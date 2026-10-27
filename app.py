"""Simulador de interrupciones · fase de validación (Streamlit Community Cloud)."""
import csv
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
import streamlit as st
from shapely.geometry import box, shape
from shapely.ops import unary_union
from streamlit_folium import st_folium

from core import ficha as F
from core import geometria as G
from core import parametros as P
from core import rios as R
from core import ventanas as V
from core.decision import fmt_min, recomendar_varios
from core.modelos import Ruta
from data.hidrologia import ultimos_datos
from data.rutas import rutas_activas
from engines.here import MotorHERE
from engines.ors import ErrorRuteo, MotorORS

st.set_page_config(page_title="Rutas alternas · Simulador", layout="wide")
TZ = ZoneInfo("America/Lima")
CENTRO = (-8.11, -79.03)  # Trujillo
COLORES = {"DESVIAR": "#C2570C", "ESPERAR": "#1D5FB8", "CONTINUAR": "#0E7A5F", "SIN_ALTERNA": "#4A5866"}
RUTA_RIOS = Path(__file__).parent / "datos" / "rios.geojson"
TABLA_HIDRO = "appsheetgr.BD_Procesamiento.senamhi_hidrologia"
TABLA_RUTAS = "appsheetgr.BD_Procesamiento.fen_7_rutas"
MANUAL = "(Marcar en el mapa)"


# ---------- Motor y caché (cada consulta cuenta para la cuota diaria de ORS) ----------
@st.cache_resource
def motor() -> MotorORS:
    return MotorORS(st.secrets["ORS_API_KEY"])


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def calcular_ruta(coords: tuple, perfil_clave: str | None, evitar_json: str | None,
                  perfil_ors: str = "driving-hgv"):
    evitar = json.loads(evitar_json) if evitar_json else None
    perfil = P.PERFILES[perfil_clave] if perfil_clave else None
    return motor().ruta([list(c) for c in coords], perfil, evitar, perfil_ors)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def ajustar(lon: float, lat: float):
    return motor().ajustar_a_via(lon, lat)


@st.cache_resource
def contador_here() -> dict:
    """Consultas a HERE hechas hoy (se reinicia cada día o si la app se reinicia)."""
    return {"fecha": None, "n": 0}


def limite_here() -> int:
    return int(st.secrets.get("HERE_LIMITE_DIARIO", 100))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def ruta_here(coords: tuple, perfil_clave: str, cajas: tuple, evitar_tierra: bool):
    """Consulta a HERE. Solo las consultas nuevas (no las que vienen de la caché) cuentan para el límite."""
    c = contador_here()
    hoy = datetime.now(TZ).date()
    if c["fecha"] != hoy:
        c.update(fecha=hoy, n=0)
    if c["n"] >= limite_here():
        raise ErrorRuteo(f"Se alcanzó el límite diario de {limite_here()} consultas a HERE configurado en la app.")
    c["n"] += 1
    return MotorHERE(st.secrets["HERE_API_KEY"]).ruta([list(x) for x in coords], P.PERFILES[perfil_clave],
                                                     list(cajas), evitar_tierra)


def comparar_con_here(base: dict) -> list:
    """Ruta habitual y dos alternas de HERE (rápida y evitando caminos de tierra) para el mismo escenario."""
    union = shape(base["poligonos"])
    partes = list(union.geoms) if hasattr(union, "geoms") else [union]
    cajas = tuple(tuple(round(v, 6) for v in g.bounds) for g in partes)
    perfil = P.PERFILES[base["perfil"]]
    filas, lineas = [], []
    try:
        hab = ruta_here(tuple(map(tuple, base["coords"])), base["perfil"], (), False)
    except ErrorRuteo as e:
        return [{"Variante": "HERE · ruta habitual", "Resultado": str(e)}], []
    cands = base.get("candidatas") or []
    alterna_ors = cands[min(ss.get("cand_sel", 0), len(cands) - 1)]["alt"] if cands else None
    for nombre, tierra in (("HERE · rápida", False), ("HERE · evita caminos de tierra", True)):
        try:
            alt = ruta_here(tuple(map(tuple, base["coords"])), base["perfil"], cajas, tierra)
        except ErrorRuteo as e:
            filas.append({"Variante": nombre, "Resultado": f"Sin ruta ({e})"})
            continue
        evita = not G.ruta_cruza(alt.coords, union)
        fi = F.analizar([(alt.coords, {})], hab.coords, perfil)
        coinc = G.coincidencia_desvio(alt.coords, alterna_ors, hab.coords) if alterna_ors else None
        filas.append({
            "Variante": nombre,
            "Resultado": "Evita el bloqueo" if evita else "Pasa por el bloqueo",
            "Habitual": fmt_min(hab.duracion_min), "Alterna": fmt_min(alt.duracion_min),
            "Diferencia": f"+{fmt_min(alt.duracion_min - hab.duracion_min)}",
            "Desvío": f"{fi['km_desvio']:.1f} km",
            "Curvas críticas / invaden": f"{fi['curvas_criticas']} / {fi['curvas_invade']}",
            "Coincide con alterna ORS": "—" if coinc is None else f"{coinc:.0%}",
            "Avisos HERE": "; ".join(dict.fromkeys(alt.extras.get("avisos_here", []))) or "—"})
        lineas.append({"nombre": nombre, "coords": alt.coords, "evita": evita})
    return filas, lineas


def filas_ors(base: dict) -> list:
    filas = []
    for c in base.get("candidatas") or []:
        fi = c["ficha"]
        filas.append({"Variante": f"ORS · {c['nombre']}", "Resultado": "Evita el bloqueo",
                      "Habitual": fmt_min(base["t_orig"]), "Alterna": fmt_min(c["t_alt"]),
                      "Diferencia": f"+{fmt_min(c['t_alt'] - base['t_orig'])}", "Desvío": f"{fi['km_desvio']:.1f} km",
                      "Curvas críticas / invaden": f"{fi['curvas_criticas']} / {fi['curvas_invade']}",
                      "Coincide con alterna ORS": "—", "Avisos HERE": "—"})
    return filas


def a_csv(filas: list, contexto: dict) -> str:
    salida = io.StringIO()
    columnas = list(contexto) + sorted({k for f in filas for k in f}, key=lambda k: list(filas[0]).index(k)
                                       if k in filas[0] else 99)
    w = csv.DictWriter(salida, fieldnames=columnas)
    w.writeheader()
    for f in filas:
        w.writerow({**contexto, **f})
    return salida.getvalue()


@st.cache_resource
def cargar_rios() -> list:
    """Trazado de ríos generado por la acción 'Actualizar ríos' (datos/rios.geojson)."""
    if not RUTA_RIOS.exists():
        return []
    fc = json.loads(RUTA_RIOS.read_text(encoding="utf-8"))
    return [dict(f, _geom=shape(f["geometry"])) for f in fc.get("features", [])]


@st.cache_data(ttl=600, show_spinner=False)
def estado_rios():
    """Nivel de alerta por río según el último dato de hidrología. None si no hay conexión."""
    if "gcp_service_account" not in st.secrets:
        return None
    filas = ultimos_datos(dict(st.secrets["gcp_service_account"]), st.secrets.get("BQ_TABLA_HIDRO", TABLA_HIDRO))
    return R.estado_por_rio(filas, datetime.now(TZ).replace(tzinfo=None))


@st.cache_data(ttl=600, show_spinner=False)
def cargar_rutas() -> list:
    if "gcp_service_account" not in st.secrets:
        return []
    return rutas_activas(dict(st.secrets["gcp_service_account"]), st.secrets.get("BQ_TABLA_RUTAS", TABLA_RUTAS))


def alterna_por_ventanas(coords: tuple, orig: Ruta, en_ruta: list, poligonos: list, perfil_clave: str):
    """Calcula la alterna. Si la consulta completa supera el límite de la API (150 km en línea recta),
    la calcula solo en ventanas alrededor de los bloqueos y la une con la ruta habitual.
    Devuelve (Ruta o None, error, ventanas [(inicio, fin)], (extremos, evitar) para diagnóstico,
    piezas [(coords, extras)] calculadas por el motor, para la ficha técnica)."""
    union = unary_union(poligonos)
    if V.distancia_recta_total(coords) <= V.LIMITE_KM:
        evitar = json.dumps(G.a_geojson(union))
        try:
            alt = calcular_ruta(coords, perfil_clave, evitar)
        except ErrorRuteo as e:
            return None, str(e), [], (coords, evitar), []
        if G.ruta_cruza(alt.coords, union):
            return None, "La única ruta que encontró el motor pasa por algún bloqueo.", [], (coords, evitar), []
        return alt, None, [], (coords, evitar), [(alt.coords, alt.extras)]

    acc = V.acumuladas_km(orig.coords)
    grupos = V.agrupar([b["frac"] * acc[-1] for b in en_ruta], orig.coords, acc)
    tramos_geo, tramos_t, ventanas, diag, piezas = [], [], [], None, []
    for (ini, fin), (km_min, km_max) in zip(grupos, V.limites_de_grupos(grupos, acc[-1])):
        limite = V.LIMITE_KM
        for intento in range(3):
            i, j = V.ventana(orig.coords, acc, ini, fin, km_min, km_max, limite)
            extremos = (tuple(orig.coords[i]), tuple(orig.coords[j]))
            xs = [c[0] for c in orig.coords[i:j + 1]]
            ys = [c[1] for c in orig.coords[i:j + 1]]
            caja = box(min(xs) - 0.3, min(ys) - 0.3, max(xs) + 0.3, max(ys) + 0.3)
            locales = unary_union([p for p in poligonos if p.intersects(caja)])
            evitar = json.dumps(G.a_geojson(locales))
            diag = diag or (extremos, evitar)
            try:
                alt = calcular_ruta(extremos, perfil_clave, evitar)
                break
            except ErrorRuteo as e:
                if "must not be greater" in str(e) and intento < 2:
                    limite *= 0.8          # ORS estimó la distancia distinto: se achica la ventana y se reintenta
                    continue
                return (None, f"Sin alterna dentro de la ventana de {V.distancia_km(*extremos):.0f} km "
                              f"alrededor del bloqueo. {e}", ventanas, diag, piezas)
        if G.ruta_cruza(alt.coords, locales):
            return None, "La única ruta que encontró el motor pasa por algún bloqueo.", ventanas, diag, piezas
        ventanas.append(extremos)
        piezas.append((alt.coords, alt.extras))
        tramos_geo.append((i, j, alt.coords))
        tramos_t.append((i, j, alt.duracion_min, alt.distancia_km))
    coords_alt = V.empalmar(orig.coords, tramos_geo)
    if G.ruta_cruza(coords_alt, union):
        return None, "La alterna resultante pasa por otro bloqueo.", ventanas, diag, piezas
    t, d = V.tiempos_empalmados(orig.duracion_min, orig.distancia_km, acc, tramos_t)
    return Ruta(t, d, coords_alt), None, ventanas, diag, piezas


def generar_candidatas(coords, orig, en_ruta, poligonos, perfil_clave):
    """Alterna A (la más rápida) y, si tiene tramos sin pavimentar, alterna B que los evita cortándolos
    con zonas pequeñas (hasta 2 rondas). Devuelve (candidatas, error, diagnóstico)."""
    perfil = P.PERFILES[perfil_clave]
    alt, error, ventanas, diag, piezas = alterna_por_ventanas(coords, orig, en_ruta, poligonos, perfil_clave)
    if not alt:
        return [], error, diag
    ficha = F.analizar(piezas, orig.coords, perfil)
    candidatas = [{"nombre": "A · Más rápida", "ruta": alt, "ficha": ficha, "ventanas": ventanas}]
    cortes = []
    for _ronda in range(2):
        nuevos = F.cortes_sin_pavimentar(ficha)
        if not nuevos:
            break
        cortes += [G.poligono_bloqueo(lon, lat, 60) for lon, lat in nuevos]
        alt_b, _, ventanas_b, _, piezas_b = alterna_por_ventanas(coords, orig, en_ruta, poligonos + cortes, perfil_clave)
        if not alt_b:
            break
        ficha = F.analizar(piezas_b, orig.coords, perfil)
        if ficha["km_sin_pavimentar"] < candidatas[-1]["ficha"]["km_sin_pavimentar"] - 0.5:
            candidata = {"nombre": "B · Prioriza vía pavimentada", "ruta": alt_b, "ficha": ficha, "ventanas": ventanas_b}
            candidatas = candidatas[:1] + [candidata]
        if ficha["km_sin_pavimentar"] < 0.5:
            break
    t_rapida = min(c["ruta"].duracion_min for c in candidatas)
    for c in candidatas:
        c["pros"], c["contras"] = F.pros_contras(c["ficha"], c["ruta"].duracion_min, t_rapida,
                                                c["ruta"].distancia_km - orig.distancia_km)
    return candidatas, None, diag


def redondear(p):
    return (round(p[0], 5), round(p[1], 5)) if p else None


def reapertura_en_min(texto: str) -> float:
    return P.REAPERTURA_OPCIONES.get(texto) or P.REAPERTURA_DESCONOCIDA_MIN


# ---------- Estado ----------
ss = st.session_state
ss.setdefault("puntos", {"origen": None, "destino": None})
ss.setdefault("puntos_paso", [])
ss.setdefault("bloqueos", [])        # [{"id", "lon", "lat", "reap"}]
ss.setdefault("ultimo_click", None)
ss.setdefault("resultado", None)
ss.setdefault("ruta_sel", MANUAL)


def invalidar():
    ss.resultado = None


# ---------- Rutas predefinidas ----------
aviso_rutas = None
try:
    rutas = cargar_rutas()
except Exception as e:
    rutas, aviso_rutas = [], f"No se pudieron leer las rutas guardadas ({e.__class__.__name__})."
rutas_por_nombre = {r["nombre"]: r for r in rutas}


def aplicar_ruta():
    ruta = rutas_por_nombre.get(ss.selector_ruta)
    ss.ruta_sel = ss.selector_ruta
    if ruta:
        ss.puntos = {"origen": ruta["origen"], "destino": ruta["destino"]}
        ss.puntos_paso = list(ruta["puntos_paso"])
    else:
        ss.puntos = {"origen": None, "destino": None}
        ss.puntos_paso = []
    invalidar()


# ---------- Barra lateral ----------
with st.sidebar:
    st.header("Escenario")
    opciones_ruta = [MANUAL] + list(rutas_por_nombre)
    st.selectbox("Ruta", opciones_ruta, key="selector_ruta", on_change=aplicar_ruta,
                 index=opciones_ruta.index(ss.ruta_sel) if ss.ruta_sel in opciones_ruta else 0)
    ruta_actual = rutas_por_nombre.get(ss.ruta_sel)
    if aviso_rutas:
        st.caption(aviso_rutas)

    claves_carga = list(P.CARGAS)
    carga_def = ruta_actual["tipo_carga"] if ruta_actual and ruta_actual["tipo_carga"] in P.CARGAS else claves_carga[0]
    carga_clave = st.selectbox("Tipo de carga", claves_carga, index=claves_carga.index(carga_def),
                               format_func=lambda k: P.CARGAS[k].nombre, on_change=invalidar)
    carga = P.CARGAS[carga_clave]
    claves_perfil = list(P.PERFILES)
    perfil_def = ruta_actual["perfil"] if ruta_actual and ruta_actual["perfil"] in P.PERFILES else carga.perfil_sugerido
    perfil_clave = st.selectbox("Vehículo", claves_perfil, index=claves_perfil.index(perfil_def),
                                format_func=lambda k: P.PERFILES[k].nombre, on_change=invalidar)
    hora = st.time_input("Hora del escenario", datetime.now(TZ).time().replace(second=0, microsecond=0),
                         on_change=invalidar)
    radio = st.slider("Radio del bloqueo (m)", 50, 500, P.RADIO_BLOQUEO_M, 25, on_change=invalidar)
    mostrar_todos = st.checkbox("Mostrar todos los ríos monitoreados", value=False)
    if st.button("Limpiar bloqueos", width="stretch"):
        ss.bloqueos = []
        invalidar()
        st.rerun()
    st.divider()
    st.caption("Parámetros provisionales · pendientes de validación.")

st.title("Simulador de interrupciones")
st.caption("Fase de validación · rutas de OpenStreetMap calculadas con OpenRouteService")


def coords_ruta() -> tuple | None:
    o, d = ss.puntos["origen"], ss.puntos["destino"]
    if not (o and d):
        return None
    return tuple([tuple(o)] + [tuple(p) for p in ss.puntos_paso] + [tuple(d)])


# Vista previa de la ruta habitual apenas hay origen y destino (una consulta, luego queda en caché)
vista_previa, error_previa = None, None
if coords_ruta() and not ss.resultado:
    try:
        vista_previa = calcular_ruta(coords_ruta(), perfil_clave, None)
    except ErrorRuteo as e:
        error_previa = str(e)

# ---------- Ríos: trazado, estado y cruces con las rutas ----------
rios = cargar_rios()
aviso_hidro = None
try:
    estados = estado_rios()
    if estados is None:
        aviso_hidro = "Sin conexión a BigQuery: ríos sin estado de alerta y sin rutas guardadas."
except Exception as e:  # la app sigue funcionando aunque BigQuery falle
    estados, aviso_hidro = None, f"No se pudo leer la hidrología ({e.__class__.__name__}). Ríos sin estado."
estados = estados or {}

def vista_resultado():
    """Resultado con la alterna elegida volcada en los campos que usan el mapa y el panel."""
    res = ss.resultado
    if res and res.get("en_ruta"):
        cands = res.get("candidatas") or []
        sel = min(ss.get("cand_sel", 0), len(cands) - 1) if cands else None
        res = dict(res, **(cands[sel] if cands else {"rec": res["rec_sin_alterna"]}), sel=sel)
    return res


r = vista_resultado()
linea_habitual = r["orig"] if r else (vista_previa.coords if vista_previa else None)
cruces_orig = R.cruces(linea_habitual, rios) if linea_habitual else []
cruces_alt = R.cruces(r["alt"], rios) if r and r.get("alt") else []
claves_cruzadas = {c["clave"] for c in cruces_orig + cruces_alt}


def nivel_de(clave: str) -> str:
    return estados.get(clave, {}).get("nivel", "sin_dato")


def detalle_de(clave: str) -> str:
    return "<br>".join(estados.get(clave, {}).get("detalle", [])) or "Sin estación con datos recientes"


col_mapa, col_res = st.columns([3, 2], gap="large")

# ---------- Mapa ----------
with col_mapa:
    modo = st.radio("Al hacer clic en el mapa:", ["Agregar bloqueo", "Mover camión", "Mover destino"],
                    horizontal=True)

    m = folium.Map(location=CENTRO, zoom_start=9, control_scale=True)
    for f in rios:
        k = f["properties"]["clave"]
        if not (mostrar_todos or k in claves_cruzadas):
            continue
        nivel = nivel_de(k)
        folium.GeoJson({"type": "Feature", "geometry": f["geometry"], "properties": f["properties"]},
                       style_function=lambda _, c=R.COLORES[nivel], w=(5 if k in claves_cruzadas else 2.5):
                       {"color": c, "weight": w, "opacity": 0.85},
                       tooltip=f"Río {f['properties']['rio']} · {R.ETIQUETAS[nivel]}").add_to(m)
    if linea_habitual:
        folium.PolyLine([(y, x) for x, y in linea_habitual], color="#1D5FB8", weight=6,
                        tooltip="Ruta habitual").add_to(m)
    for k, c in enumerate((r or {}).get("candidatas") or []):
        if k != r.get("sel"):
            folium.PolyLine([(y, x) for x, y in c["alt"]], color="#8896A4", weight=4, dash_array="6 8",
                            tooltip=f"Alterna {c['nombre']}").add_to(m)
    for lh in (r or {}).get("here_lineas") or []:
        folium.PolyLine([(y, x) for x, y in lh["coords"]], color="#6B3FA0", weight=4, dash_array="2 8",
                        tooltip=f"{lh['nombre']}" + ("" if lh["evita"] else " · pasa por el bloqueo")).add_to(m)
    for cv in ((r or {}).get("ficha") or {}).get("curvas", []):
        if cv["nivel"] != "ok":
            color = "#B42318" if cv["nivel"] == "critica" else "#D4A300"
            texto = "no pasa sin maniobra" if cv["nivel"] == "critica" else "invade carril contrario"
            folium.RegularPolygonMarker((cv["lat"], cv["lon"]), number_of_sides=3, radius=7, color="#FFFFFF",
                                        weight=1, fill=True, fill_color=color, fill_opacity=1,
                                        tooltip=f"Curva de radio ~{cv['radio_m']:.0f} m: {texto}").add_to(m)
    if r and r.get("alt"):
        folium.PolyLine([(y, x) for x, y in r["alt"]], color="#C2570C", weight=5, dash_array="10 8",
                        tooltip="Alterna").add_to(m)
    if r and r.get("poligonos"):
        folium.GeoJson(r["poligonos"], style_function=lambda _: {"color": "#B42318", "fillOpacity": 0.35}).add_to(m)
    for k, (ini, fin) in enumerate((r or {}).get("ventanas") or [], start=1):
        for punto, texto in ((ini, "inicio"), (fin, "fin")):
            folium.CircleMarker((punto[1], punto[0]), radius=5, color="#4A5866", fill=True, fill_color="#FFFFFF",
                                fill_opacity=1, tooltip=f"Ventana {k}: {texto} del tramo recalculado").add_to(m)
    if r and r.get("divergencia"):
        lon, lat = r["divergencia"][:2]
        folium.CircleMarker((lat, lon), radius=9, color="#15202B", fill=True, fill_color="#FFFFFF",
                            fill_opacity=1, tooltip="Punto de decisión").add_to(m)
    vistos = set()
    for c in cruces_orig + cruces_alt:
        clave_punto = (round(c["lon"], 4), round(c["lat"], 4))
        if clave_punto in vistos:
            continue
        vistos.add(clave_punto)
        nivel = nivel_de(c["clave"])
        folium.CircleMarker((c["lat"], c["lon"]), radius=8, color="#FFFFFF", weight=2, fill=True,
                            fill_color=R.COLORES[nivel], fill_opacity=1,
                            tooltip=folium.Tooltip(f"<b>Cruce río {c['rio']}</b> · {R.ETIQUETAS[nivel]}"
                                                   f"<br>{detalle_de(c['clave'])}")).add_to(m)
    nombre_o = ruta_actual["origen_nombre"] if ruta_actual else "Camión"
    nombre_d = ruta_actual["destino_nombre"] if ruta_actual else "Destino"
    if ss.puntos["origen"]:
        o = ss.puntos["origen"]
        folium.Marker((o[1], o[0]), tooltip=f"Camión · {nombre_o}",
                      icon=folium.Icon(color="blue", icon="truck", prefix="fa")).add_to(m)
    if ss.puntos["destino"]:
        d = ss.puntos["destino"]
        folium.Marker((d[1], d[0]), tooltip=nombre_d, icon=folium.Icon(color="black", icon="flag", prefix="fa")).add_to(m)
    for i, b in enumerate(ss.bloqueos, start=1):
        folium.Marker((b["lat"], b["lon"]), tooltip=f"Bloqueo {i} · reapertura {b['reap']}",
                      icon=folium.Icon(color="red", icon="ban", prefix="fa")).add_to(m)
    extremos = (linea_habitual or []) + ((r.get("alt") or []) if r else [])
    if extremos:
        xs, ys = [c[0] for c in extremos], [c[1] for c in extremos]
        m.fit_bounds([(min(ys), min(xs)), (max(ys), max(xs))])

    salida = st_folium(m, height=600, use_container_width=True, key="mapa", returned_objects=["last_clicked"])
    click = salida.get("last_clicked") if salida else None
    if click:
        punto = redondear((click["lng"], click["lat"]))
        if punto != ss.ultimo_click:
            ss.ultimo_click = punto
            if modo == "Agregar bloqueo":
                ss.bloqueos.append({"id": uuid.uuid4().hex[:8], "lon": punto[0], "lat": punto[1], "reap": "1–3 h"})
            elif modo == "Mover camión":
                ss.puntos["origen"] = punto
            else:
                ss.puntos["destino"] = punto
            invalidar()
            st.rerun()

# ---------- Panel ----------
with col_res:
    if aviso_hidro:
        st.caption(aviso_hidro)
    if not rios:
        st.caption("Aún no hay trazado de ríos: ejecuta la acción «Actualizar ríos» en GitHub.")
    if error_previa:
        st.error(f"No se pudo calcular la ruta habitual. {error_previa}")

    # Lista de bloqueos, cada uno con su reapertura
    if ss.bloqueos:
        st.subheader("Bloqueos")
        for i, b in enumerate(list(ss.bloqueos), start=1):
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            opciones = list(P.REAPERTURA_OPCIONES)
            nuevo = c1.selectbox(f"Bloqueo {i} · reapertura estimada", opciones, index=opciones.index(b["reap"]),
                                 key=f"reap_{b['id']}")
            if nuevo != b["reap"]:
                b["reap"] = nuevo
                invalidar()
            if c2.button("Quitar", key=f"quitar_{b['id']}", width="stretch"):
                ss.bloqueos = [x for x in ss.bloqueos if x["id"] != b["id"]]
                invalidar()
                st.rerun()
        st.caption("Se usa el extremo superior de cada rango (criterio conservador). "
                   f"«No sé» = {fmt_min(P.REAPERTURA_DESCONOCIDA_MIN)} (provisional).")

    faltan = [n for n, ok in (("camión", ss.puntos["origen"]), ("destino", ss.puntos["destino"]),
                              ("al menos un bloqueo", ss.bloqueos)) if not ok]
    if faltan:
        st.info("Falta: " + ", ".join(faltan) + ". Elige una ruta en la barra lateral o marca en el mapa.")

    if st.button("Calcular", type="primary", disabled=bool(faltan), width="stretch"):
        coords = coords_ruta()
        with st.spinner("Calculando rutas…"):
            try:
                orig = calcular_ruta(coords, perfil_clave, None)
            except ErrorRuteo as e:
                st.error(f"No se pudo calcular la ruta habitual. {e}")
                st.stop()

            poligonos, en_ruta, fuera = [], [], []
            for i, b in enumerate(ss.bloqueos, start=1):
                try:
                    snap = ajustar(b["lon"], b["lat"])
                except ErrorRuteo:
                    snap = None
                lon, lat = (snap[0], snap[1]) if snap else (b["lon"], b["lat"])
                poly = G.poligono_bloqueo(lon, lat, radio)
                poligonos.append(poly)
                info = {"n": i, "reap": b["reap"], "via": snap[2] if snap else ""}
                if G.ruta_cruza(orig.coords, poly):
                    info["frac"] = G.fraccion_hasta(orig.coords, lon, lat)
                    info["t_hasta"] = orig.duracion_min * info["frac"]
                    en_ruta.append(info)
                else:
                    fuera.append(info)

            union = unary_union(poligonos)
            res = {"orig": orig.coords, "poligonos": G.a_geojson(union), "t_orig": orig.duracion_min,
                   "d_orig": orig.distancia_km, "coords": coords, "perfil": perfil_clave,
                   "en_ruta": en_ruta, "fuera": fuera}
            ss.diagnostico = None

            if en_ruta:
                candidatas, error, diag = generar_candidatas(coords, orig, en_ruta, poligonos, perfil_clave)
                res.update(diag_coords=diag[0], diag_evitar=diag[1], t_hasta=min(b["t_hasta"] for b in en_ruta))
                if error:
                    res["error_alt"] = error
                bloqueos_t = [(b["t_hasta"], reapertura_en_min(b["reap"])) for b in en_ruta]
                res["rec_sin_alterna"] = recomendar_varios(orig.duracion_min, None, bloqueos_t, carga, hora.hour)
                res["candidatas"] = []
                for c in candidatas:
                    alt = c["ruta"]
                    div = G.punto_divergencia(orig.coords, alt.coords)
                    res["candidatas"].append({
                        "nombre": c["nombre"], "alt": alt.coords, "t_alt": alt.duracion_min, "d_alt": alt.distancia_km,
                        "ficha": c["ficha"], "pros": c["pros"], "contras": c["contras"], "ventanas": c["ventanas"],
                        "rec": recomendar_varios(orig.duracion_min, alt.duracion_min, bloqueos_t, carga, hora.hour),
                        "divergencia": div, "km_decision": div[2] * orig.distancia_km if div else None,
                        "enlace": G.enlace_google_maps(coords[0], coords[-1], G.puntos_exclusivos(alt.coords, orig.coords)),
                        "gpx": F.a_gpx(c["nombre"], alt.coords)})
                if res["candidatas"]:
                    res["sugerida"] = min(range(len(res["candidatas"])),
                                          key=lambda k: F.clave_orden(res["candidatas"][k]["ficha"],
                                                                      res["candidatas"][k]["t_alt"]))
                    ss.cand_sel = res["sugerida"]
            ss.resultado = res
        st.rerun()

    r = vista_resultado()
    if r:
        for b in r["fuera"]:
            st.caption(f"Bloqueo {b['n']}: no está sobre la ruta habitual.")
        if not r["en_ruta"]:
            st.success("Ningún bloqueo está sobre la ruta habitual: el camión puede continuar normalmente.")
            st.caption(f"Ruta habitual: {fmt_min(r['t_orig'])} · {r['d_orig']:.1f} km")
        else:
            cands = r.get("candidatas") or []
            if len(cands) > 1:
                etiquetas = [f"{c['nombre']} · {fmt_min(c['t_alt'])} · {c['ficha']['km_sin_pavimentar']:.0f} km sin pavimentar"
                             + (" · sugerida" if k == r.get("sugerida") else "") for k, c in enumerate(cands)]
                elegida = st.radio("Alterna a evaluar", range(len(cands)), index=r["sel"],
                                   format_func=lambda k: etiquetas[k])
                if elegida != r["sel"]:
                    ss.cand_sel = elegida
                    st.rerun()
                st.caption("Se sugiere la alterna sin curvas críticas y con menos tramos sin pavimentar; "
                           "a igualdad, la más rápida. La decisión final es del encargado.")
            rec = r["rec"]
            st.markdown(f"<div style='background:{COLORES[rec.accion]};color:#fff;padding:14px 16px;"
                        f"border-radius:10px;font-size:1.4rem;font-weight:700'>{rec.titulo}</div>",
                        unsafe_allow_html=True)
            for t in rec.razones:
                st.write(t)
            c1, c2 = st.columns(2)
            c1.metric("Ruta habitual", fmt_min(r["t_orig"]), f"+ espera {fmt_min(rec.espera_real_min)}",
                      delta_color="off")
            c2.metric("Alterna", fmt_min(r.get("t_alt")),
                      f"{r['d_alt'] - r['d_orig']:+.1f} km" if r.get("t_alt") else None, delta_color="off")
            c3, c4 = st.columns(2)
            c3.metric("Espera máxima", fmt_min(rec.espera_max_min))
            c4.metric("Llega al primer bloqueo en", fmt_min(r["t_hasta"]))
            for b in sorted(r["en_ruta"], key=lambda x: x["t_hasta"]):
                via = f" · {b['via']}" if b["via"] else ""
                st.caption(f"Bloqueo {b['n']}{via}: llega en {fmt_min(b['t_hasta'])} · reapertura {b['reap']}")
            if r.get("km_decision") is not None:
                st.write(f"**Punto de decisión:** a {r['km_decision']:.1f} km de la posición del camión.")
            for a in rec.avisos:
                st.warning(a)

            # ---------- Ríos cruzados ----------
            for titulo, lista in (("habitual", cruces_orig), ("alterna", cruces_alt)):
                if not lista:
                    continue
                nombres = ", ".join(dict.fromkeys(f"{c['rio']} ({R.ETIQUETAS[nivel_de(c['clave'])].lower()})"
                                                  for c in lista))
                st.write(f"**Ríos que cruza la ruta {titulo}:** {nombres}")
                for c in {c["clave"]: c for c in lista}.values():
                    if nivel_de(c["clave"]) in ("naranja", "rojo"):
                        st.warning(f"La ruta {titulo} cruza el río {c['rio']} en "
                                   f"{R.ETIQUETAS[nivel_de(c['clave'])].lower()}. "
                                   + detalle_de(c["clave"]).replace("<br>", " · "))
            if r.get("ficha"):
                fi = r["ficha"]
                st.markdown("**Validación:** Nivel 4 · sin validar en campo (calculada por el motor).")
                with st.expander("Ficha técnica del desvío", expanded=True):
                    for p in r["pros"]:
                        st.markdown(f"✅ {p}")
                    for c in r["contras"]:
                        st.markdown(f"⚠️ {c}")
                    st.dataframe([
                        {"Dato": "Longitud del desvío", "Valor": f"{fi['km_desvio']:.1f} km"},
                        {"Dato": "Pavimentado", "Valor": f"{fi['km_pavimentada']:.1f} km"},
                        {"Dato": "Sin pavimentar", "Valor": f"{fi['km_sin_pavimentar']:.1f} km (trocha: {fi['km_trocha']:.1f} km)"},
                        {"Dato": "Sin dato de superficie", "Valor": f"{fi['km_desconocida']:.1f} km"},
                        {"Dato": "Pendiente ≥ 7 % / ≥ 12 %", "Valor": f"{fi['km_pendiente_7']:.1f} km / {fi['km_pendiente_12']:.1f} km"},
                        {"Dato": "Curvas que no pasa sin maniobra", "Valor": str(fi["curvas_criticas"])},
                        {"Dato": "Curvas que invaden carril contrario", "Valor": str(fi["curvas_invade"])},
                        {"Dato": "Vados / túneles", "Valor": f"{fi['vados']} / {fi['tuneles']}"},
                    ], hide_index=True, width="stretch")
                    st.caption("Datos de OpenStreetMap y estimaciones a partir del trazado; el ancho de vía y las "
                               "distancias entre ejes son valores provisionales. Sirve para decidir qué inspeccionar, "
                               "no reemplaza la inspección.")
                    st.download_button("Descargar GPX para la inspección", r["gpx"],
                                       file_name=f"alterna_{r['nombre'].split(' ')[0]}.gpx",
                                       mime="application/gpx+xml", width="stretch")
            if r.get("ventanas"):
                n = len(r["ventanas"])
                st.caption(f"La alterna se calculó en {n} {'ventana' if n == 1 else 'ventanas'} alrededor de los "
                           "bloqueos (límite de 150 km de la API gratuita) y se unió con la ruta habitual.")
            if r.get("error_alt"):
                st.caption(f"Detalle del motor: {r['error_alt']}")
            if r.get("enlace"):
                st.link_button("Abrir alterna en Google Maps", r["enlace"], width="stretch")
                st.caption("Google recalcula entre puntos intermedios; verifica que siga la alterna.")

            # ---------- Diagnóstico ----------
            with st.expander("Diagnóstico: comparar variantes de la alterna"):
                st.caption("Calcula la alterna con tres variantes para saber por qué no aparece "
                           "(en la primera ventana, si la ruta es larga). Usa hasta 3 consultas de la cuota diaria.")
                if st.button("Ejecutar diagnóstico", width="stretch"):
                    evitar_json = r["diag_evitar"]
                    poly = shape(json.loads(evitar_json))
                    filas = []
                    variantes = [("Camión con dimensiones", r["perfil"], "driving-hgv"),
                                 ("Camión sin dimensiones", None, "driving-hgv"),
                                 ("Auto (similar a Google Maps)", None, "driving-car")]
                    for nombre, pk, pors in variantes:
                        try:
                            rr = calcular_ruta(tuple(r["diag_coords"]), pk, evitar_json, pors)
                            evita = not G.ruta_cruza(rr.coords, poly)
                            filas.append({"Variante": nombre,
                                          "Resultado": "Encontró alterna" if evita else "Pasa por el bloqueo",
                                          "Tiempo": fmt_min(rr.duracion_min),
                                          "Distancia": f"{rr.distancia_km:.1f} km"})
                        except ErrorRuteo as e:
                            filas.append({"Variante": nombre, "Resultado": f"Sin ruta ({e})",
                                          "Tiempo": "—", "Distancia": "—"})
                    ss.diagnostico = filas
                if ss.get("diagnostico"):
                    st.dataframe(ss.diagnostico, hide_index=True, width="stretch")
                    st.markdown(
                        "- **Solo el auto encuentra alterna:** el camino existe, pero el mapa lo marca como no apto "
                        "para camión o es una trocha. Confirmar con los choferes si de verdad pasa un camión.\n"
                        "- **Camión sin dimensiones sí, con dimensiones no:** alguna vía de la alterna tiene "
                        "límite de peso, altura o ancho en el mapa.\n"
                        "- **Ninguna encuentra:** la vía falta o está desconectada en OpenStreetMap, o el radio "
                        "del bloqueo también cubre el cruce de la alterna. Reduce el radio y vuelve a calcular.")

            # ---------- Prueba comparativa con HERE ----------
            if "HERE_API_KEY" in st.secrets:
                with st.expander("Prueba comparativa: ORS vs. HERE", expanded=bool(r.get("here_filas"))):
                    usadas = contador_here()["n"] if contador_here()["fecha"] == datetime.now(TZ).date() else 0
                    st.caption(f"Usa hasta 3 consultas de HERE: ruta habitual, alterna rápida y alterna que evita "
                               f"caminos de tierra. Repetir el mismo escenario no consume más. "
                               f"Consultas hoy: {usadas} de {limite_here()}.")
                    if st.button("Comparar con HERE", width="stretch"):
                        with st.spinner("Consultando HERE…"):
                            filas_h, lineas_h = comparar_con_here(ss.resultado)
                        ss.resultado["here_filas"], ss.resultado["here_lineas"] = filas_h, lineas_h
                        st.rerun()
                    if r.get("here_filas"):
                        tabla = filas_ors(ss.resultado) + r["here_filas"]
                        st.dataframe(tabla, hide_index=True, width="stretch")
                        st.markdown(
                            "- **Coincide con alterna ORS:** qué parte del desvío de HERE va por el mismo camino que "
                            "la alterna ORS elegida. Alto = ambos motores coinciden; bajo = proponen caminos distintos "
                            "y conviene revisar ambos.\n"
                            "- Cada motor calcula sus propios tiempos; compara la **diferencia** de cada uno contra su "
                            "propia ruta habitual.\n"
                            "- En HERE, evitar una zona es una preferencia: si no hay otra forma, puede pasar por el "
                            "bloqueo, y la tabla lo indica.\n"
                            "- Las alternas de HERE se ven en el mapa en morado punteado.")
                        contexto = {"fecha": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "ruta": ss.ruta_sel,
                                    "vehiculo": ss.resultado["perfil"],
                                    "bloqueos": "; ".join(f"{b['lat']:.5f},{b['lon']:.5f}" for b in ss.bloqueos)}
                        st.download_button("Descargar comparación (CSV)", a_csv(tabla, contexto),
                                           file_name="comparacion_ors_here.csv", mime="text/csv", width="stretch")
            else:
                st.caption("Para la prueba comparativa con HERE, agrega HERE_API_KEY en los secretos.")
