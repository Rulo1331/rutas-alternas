"""Ficha técnica de una alterna: superficie, trochas, pendientes, vados, túneles y curvas.

Se analiza solo el DESVÍO (lo que no comparte con la ruta habitual). Los datos vienen de OpenStreetMap
vía ORS y del trazado; son una estimación para decidir qué inspeccionar, NO una validación.
Lógica pura, sin APIs."""
import bisect
import math

from shapely.geometry import LineString, Point

from .geometria import ProyeccionLocal
from .modelos import PerfilVehiculo
from .parametros import ANCHO_CALZADA_M, RADIO_CURVA_REVISAR_M

# Códigos de ORS (extra_info)
SUPERFICIE_PAVIMENTADA = {1, 3, 4, 5, 6, 14}          # pavimento, asfalto, concreto, adoquín, metal, losas
SUPERFICIE_SIN_PAVIMENTAR = {2, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18}  # afirmado, ripio, tierra, arena, etc.
WAYTYPE_TROCHA = 5                                     # "track" en OpenStreetMap
CATEGORIA_TUNEL, CATEGORIA_VADO = 32, 128              # bits de waycategory


def _por_segmento(n: int, rangos, defecto=0) -> list:
    vals = [defecto] * n
    for s, e, v in rangos or []:
        for k in range(max(0, s), min(e, n)):
            vals[k] = v
    return vals


def clase_superficie(surface: int, waytype: int) -> str:
    if surface in SUPERFICIE_SIN_PAVIMENTAR or waytype == WAYTYPE_TROCHA:
        return "sin_pavimentar"
    if surface in SUPERFICIE_PAVIMENTADA:
        return "pavimentada"
    return "desconocida"


def radio_circunscrito(a, b, c) -> float:
    ab, bc, ca = a.distance(b), b.distance(c), c.distance(a)
    area2 = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y))
    return math.inf if area2 < 1e-9 else ab * bc * ca / (2 * area2)


def radios(pts: list, brazo_m: float = 20) -> list:
    """Radio de curvatura aproximado en cada vértice, usando puntos a ~brazo_m antes y después."""
    acc = [0.0]
    for k in range(1, len(pts)):
        acc.append(acc[-1] + pts[k - 1].distance(pts[k]))
    salida = []
    for i in range(len(pts)):
        atras = bisect.bisect_right(acc, acc[i] - brazo_m) - 1
        adelante = bisect.bisect_left(acc, acc[i] + brazo_m)
        if atras < 0 or adelante >= len(pts):
            salida.append(math.inf)
        else:
            salida.append(radio_circunscrito(pts[atras], pts[i], pts[adelante]))
    return salida


def barrido_m(radio: float, perfil: PerfilVehiculo) -> float:
    """Ancho que ocupa el vehículo en una curva: su ancho + desplazamiento de las ruedas traseras hacia
    el interior (fórmula aproximada de estado estable). Infinito si el radio es menor que el mínimo."""
    suma = sum(l * l for l in perfil.ejes_m)
    if radio * radio <= suma:
        return math.inf
    return perfil.ancho_m + (radio - math.sqrt(radio * radio - suma))


def analizar(piezas: list, habitual: list, perfil: PerfilVehiculo, tol_m: float = 60) -> dict:
    """piezas: [(coords, extras)] de la alterna (una por ventana). habitual: coords de la ruta habitual."""
    f = {"km_desvio": 0.0, "km_pavimentada": 0.0, "km_sin_pavimentar": 0.0, "km_desconocida": 0.0,
         "km_trocha": 0.0, "km_pendiente_7": 0.0, "km_pendiente_12": 0.0, "vados": 0, "tuneles": 0,
         "curvas": [], "tramos_sin_pavimentar": []}
    for coords, extras in piezas:
        if len(coords) < 2:
            continue
        proj = ProyeccionLocal(coords[0][0], coords[0][1])
        hab = proj.a_metros(LineString([c[:2] for c in habitual]))
        pts = [proj.a_metros(Point(c[0], c[1])) for c in coords]
        n = len(pts) - 1
        sup = _por_segmento(n, extras.get("surface"))
        tipo = _por_segmento(n, extras.get("waytype"))
        pend = _por_segmento(n, extras.get("steepness"))
        cat = _por_segmento(n, extras.get("waycategory"))
        exclusivo = [Point((pts[k].x + pts[k + 1].x) / 2, (pts[k].y + pts[k + 1].y) / 2).distance(hab) > tol_m
                     for k in range(n)]
        en_vado = en_tunel = False
        tramo_sp = None   # tramo sin pavimentar en curso: [km, índice inicio, índice fin]
        for k in range(n):
            if not exclusivo[k]:
                en_vado = en_tunel = False
                tramo_sp = None
                continue
            largo = pts[k].distance(pts[k + 1]) / 1000
            clase = clase_superficie(sup[k], tipo[k])
            f["km_desvio"] += largo
            f[f"km_{clase}"] += largo
            if tipo[k] == WAYTYPE_TROCHA:
                f["km_trocha"] += largo
            if abs(pend[k]) >= 3:
                f["km_pendiente_7"] += largo
            if abs(pend[k]) >= 4:
                f["km_pendiente_12"] += largo
            vado, tunel = bool(cat[k] & CATEGORIA_VADO), bool(cat[k] & CATEGORIA_TUNEL)
            f["vados"] += int(vado and not en_vado)
            f["tuneles"] += int(tunel and not en_tunel)
            en_vado, en_tunel = vado, tunel
            if clase == "sin_pavimentar":
                if tramo_sp is None:
                    tramo_sp = [0.0, k, k + 1, coords]       # [km, inicio, fin, coordenadas de la pieza]
                    f["tramos_sin_pavimentar"].append(tramo_sp)
                tramo_sp[0] += largo
                tramo_sp[2] = k + 1
            else:
                tramo_sp = None

        # Curvas: agrupar vértices consecutivos del desvío con radio bajo
        rs = radios(pts)
        curva = None
        for i in range(1, n):
            dentro = exclusivo[i - 1] and rs[i] < RADIO_CURVA_REVISAR_M
            if dentro:
                if curva is None or rs[i] < curva["radio_m"]:
                    clase = clase_superficie(sup[i], tipo[i])
                    curva = {"radio_m": rs[i], "lon": coords[i][0], "lat": coords[i][1], "superficie": clase}
            elif curva is not None:
                f["curvas"].append(curva)
                curva = None
        if curva is not None:
            f["curvas"].append(curva)

    # Clasificar curvas según el vehículo y el ancho supuesto de la vía
    for c in f["curvas"]:
        calzada = ANCHO_CALZADA_M[c["superficie"]]
        carril = calzada / 2 if c["superficie"] == "pavimentada" else calzada
        b = barrido_m(c["radio_m"], perfil)
        c["barrido_m"] = b
        c["nivel"] = "critica" if b > calzada else ("invade" if b > carril else "ok")
    f["curvas_criticas"] = sum(c["nivel"] == "critica" for c in f["curvas"])
    f["curvas_invade"] = sum(c["nivel"] == "invade" for c in f["curvas"])
    return f


def cortes_sin_pavimentar(ficha: dict, km_min: float = 0.5) -> list:
    """Puntos (lon, lat) en medio de cada tramo sin pavimentar del desvío. Excluir una zona pequeña ahí
    obliga al motor a buscar otra alterna, ojalá pavimentada."""
    puntos = []
    for km, i, j, coords in ficha["tramos_sin_pavimentar"]:
        if km >= km_min:
            c = coords[(i + j) // 2]
            puntos.append((c[0], c[1]))
    return puntos


def pros_contras(f: dict, t_min: float, t_mas_rapida: float, km_extra: float) -> tuple:
    pros, contras = [], []
    if t_min <= t_mas_rapida + 0.5:
        pros.append("Es la alterna más rápida.")
    else:
        contras.append(f"Toma {round(t_min - t_mas_rapida)} min más que la alterna más rápida.")
    sin_pav = f["km_sin_pavimentar"]
    if sin_pav < 0.5 and f["km_desconocida"] < 1:
        pros.append("Todo el desvío está pavimentado según el mapa.")
    elif sin_pav >= 0.5:
        contras.append(f"{sin_pav:.1f} km sin pavimentar: con lluvia puede haber barro y falta de tracción; "
                       "tramos de un solo carril donde el cruce con otro vehículo solo es posible en ensanches.")
    if f["km_desconocida"] >= 1:
        contras.append(f"{f['km_desconocida']:.1f} km sin dato de superficie en el mapa: verificar.")
    if f["curvas_criticas"]:
        contras.append(f"{f['curvas_criticas']} curva(s) donde el vehículo podría no pasar sin maniobra "
                       "(su barrido supera el ancho supuesto de la vía).")
    if f["curvas_invade"]:
        contras.append(f"{f['curvas_invade']} curva(s) donde el vehículo invade el carril contrario: "
                       "riesgo si viene otro vehículo.")
    if not f["curvas_criticas"] and not f["curvas_invade"]:
        pros.append("Sin curvas problemáticas detectadas para este vehículo.")
    if f["km_pendiente_12"] >= 0.3:
        contras.append(f"{f['km_pendiente_12']:.1f} km con pendiente de 12% o más (frenos en bajada, tracción en subida).")
    elif f["km_pendiente_7"] >= 0.5:
        contras.append(f"{f['km_pendiente_7']:.1f} km con pendiente de 7% o más.")
    if f["vados"]:
        contras.append(f"{f['vados']} vado(s): cruce por el cauce, peligroso con caudal alto.")
    if f["tuneles"]:
        contras.append(f"{f['tuneles']} túnel(es): verificar gálibo.")
    if km_extra > 0.5:
        contras.append(f"{km_extra:.0f} km más que la ruta habitual.")
    contras.append("Sin validar en campo.")
    return pros, contras


def clave_orden(f: dict, t_min: float) -> tuple:
    """Criterio para sugerir una alterna: primero sin curvas críticas, luego menos km sin pavimentar
    (redondeado a 1 km), luego menos curvas que invaden carril, luego la más rápida."""
    return (f["curvas_criticas"], round(f["km_sin_pavimentar"]), f["curvas_invade"], t_min)


def a_gpx(nombre: str, coords: list) -> str:
    puntos = "\n".join(f'      <trkpt lat="{c[1]:.6f}" lon="{c[0]:.6f}"/>' for c in coords)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="rutas-alternas" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f'  <trk>\n    <name>{nombre}</name>\n    <trkseg>\n{puntos}\n    </trkseg>\n  </trk>\n</gpx>\n')
