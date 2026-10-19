"""Operaciones geométricas en metros usando una proyección local (suficiente a escala regional)."""
import math
from urllib.parse import urlencode

import numpy as np
import shapely
from shapely.geometry import LineString, Point, mapping

_R = 6371008.8


class ProyeccionLocal:
    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = math.cos(math.radians(lat0)) * math.pi / 180 * _R
        self.ky = math.pi / 180 * _R
        self._origen = np.array([lon0, lat0])
        self._escala = np.array([self.kx, self.ky])

    def a_metros(self, geom):
        return shapely.transform(geom, lambda c: (c - self._origen) * self._escala)

    def a_grados(self, geom):
        return shapely.transform(geom, lambda c: c / self._escala + self._origen)


def poligono_bloqueo(lon: float, lat: float, radio_m: float):
    p = ProyeccionLocal(lon, lat)
    return p.a_grados(Point(0, 0).buffer(radio_m, 16))


def a_geojson(geom) -> dict:
    return mapping(geom)


def ruta_cruza(coords: list, poligono) -> bool:
    return LineString(coords).intersects(poligono)


def fraccion_hasta(coords: list, lon: float, lat: float) -> float:
    """Fracción (0–1) del recorrido hasta el punto más cercano a (lon, lat)."""
    p = ProyeccionLocal(lon, lat)
    return p.a_metros(LineString(coords)).project(p.a_metros(Point(lon, lat)), normalized=True)


def punto_divergencia(orig: list, alt: list, tol_m: float = 60):
    """Último punto de la ruta habitual antes de que la alterna se separe. Devuelve (lon, lat, fracción)."""
    p = ProyeccionLocal(*orig[0])
    linea_alt = p.a_metros(LineString(alt))
    linea_orig = p.a_metros(LineString(orig))
    previo = orig[0]
    for c in orig:
        if p.a_metros(Point(c)).distance(linea_alt) > tol_m:
            frac = linea_orig.project(p.a_metros(Point(previo)), normalized=True)
            return previo[0], previo[1], frac
        previo = c
    return None


def puntos_exclusivos(alt: list, orig: list, n: int = 3, tol_m: float = 200) -> list:
    """Hasta n puntos de la alterna alejados de la ruta habitual (para forzarla en Google Maps)."""
    p = ProyeccionLocal(*alt[0])
    linea_orig = p.a_metros(LineString(orig))
    lejos = [c for c in alt if p.a_metros(Point(c)).distance(linea_orig) > tol_m]
    if not lejos:
        return []
    if len(lejos) <= n:
        return lejos
    paso = len(lejos) / (n + 1)
    return [lejos[int(paso * (i + 1))] for i in range(n)]


def enlace_google_maps(origen: tuple, destino: tuple, waypoints: list) -> str:
    q = {"api": 1, "origin": f"{origen[1]},{origen[0]}", "destination": f"{destino[1]},{destino[0]}",
         "travelmode": "driving"}
    if waypoints:
        q["waypoints"] = "|".join(f"{w[1]},{w[0]}" for w in waypoints)
    return "https://www.google.com/maps/dir/?" + urlencode(q, safe="|,")
