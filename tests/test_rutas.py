from data.rutas import a_ruta


def test_fila_a_ruta():
    fila = {"id": "TRU-PIU", "nombre": "Trujillo → Piura", "origen_nombre": "Trujillo", "origen_lat": -8.11,
            "origen_lon": -79.03, "destino_nombre": "Piura", "destino_lat": -5.19, "destino_lon": -80.63,
            "puntos_paso": "[[-79.5, -7.0]]", "tipo_carga": "pollo_beneficiado", "perfil": "frigorifico_c2"}
    r = a_ruta(fila)
    assert r["origen"] == (-79.03, -8.11) and r["destino"] == (-80.63, -5.19)
    assert r["puntos_paso"] == [(-79.5, -7.0)]


def test_puntos_de_paso_invalidos_no_rompen():
    fila = {"id": "X", "nombre": "X", "origen_lat": 0, "origen_lon": 0, "destino_lat": 1, "destino_lon": 1,
            "puntos_paso": "no es json"}
    assert a_ruta(fila)["puntos_paso"] == []
