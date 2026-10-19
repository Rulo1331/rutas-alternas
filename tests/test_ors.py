"""Verifica el cuerpo que se envía a ORS sin llamar a la API real."""
from core.parametros import PERFILES
from engines import ors


class _Resp:
    status_code = 200
    def json(self):
        return {"features": [{"properties": {"summary": {"duration": 3600, "distance": 50000}},
                              "geometry": {"coordinates": [[-79.0, -8.1], [-78.9, -8.2]]}}]}


def test_cuerpo_de_la_peticion(monkeypatch):
    capturado = {}
    def falso_post(url, json, headers, timeout):
        capturado.update(url=url, json=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(ors.requests, "post", falso_post)
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    r = ors.MotorORS("CLAVE").ruta([[-79.0, -8.1], [-78.9, -8.2]], PERFILES["jaulero_c3"], poly)
    op = capturado["json"]["options"]
    assert capturado["url"].endswith("/v2/directions/driving-hgv/geojson")
    assert capturado["headers"]["Authorization"] == "CLAVE"
    assert op["vehicle_type"] == "hgv" and op["profile_params"]["restrictions"]["weight"] == 25.0
    assert op["avoid_polygons"] == poly
    assert r.duracion_min == 60 and r.distancia_km == 50
