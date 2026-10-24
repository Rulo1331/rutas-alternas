"""Simulador de interrupciones · fase de validación (Streamlit Community Cloud)."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
import streamlit as st
from shapely.geometry import shape
from shapely.ops import unary_union
from streamlit_folium import st_folium

from core import geometria as G
from core import parametros as P
from core import rios as R
from core.decision import fmt_min, recomendar_varios
from data.hidrologia import ultimos_datos
from data.rutas import rutas_activas
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
    if st.button("Limpiar bloqueos", use_container_width=True):
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

r = ss.resultado
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
    if r and r.get("alt"):
        folium.PolyLine([(y, x) for x, y in r["alt"]], color="#C2570C", weight=5, dash_array="10 8",
                        tooltip="Alterna").add_to(m)
    if r and r.get("poligonos"):
        folium.GeoJson(r["poligonos"], style_function=lambda _: {"color": "#B42318", "fillOpacity": 0.35}).add_to(m)
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
            if c2.button("Quitar", key=f"quitar_{b['id']}", use_container_width=True):
                ss.bloqueos = [x for x in ss.bloqueos if x["id"] != b["id"]]
                invalidar()
                st.rerun()
        st.caption("Se usa el extremo superior de cada rango (criterio conservador). "
                   f"«No sé» = {fmt_min(P.REAPERTURA_DESCONOCIDA_MIN)} (provisional).")

    faltan = [n for n, ok in (("camión", ss.puntos["origen"]), ("destino", ss.puntos["destino"]),
                              ("al menos un bloqueo", ss.bloqueos)) if not ok]
    if faltan:
        st.info("Falta: " + ", ".join(faltan) + ". Elige una ruta en la barra lateral o marca en el mapa.")

    if st.button("Calcular", type="primary", disabled=bool(faltan), use_container_width=True):
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
                    info["t_hasta"] = orig.duracion_min * G.fraccion_hasta(orig.coords, lon, lat)
                    en_ruta.append(info)
                else:
                    fuera.append(info)

            union = unary_union(poligonos)
            res = {"orig": orig.coords, "poligonos": G.a_geojson(union), "t_orig": orig.duracion_min,
                   "d_orig": orig.distancia_km, "coords": coords, "perfil": perfil_clave,
                   "en_ruta": en_ruta, "fuera": fuera}
            ss.diagnostico = None

            if en_ruta:
                try:
                    alt = calcular_ruta(coords, perfil_clave, json.dumps(res["poligonos"]))
                    if G.ruta_cruza(alt.coords, union):
                        alt = None
                        res["error_alt"] = "La única ruta que encontró el motor pasa por algún bloqueo."
                except ErrorRuteo as e:
                    alt = None
                    res["error_alt"] = str(e)
                bloqueos_t = [(b["t_hasta"], reapertura_en_min(b["reap"])) for b in en_ruta]
                res["rec"] = recomendar_varios(orig.duracion_min, alt.duracion_min if alt else None,
                                               bloqueos_t, carga, hora.hour)
                res["t_hasta"] = min(b["t_hasta"] for b in en_ruta)
                if alt:
                    div = G.punto_divergencia(orig.coords, alt.coords)
                    res.update(alt=alt.coords, t_alt=alt.duracion_min, d_alt=alt.distancia_km, divergencia=div,
                               km_decision=div[2] * orig.distancia_km if div else None,
                               enlace=G.enlace_google_maps(coords[0], coords[-1],
                                                           G.puntos_exclusivos(alt.coords, orig.coords)))
            ss.resultado = res
        st.rerun()

    r = ss.resultado
    if r:
        for b in r["fuera"]:
            st.caption(f"Bloqueo {b['n']}: no está sobre la ruta habitual.")
        if not r["en_ruta"]:
            st.success("Ningún bloqueo está sobre la ruta habitual: el camión puede continuar normalmente.")
            st.caption(f"Ruta habitual: {fmt_min(r['t_orig'])} · {r['d_orig']:.1f} km")
        else:
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
            if r.get("error_alt"):
                st.caption(f"Detalle del motor: {r['error_alt']}")
            if r.get("enlace"):
                st.link_button("Abrir alterna en Google Maps", r["enlace"], use_container_width=True)
                st.caption("Google recalcula entre puntos intermedios; verifica que siga la alterna.")

            # ---------- Diagnóstico ----------
            with st.expander("Diagnóstico: comparar variantes de la alterna"):
                st.caption("Calcula la alterna con tres variantes para saber por qué no aparece. "
                           "Usa hasta 3 consultas de la cuota diaria.")
                if st.button("Ejecutar diagnóstico", use_container_width=True):
                    poly = shape(r["poligonos"])
                    evitar_json = json.dumps(r["poligonos"])
                    filas = []
                    variantes = [("Camión con dimensiones", r["perfil"], "driving-hgv"),
                                 ("Camión sin dimensiones", None, "driving-hgv"),
                                 ("Auto (similar a Google Maps)", None, "driving-car")]
                    for nombre, pk, pors in variantes:
                        try:
                            rr = calcular_ruta(r["coords"], pk, evitar_json, pors)
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
                    st.dataframe(ss.diagnostico, hide_index=True, use_container_width=True)
                    st.markdown(
                        "- **Solo el auto encuentra alterna:** el camino existe, pero el mapa lo marca como no apto "
                        "para camión o es una trocha. Confirmar con los choferes si de verdad pasa un camión.\n"
                        "- **Camión sin dimensiones sí, con dimensiones no:** alguna vía de la alterna tiene "
                        "límite de peso, altura o ancho en el mapa.\n"
                        "- **Ninguna encuentra:** la vía falta o está desconectada en OpenStreetMap, o el radio "
                        "del bloqueo también cubre el cruce de la alterna. Reduce el radio y vuelve a calcular.")
