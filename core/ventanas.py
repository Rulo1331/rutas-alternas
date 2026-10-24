"""Alterna por ventana: calcula la alterna solo alrededor de los bloqueos y la une con la ruta habitual.

Motivo: la API pública de ORS rechaza rutas con zonas a evitar si la distancia aproximada (en línea
recta entre los puntos enviados) supera 150 km. Aquí se trabaja con un margen bajo ese límite.
Lógica pura, sin APIs."""
import bisect
import math

LIMITE_KM = 140        # margen de seguridad bajo los 150 km del plan gratuito
HOLGURA_KM = 2         # la ventana empieza al menos 2 km antes/después de cada bloqueo
PASO_KM = 2            # resolución con la que se amplía la ventana


def distancia_km(a, b) -> float:
    """Distancia en línea recta (haversine) entre dos puntos (lon, lat)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def distancia_recta_total(coords) -> float:
    """Lo que ORS considera la distancia aproximada de una consulta: suma de tramos en línea recta."""
    return sum(distancia_km(coords[k], coords[k + 1]) for k in range(len(coords) - 1))


def acumuladas_km(coords) -> list:
    acc = [0.0]
    for k in range(1, len(coords)):
        acc.append(acc[-1] + distancia_km(coords[k - 1], coords[k]))
    return acc


def _indice_antes(acc, km) -> int:
    return max(0, bisect.bisect_right(acc, km) - 1)


def _indice_despues(acc, km) -> int:
    return min(len(acc) - 1, bisect.bisect_left(acc, km))


def agrupar(posiciones_km: list, coords: list, acc: list, limite_km: float = LIMITE_KM) -> list:
    """Agrupa bloqueos cercanos para resolverlos en una sola ventana. Devuelve [(km_inicio, km_fin)]."""
    grupos = []
    for km in sorted(posiciones_km):
        if grupos:
            ini, _ = grupos[-1]
            a = coords[_indice_antes(acc, ini)]
            b = coords[_indice_despues(acc, km)]
            if distancia_km(a, b) + 2 * HOLGURA_KM <= limite_km * 0.8:
                grupos[-1] = (ini, km)
                continue
        grupos.append((km, km))
    return grupos


def ventana(coords: list, acc: list, km_ini: float, km_fin: float, km_min: float, km_max: float,
            limite_km: float = LIMITE_KM) -> tuple:
    """La ventana MÁS GRANDE alrededor de [km_ini, km_fin] cuyos extremos estén a <= limite_km en línea recta.
    Una ventana más grande nunca da una alterna peor (contiene todas las opciones de una más chica),
    así que se usa la máxima posible en una sola consulta. Devuelve (índice_inicio, índice_fin)."""
    a = max(km_min, km_ini - HOLGURA_KM)
    b = min(km_max, km_fin + HOLGURA_KM)
    punto = lambda km, antes: coords[_indice_antes(acc, km) if antes else _indice_despues(acc, km)]
    movido = True
    while movido:
        movido = False
        a2 = max(km_min, a - PASO_KM)
        if a2 < a and distancia_km(punto(a2, True), punto(b, False)) <= limite_km:
            a, movido = a2, True
        b2 = min(km_max, b + PASO_KM)
        if b2 > b and distancia_km(punto(a, True), punto(b2, False)) <= limite_km:
            b, movido = b2, True
    return _indice_antes(acc, a), _indice_despues(acc, b)


def limites_de_grupos(grupos: list, total_km: float) -> list:
    """Cada grupo puede ampliarse hasta la mitad del camino hacia el grupo vecino (sin superponerse)."""
    limites = []
    for k, (ini, fin) in enumerate(grupos):
        km_min = 0.0 if k == 0 else (grupos[k - 1][1] + ini) / 2
        km_max = total_km if k == len(grupos) - 1 else (fin + grupos[k + 1][0]) / 2
        limites.append((km_min, km_max))
    return limites


def empalmar(orig: list, tramos: list) -> list:
    """Une la ruta habitual con las alternas locales. tramos: [(i, j, coords_alterna)] en orden."""
    salida, desde = [], 0
    for i, j, alt in sorted(tramos, key=lambda t: t[0]):
        salida += orig[desde:i] + list(alt)
        desde = j + 1
    return salida + orig[desde:]


def tiempos_empalmados(t_orig: float, d_orig: float, acc: list, tramos: list) -> tuple:
    """Duración y distancia de la ruta empalmada. Los tramos habituales reemplazados se descuentan
    en proporción a su distancia (supone velocidad pareja en esos tramos)."""
    total = acc[-1] or 1.0
    t, d = t_orig, d_orig
    for i, j, dur_alt, dist_alt in tramos:
        fr = (acc[j] - acc[i]) / total
        t += dur_alt - t_orig * fr
        d += dist_alt - d_orig * fr
    return t, d
