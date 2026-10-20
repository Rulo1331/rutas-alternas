from datetime import datetime, timedelta

from core import rios as R

AHORA = datetime(2026, 10, 20, 12, 0)


def test_normalizacion_de_nombres():
    assert R.normalizar_rio("Río Virú") == R.normalizar_rio("RIO VIRU") == R.normalizar_rio("Viru") == "viru"
    assert R.clave_rio("Río La Leche", "LAMBAYEQUE") == "la leche|lambayeque"


def test_nivel_de_alerta():
    assert R.nivel_alerta(3.1, 2.0, 2.5, 3.0) == "rojo"
    assert R.nivel_alerta(2.6, 2.0, 2.5, 3.0) == "naranja"
    assert R.nivel_alerta(1.0, 2.0, 2.5, 3.0) == "normal"
    assert R.nivel_alerta(1.0, None, None, None) == "sin_umbral"


def test_estado_toma_la_estacion_mas_grave_y_descarta_datos_viejos():
    filas = [
        {"rio": "Chicama", "departamento": "La Libertad", "estacion": "A", "variable": "NIVEL", "unidad": "m",
         "fecha_hora": AHORA - timedelta(hours=1), "valor": 1.0, "umbral_amarillo": 2, "umbral_naranja": 3, "umbral_rojo": 4},
        {"rio": "Río Chicama", "departamento": "LA LIBERTAD", "estacion": "B", "variable": "NIVEL", "unidad": "m",
         "fecha_hora": AHORA - timedelta(hours=2), "valor": 3.2, "umbral_amarillo": 2, "umbral_naranja": 3, "umbral_rojo": 4},
        {"rio": "Moche", "departamento": "La Libertad", "estacion": "C", "variable": "CAUDAL", "unidad": "m3/s",
         "fecha_hora": AHORA - timedelta(hours=48), "valor": 900, "umbral_amarillo": 10, "umbral_naranja": 20, "umbral_rojo": 30},
    ]
    e = R.estado_por_rio(filas, AHORA)
    assert e["chicama|la libertad"]["nivel"] == "naranja" and len(e["chicama|la libertad"]["detalle"]) == 2
    assert e["moche|la libertad"]["nivel"] == "sin_dato"


def test_cruces_con_la_ruta_y_agrupacion_por_puente():
    ruta = [[-79.0, -8.0], [-79.0, -8.5]]
    rio = {"type": "Feature", "properties": {"rio": "Virú", "departamento": "La Libertad"},
           "geometry": {"type": "MultiLineString", "coordinates": [
               [[-79.1, -8.3], [-78.9, -8.3]],            # cauce principal
               [[-79.1, -8.3005], [-78.9, -8.3005]]]}}    # brazo a ~55 m: mismo puente
    lejos = {"type": "Feature", "properties": {"rio": "Santa", "departamento": "Áncash"},
             "geometry": {"type": "LineString", "coordinates": [[-78.5, -9.0], [-78.4, -9.1]]}}
    c = R.cruces(ruta, [rio, lejos])
    assert len(c) == 1 and c[0]["rio"] == "Virú" and c[0]["clave"] == "viru|la libertad"
    assert abs(c[0]["lat"] + 8.3) < 0.001 and 0.5 < c[0]["fraccion"] < 0.7
