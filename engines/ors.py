"""Adaptador de OpenRouteService. Al migrar a ORS propio solo cambia base_url."""
import requests

from core.modelos import PerfilVehiculo, Ruta


class ErrorRuteo(Exception):
    pass


class MotorORS:
    def __init__(self, api_key: str, base_url: str = "https://api.openrouteservice.org", timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Authorization": api_key, "Content-Type": "application/json",
                        "Accept": "application/json, application/geo+json"}

    def _post(self, ruta: str, cuerpo: dict) -> dict:
        r = requests.post(f"{self.base}{ruta}", json=cuerpo, headers=self.headers, timeout=self.timeout)
        if r.status_code != 200:
            try:
                err = r.json().get("error", {})
                msg = err.get("message", err) if isinstance(err, dict) else err
            except ValueError:
                msg = r.text[:200]
            raise ErrorRuteo(f"ORS {r.status_code}: {msg}")
        return r.json()

    def ruta(self, coords: list, perfil: PerfilVehiculo | None = None, evitar: dict | None = None,
             perfil_ors: str = "driving-hgv") -> Ruta:
        """perfil_ors: "driving-hgv" (camión) o "driving-car" (auto). Las restricciones de
        dimensiones solo se envían con camión y si se pasa un perfil de vehículo."""
        cuerpo = {"coordinates": coords, "instructions": False,
                  "extra_info": ["surface", "waytype", "steepness", "waycategory"]}
        opciones = {}
        if perfil and perfil_ors == "driving-hgv":
            opciones["vehicle_type"] = "hgv"
            opciones["profile_params"] = {"restrictions": {
                "height": perfil.alto_m, "width": perfil.ancho_m,
                "length": perfil.largo_m, "weight": perfil.peso_t}}
        if evitar:
            opciones["avoid_polygons"] = evitar
        if opciones:
            cuerpo["options"] = opciones
        datos = self._post(f"/v2/directions/{perfil_ors}/geojson", cuerpo)
        f = datos["features"][0]
        resumen = f["properties"].get("summary", {})
        extras = {k: v.get("values", []) for k, v in f["properties"].get("extras", {}).items()}
        return Ruta(duracion_min=resumen.get("duration", 0) / 60,
                    distancia_km=resumen.get("distance", 0) / 1000,
                    coords=f["geometry"]["coordinates"], extras=extras)

    def ajustar_a_via(self, lon: float, lat: float, radio_m: int = 350):
        """Pega el punto a la vía más cercana. Devuelve (lon, lat, nombre, distancia_m) o None."""
        datos = self._post("/v2/snap/driving-hgv", {"locations": [[lon, lat]], "radius": radio_m})
        loc = (datos.get("locations") or [None])[0]
        if not loc:
            return None
        return loc["location"][0], loc["location"][1], loc.get("name", ""), loc.get("snapped_distance", 0)
