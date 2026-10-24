"""Ríos monitoreados: estado de alerta y cruces con la ruta. Lógica pura, sin APIs."""
import unicodedata

from shapely.geometry import LineString, shape

from .geometria import ProyeccionLocal

ORDEN = {"rojo": 5, "naranja": 4, "amarillo": 3, "normal": 2, "sin_umbral": 1, "sin_dato": 0}
ETIQUETAS = {"rojo": "Alerta roja", "naranja": "Alerta naranja", "amarillo": "Alerta amarilla",
             "normal": "Normal", "sin_umbral": "Sin umbral definido", "sin_dato": "Sin dato reciente"}
COLORES = {"rojo": "#C62828", "naranja": "#E06C00", "amarillo": "#D4A300", "normal": "#2E7D32",
           "sin_umbral": "#4F7396", "sin_dato": "#7D8A96"}


def plano(texto) -> str:
    """Minúsculas, sin tildes y con espacios simples."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def normalizar_rio(nombre) -> str:
    t = plano(nombre)
    return t[4:].strip() if t.startswith("rio ") else t


def clave_rio(rio, departamento) -> str:
    return f"{normalizar_rio(rio)}|{plano(departamento)}"


def nivel_alerta(valor, amarillo, naranja, rojo) -> str:
    if valor is None:
        return "sin_dato"
    if amarillo is None and naranja is None and rojo is None:
        return "sin_umbral"
    for nivel, umbral in (("rojo", rojo), ("naranja", naranja), ("amarillo", amarillo)):
        if umbral is not None and valor >= umbral:
            return nivel
    return "normal"


def porcentaje_umbral(valor, amarillo, naranja, rojo) -> str:
    """Texto con el % del valor respecto al siguiente umbral que aún no alcanza
    (o al umbral rojo si ya lo superó). Vacío si no hay umbrales."""
    if valor is None:
        return ""
    umbrales = [(n, u) for n, u in (("amarillo", amarillo), ("naranja", naranja), ("rojo", rojo)) if u]
    if not umbrales:
        return ""
    for nombre, u in umbrales:
        if valor < u:
            return f"{valor / u:.0%} del umbral {nombre}"
    nombre, u = umbrales[-1]
    return f"{valor / u:.0%} del umbral {nombre}"



def estado_por_rio(filas: list, ahora, max_horas: float = 24) -> dict:
    """Agrupa el último dato de cada estación/variable por río y toma el nivel MÁS GRAVE.
    filas: dicts con rio, departamento, estacion, variable, unidad, fecha_hora, valor y umbrales.
    ahora: datetime en la misma referencia horaria que fecha_hora (hora local de Perú)."""
    estados = {}
    for f in filas:
        clave = clave_rio(f.get("rio"), f.get("departamento"))
        fh, valor = f.get("fecha_hora"), f.get("valor")
        horas = (ahora - fh).total_seconds() / 3600 if fh else None
        if horas is None or horas > max_horas:
            nivel = "sin_dato"
        else:
            nivel = nivel_alerta(valor, f.get("umbral_amarillo"), f.get("umbral_naranja"), f.get("umbral_rojo"))
        nombre = f.get("estacion") or f.get("cod_estacion") or "Estación"
        dato = f"{round(valor, 2):g} {f.get('unidad') or ''}".strip() if valor is not None else "sin valor"
        pct = porcentaje_umbral(valor, f.get("umbral_amarillo"), f.get("umbral_naranja"), f.get("umbral_rojo"))
        if pct:
            dato += f" ({pct})"
        cuando = f"{fh:%d/%m %H:%M}" if fh else "sin fecha"
        e = estados.setdefault(clave, {"nivel": "sin_dato", "detalle": []})
        if ORDEN[nivel] > ORDEN[e["nivel"]]:
            e["nivel"] = nivel
        e["detalle"].append(f"{nombre} · {f.get('variable', '')} {dato} · {cuando} → {ETIQUETAS[nivel]}")
    return estados


def _puntos(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Point":
        return [geom]
    if geom.geom_type in ("LineString", "LinearRing"):
        return [geom.interpolate(0.5, normalized=True)]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _puntos(g)]
    return [geom.representative_point()]


def cruces(ruta_coords: list, rios: list, agrupar_m: float = 300) -> list:
    """Puntos donde la ruta cruza cada río (normalmente, puentes), ordenados por avance.
    rios: features GeoJSON; si traen '_geom' (shapely) se usa para no reconstruirla."""
    if not ruta_coords or len(ruta_coords) < 2 or not rios:
        return []
    ruta = LineString(ruta_coords)
    rx0, ry0, rx1, ry1 = ruta.bounds
    proj = ProyeccionLocal(*ruta_coords[0])
    salida = []
    for f in rios:
        geom = f.get("_geom") or shape(f["geometry"])
        x0, y0, x1, y1 = geom.bounds
        if x1 < rx0 or x0 > rx1 or y1 < ry0 or y0 > ry1:
            continue
        elegidos = []   # un mismo puente puede cortar varios brazos del río
        for p in _puntos(ruta.intersection(geom)):
            pm = proj.a_metros(p)
            if all(pm.distance(q) > agrupar_m for _, q in elegidos):
                elegidos.append((p, pm))
        props = f.get("properties", {})
        for p, _ in elegidos:
            salida.append({"rio": props.get("rio"), "departamento": props.get("departamento"),
                           "clave": props.get("clave") or clave_rio(props.get("rio"), props.get("departamento")),
                           "lon": p.x, "lat": p.y, "fraccion": ruta.project(p, normalized=True)})
    return sorted(salida, key=lambda c: c["fraccion"])
