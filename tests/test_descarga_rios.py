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


def test_rio_de_un_solo_tramo_no_falla():
    """Caso del error en GitHub Actions: tras unir, queda una sola línea."""
    elementos = [{"type": "way", "tags": {"name": "Río Chilete"},
                  "geometry": [{"lon": -78.84, "lat": -7.22}, {"lon": -78.90, "lat": -7.21}]}]
    f = D.construir_features(elementos, ["RÍO CHILETE"], "CAJAMARCA")
    assert len(f) == 1 and f[0]["geometry"]["type"] == "LineString"


def test_alias_y_mayusculas(tmp_path):
    csv = tmp_path / "alias.csv"
    csv.write_text("rio_tabla,nombre_osm\n# comentario\nRÍO CHANCAY LAMBAYEQUE,Río Chancay\n", encoding="utf-8")
    alias = D.cargar_alias(csv)
    buscados = D.nombres_buscados(["RÍO CHANCAY LAMBAYEQUE"], alias)
    assert buscados == {"chancay lambayeque": "RÍO CHANCAY LAMBAYEQUE", "chancay": "RÍO CHANCAY LAMBAYEQUE"}
    elementos = [{"type": "way", "tags": {"name": "Río Chancay"},
                  "geometry": [{"lon": -79.5, "lat": -6.7}, {"lon": -79.4, "lat": -6.75}]}]
    f = D.construir_features(elementos, ["RÍO CHANCAY LAMBAYEQUE"], "LAMBAYEQUE", alias)
    assert f[0]["properties"]["rio"] == "RÍO CHANCAY LAMBAYEQUE"


def test_consulta_incluye_canales():
    q = D.consulta_overpass("Cajamarca", ["trasvase del rio chotano"])
    assert '["waterway"~"^(river|canal)$"]' in q
