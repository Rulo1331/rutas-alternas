from core import geometria as G
from core.parametros import PERFILES
from engines import here
from engines.flexpolyline import decodificar


def test_decodificar_ejemplo_oficial():
    assert decodificar("BFoz5xJ67i1B1B7PzIhaxL7Y") == [(50.10228, 8.69821), (50.10201, 8.69567),
                                                      (50.10063, 8.6915), (50.09878, 8.68752)]


def test_decodificar_trujillo_chao():
    assert decodificar("BF3qwxBnpriPjxzCkqkC") == [(-8.1118, -79.02868), (-8.5395, -78.6789)]


def test_parametros_camion_y_zonas():
    p = dict(here.parametros([(-79.0, -8.1), (-78.9, -8.3), (-78.7, -8.5)], PERFILES["granelero_t3s3"],
                             [(-78.95, -8.21, -78.94, -8.20)], True, "K"))
    assert p["origin"] == "-8.1,-79.0" and p["via"] == "-8.3,-78.9" and p["destination"] == "-8.5,-78.7"
    assert p["vehicle[grossWeight]"] == "48000" and p["vehicle[height]"] == "410"
    assert p["vehicle[type]"] == "tractor" and p["vehicle[axleCount]"] == "6"
    assert p["avoid[areas]"].startswith("bbox:-78.950000,-8.210000") and p["avoid[features]"] == "dirtRoad"


class _Resp:
    status_code = 200
    def json(self):
        return {"routes": [{"sections": [
            {"polyline": "BF3qwxBnpriPjxzCkqkC", "summary": {"duration": 3600, "length": 60000}}]}]}


def test_ruta_desde_respuesta(monkeypatch):
    monkeypatch.setattr(here.requests, "get", lambda url, params, timeout: _Resp())
    r = here.MotorHERE("K").ruta([(-79.02868, -8.1118), (-78.6789, -8.5395)], PERFILES["jaulero_c3"])
    assert r.duracion_min == 60 and r.distancia_km == 60 and r.coords[0] == [-79.02868, -8.1118]


def test_coincidencia_de_trazados():
    a = [[-78.0, -8.0], [-78.0, -8.1]]
    assert G.coincidencia(a, a) == 1.0
    assert G.coincidencia(a, [[-77.9, -8.0], [-77.9, -8.1]]) == 0.0
