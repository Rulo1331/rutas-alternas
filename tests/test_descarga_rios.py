import re

from jobs import descargar_rios as D


def test_patron_tolera_tildes_y_prefijo():
    p = re.compile(D.patron_nombre("Virú"), re.I)
    assert p.match("Río Virú") and p.match("RIO VIRU") and p.match("Viru")
    assert not p.match("Quebrada Virú")


def test_consulta_usa_el_departamento():
    q = D.consulta_overpass("La Libertad", ["Chicama", "Moche"])
    assert '["name"="La Libertad"]' in q and q.count("relation[") == 2 and q.count("way[") == 2


def test_construir_features_desde_overpass():
    elementos = [
        {"type": "way", "tags": {"name": "Río Chicama"},
         "geometry": [{"lon": -79.3, "lat": -7.8}, {"lon": -79.2, "lat": -7.7}]},
        {"type": "relation", "tags": {"name": "Rio Chicama"}, "members": [
            {"type": "way", "geometry": [{"lon": -79.2, "lat": -7.7}, {"lon": -79.1, "lat": -7.6}]}]},
        {"type": "way", "tags": {"name": "Río Otro"},
         "geometry": [{"lon": -79.0, "lat": -7.0}, {"lon": -78.9, "lat": -7.1}]},
    ]
    f = D.construir_features(elementos, ["Chicama"], "LA LIBERTAD")
    assert len(f) == 1
    assert f[0]["properties"] == {"rio": "Chicama", "departamento": "LA LIBERTAD", "clave": "chicama|la libertad"}
    assert f[0]["geometry"]["type"] in ("LineString", "MultiLineString")
