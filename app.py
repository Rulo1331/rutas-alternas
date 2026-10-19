"""Simulador de interrupciones · fase de validación (Streamlit Community Cloud)."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import folium
import streamlit as st
from streamlit_folium import st_folium

from core import geometria as G
from core import parametros as P
from core.decision import fmt_min, recomendar
from engines.ors import ErrorRuteo, MotorORS

st.set_page_config(page_title="Rutas alternas · Simulador", layout="wide")
TZ = ZoneInfo("America/Lima")
CENTRO = (-8.11, -79.03)  # Trujillo
COLORES = {"DESVIAR": "#C2570C", "ESPERAR": "#1D5FB8", "CONTINUAR": "#0E7A5F", "SIN_ALTERNA": "#4A5866"}


# ---------- Motor y caché (cada consulta cuenta para la cuota diaria de ORS) ----------
@st.cache_resource
def motor() -> MotorORS:
    return MotorORS(st.secrets["ORS_API_KEY"])


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def calcular_ruta(coords: tuple, perfil_clave: str, evitar_json: str | None):
    evitar = json.loads(evitar_json) if evitar_json else None
    return motor().ruta([list(c) for c in coords], P.PERFILES[perfil_clave], evitar)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def ajustar(lon: float, lat: float):
    return motor().ajustar_a_via(lon, lat)


def redondear(p):
    return (round(p[0], 5), round(p[1], 5)) if p else None


# ---------- Estado ----------
ss = st.session_state
ss.setdefault("puntos", {"origen": None, "destino": None, "bloqueo": None})
ss.setdefault("ultimo_click", None)
ss.setdefault("resultado", None)

# ---------- Barra lateral ----------
with st.sidebar:
    st.header("Escenario")
    carga_clave = st.selectbox("Tipo de carga", list(P.CARGAS), format_func=lambda k: P.CARGAS[k].nombre)
    carga = P.CARGAS[carga_clave]
    claves_perfil = list(P.PERFILES)
    perfil_clave = st.selectbox("Vehículo", claves_perfil, index=claves_perfil.index(carga.perfil_sugerido),
                                format_func=lambda k: P.PERFILES[k].nombre)
    reap_txt = st.selectbox("Reapertura estimada", list(P.REAPERTURA_OPCIONES), index=1)
    reapertura_min = P.REAPERTURA_OPCIONES[reap_txt] or P.REAPERTURA_DESCONOCIDA_MIN
    st.caption("Se usa el extremo superior del rango (criterio conservador)."
               if P.REAPERTURA_OPCIONES[reap_txt] else
               f"Sin dato: se usa {fmt_min(P.REAPERTURA_DESCONOCIDA_MIN)} (provisional).")
    hora = st.time_input("Hora del escenario", datetime.now(TZ).time().replace(second=0, microsecond=0))
    radio = st.slider("Radio del bloqueo (m)", 50, 500, P.RADIO_BLOQUEO_M, 25)
    if st.button("Limpiar escenario", use_container_width=True):
        ss.puntos = {"origen": None, "destino": None, "bloqueo": None}
        ss.resultado = None
        st.rerun()
    st.divider()
    st.caption("Parámetros provisionales · pendientes de validación.")

st.title("Simulador de interrupciones")
st.caption("Fase de validación · rutas de OpenStreetMap calculadas con OpenRouteService")

col_mapa, col_res = st.columns([3, 2], gap="large")

# ---------- Mapa ----------
with col_mapa:
    modo = st.radio("Al hacer clic en el mapa, colocar:", ["Camión", "Destino", "Bloqueo"], horizontal=True)
    clave_modo = {"Camión": "origen", "Destino": "destino", "Bloqueo": "bloqueo"}[modo]

    m = folium.Map(location=CENTRO, zoom_start=9, control_scale=True)
    r = ss.resultado
    if r and r.get("orig"):
        folium.PolyLine([(y, x) for x, y in r["orig"]], color="#1D5FB8", weight=6, tooltip="Ruta habitual").add_to(m)
    if r and r.get("alt"):
        folium.PolyLine([(y, x) for x, y in r["alt"]], color="#C2570C", weight=5, dash_array="10 8",
                        tooltip="Alterna").add_to(m)
    if r and r.get("poligono"):
        folium.GeoJson(r["poligono"], style_function=lambda _: {"color": "#B42318", "fillOpacity": 0.35}).add_to(m)
    if r and r.get("divergencia"):
        lon, lat = r["divergencia"][:2]
        folium.CircleMarker((lat, lon), radius=9, color="#15202B", fill=True, fill_color="#FFFFFF",
                            fill_opacity=1, tooltip="Punto de decisión").add_to(m)
    iconos = {"origen": ("Camión", "blue", "truck"), "destino": ("Destino", "black", "flag"),
              "bloqueo": ("Bloqueo", "red", "ban")}
    for k, p in ss.puntos.items():
        if p:
            nombre, color, icono = iconos[k]
            folium.Marker((p[1], p[0]), tooltip=nombre, icon=folium.Icon(color=color, icon=icono, prefix="fa")).add_to(m)
    if r and r.get("orig"):
        xs = [c[0] for c in r["orig"] + (r.get("alt") or [])]
        ys = [c[1] for c in r["orig"] + (r.get("alt") or [])]
        m.fit_bounds([(min(ys), min(xs)), (max(ys), max(xs))])

    salida = st_folium(m, height=580, use_container_width=True, key="mapa", returned_objects=["last_clicked"])
    click = salida.get("last_clicked") if salida else None
    if click:
        punto = redondear((click["lng"], click["lat"]))
        if punto != ss.ultimo_click:
            ss.ultimo_click = punto
            ss.puntos[clave_modo] = punto
            ss.resultado = None
            st.rerun()

# ---------- Cálculo ----------
with col_res:
    faltan = [n for n, k in (("camión", "origen"), ("destino", "destino"), ("bloqueo", "bloqueo")) if not ss.puntos[k]]
    if faltan:
        st.info("Marca en el mapa: " + ", ".join(faltan) + ".")
    if st.button("Calcular", type="primary", disabled=bool(faltan), use_container_width=True):
        origen, destino, bloqueo = ss.puntos["origen"], ss.puntos["destino"], ss.puntos["bloqueo"]
        with st.spinner("Calculando rutas…"):
            try:
                orig = calcular_ruta((origen, destino), perfil_clave, None)
            except ErrorRuteo as e:
                st.error(f"No se pudo calcular la ruta habitual. {e}")
                st.stop()
            try:
                snap = ajustar(*bloqueo)
            except ErrorRuteo:
                snap = None
            b_lon, b_lat = (snap[0], snap[1]) if snap else bloqueo
            poligono = G.poligono_bloqueo(b_lon, b_lat, radio)
            res = {"orig": orig.coords, "poligono": G.a_geojson(poligono), "via": snap[2] if snap else "",
                   "t_orig": orig.duracion_min, "d_orig": orig.distancia_km}

            if not G.ruta_cruza(orig.coords, poligono):
                res["fuera_de_ruta"] = True
            else:
                t_hasta = orig.duracion_min * G.fraccion_hasta(orig.coords, b_lon, b_lat)
                try:
                    alt = calcular_ruta((origen, destino), perfil_clave, json.dumps(res["poligono"]))
                    if G.ruta_cruza(alt.coords, poligono):
                        alt = None
                except ErrorRuteo:
                    alt = None
                rec = recomendar(orig.duracion_min, alt.duracion_min if alt else None, t_hasta,
                                 reapertura_min, carga, hora.hour)
                res.update(rec=rec, t_hasta=t_hasta)
                if alt:
                    div = G.punto_divergencia(orig.coords, alt.coords)
                    res.update(alt=alt.coords, t_alt=alt.duracion_min, d_alt=alt.distancia_km,
                               divergencia=div,
                               km_decision=div[2] * orig.distancia_km if div else None,
                               enlace=G.enlace_google_maps(origen, destino,
                                                           G.puntos_exclusivos(alt.coords, orig.coords)))
            ss.resultado = res
        st.rerun()

    r = ss.resultado
    if r:
        if r.get("fuera_de_ruta"):
            st.success("El bloqueo no está sobre la ruta del camión: puede continuar normalmente.")
            st.caption(f"Ruta habitual: {fmt_min(r['t_orig'])} · {r['d_orig']:.1f} km")
        else:
            rec = r["rec"]
            color = COLORES[rec.accion]
            st.markdown(f"<div style='background:{color};color:#fff;padding:14px 16px;border-radius:10px;"
                        f"font-size:1.4rem;font-weight:700'>{rec.titulo}</div>", unsafe_allow_html=True)
            for t in rec.razones:
                st.write(t)
            c1, c2 = st.columns(2)
            c1.metric("Ruta habitual", fmt_min(r["t_orig"]), f"+ espera {fmt_min(rec.espera_real_min)}",
                      delta_color="off")
            c2.metric("Alterna", fmt_min(r.get("t_alt")),
                      f"{r['d_alt'] - r['d_orig']:+.1f} km" if r.get("t_alt") else None, delta_color="off")
            c3, c4 = st.columns(2)
            c3.metric("Espera máxima", fmt_min(rec.espera_max_min))
            c4.metric("Llega al bloqueo en", fmt_min(r["t_hasta"]))
            if r.get("km_decision") is not None:
                st.write(f"**Punto de decisión:** a {r['km_decision']:.1f} km de la posición del camión.")
            if r.get("via"):
                st.caption(f"Vía del bloqueo según el mapa: {r['via']}")
            for a in rec.avisos:
                st.warning(a)
            if r.get("enlace"):
                st.link_button("Abrir alterna en Google Maps", r["enlace"], use_container_width=True)
                st.caption("Google recalcula entre puntos intermedios; verifica que siga la alterna.")
