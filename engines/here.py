"""Adaptador de HERE Routing API v8 (modo camión) para la prueba comparativa."""
import requests

from core.modelos import PerfilVehiculo, Ruta
from engines.flexpolyline import decodificar
from engines.ors import ErrorRuteo

URL = "https://router.hereapi.com/v8/routes"
# Configuración de ejes por perfil: (tipo de vehículo HERE, número de ejes, remolques)
CONFIG_EJES = {"granelero_t3s3": ("tractor", 6, 1), "jaulero_c3": ("straightTruck", 3, 0),
               "frigorifico_c2": ("straightTruck", 2, 0)}


def parametros(coords: list, perfil: PerfilVehiculo | None, cajas: list, evitar_tierra: bool, api_key: str) -> list:
    """Arma los parámetros de la consulta. coords: [(lon, lat), ...]; cajas: [(oeste, sur, este, norte)]."""
    p = [("transportMode", "truck"), ("origin", f"{coords[0][1]},{coords[0][0]}"),
         ("destination", f"{coords[-1][1]},{coords[-1][0]}"), ("return", "polyline,summary"),
         ("departureTime", "any"),          # sin tráfico en tiempo real, para comparar en igualdad con ORS
         ("apiKey", api_key)]
    p += [("via", f"{c[1]},{c[0]}") for c in coords[1:-1]]
    if perfil:
        tipo, ejes, remolques = CONFIG_EJES.get(perfil.clave, ("straightTruck", 2, 0))
        p += [("vehicle[grossWeight]", str(round(perfil.peso_t * 1000))),   # kg
              ("vehicle[height]", str(round(perfil.alto_m * 100))),         # cm
              ("vehicle[width]", str(round(perfil.ancho_m * 100))),
              ("vehicle[length]", str(round(perfil.largo_m * 100))),
              ("vehicle[type]", tipo), ("vehicle[axleCount]", str(ejes)),
              ("vehicle[trailerCount]", str(remolques))]
    if cajas:
        p.append(("avoid[areas]", "|".join(f"bbox:{o:.6f},{s:.6f},{e:.6f},{n:.6f}" for o, s, e, n in cajas)))
    if evitar_tierra:
        p.append(("avoid[features]", "dirtRoad"))
    return p


class MotorHERE:
    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key, self.timeout = api_key, timeout

    def ruta(self, coords: list, perfil: PerfilVehiculo | None = None, cajas: list | None = None,
             evitar_tierra: bool = False) -> Ruta:
        r = requests.get(URL, params=parametros(coords, perfil, cajas or [], evitar_tierra, self.api_key),
                         timeout=self.timeout)
        if r.status_code != 200:
            try:
                d = r.json()
                msg = d.get("title") or d.get("error_description") or d.get("error") or r.text[:200]
                if d.get("cause"):
                    msg += f" ({d['cause']})"
            except ValueError:
                msg = r.text[:200]
            raise ErrorRuteo(f"HERE {r.status_code}: {msg}")
        datos = r.json()
        rutas = datos.get("routes") or []
        if not rutas:
            avisos = "; ".join(n.get("title", "") for n in datos.get("notices", []))
            raise ErrorRuteo("HERE no encontró ruta" + (f": {avisos}" if avisos else "."))
        coords_ruta, duracion, largo = [], 0.0, 0.0
        for sec in rutas[0].get("sections", []):
            pts = [[p[1], p[0]] for p in decodificar(sec["polyline"])]
            coords_ruta += pts if not coords_ruta else pts[1:]
            resumen = sec.get("summary", {})
            duracion += resumen.get("duration", 0)
            largo += resumen.get("length", 0)
        avisos = [n.get("title", "") for s in rutas[0].get("sections", []) for n in s.get("notices", [])]
        return Ruta(duracion / 60, largo / 1000, coords_ruta, {"avisos_here": avisos})
