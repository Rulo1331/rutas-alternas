import math

from core import ficha as F
from core.parametros import PERFILES
from shapely.geometry import Point

T3S3, C2 = PERFILES["granelero_t3s3"], PERFILES["frigorifico_c2"]
HABITUAL = [[-78.0, -8.0], [-78.0, -8.2]]           # recta norte–sur


def arco(lon0, lat0, radio_m, grados=180, n=40):
    """Arco de circunferencia en coordenadas (para simular una curva)."""
    kx = 111320 * math.cos(math.radians(lat0)); ky = 110540
    return [[lon0 + radio_m * math.cos(math.radians(a)) / kx, lat0 + radio_m * math.sin(math.radians(a)) / ky]
            for a in [grados * k / n for k in range(n + 1)]]


def test_radio_de_circunferencia():
    pts = [Point(0, 0), Point(10, 10), Point(20, 0)]
    assert abs(F.radio_circunscrito(*pts) - 10) < 1e-6


def test_barrido_semirremolque_mucho_mayor_que_camion_rigido():
    assert F.barrido_m(15, T3S3) > 7.5 and F.barrido_m(15, C2) < 4.0
    assert F.barrido_m(10, T3S3) == math.inf          # radio menor que el mínimo posible


def test_superficie_trocha_vado_y_pendiente_en_el_desvio():
    desvio = [[-77.95, -8.05], [-77.95, -8.10], [-77.95, -8.15]]   # ~5.5 km al este: todo es desvío
    extras = {"surface": [[0, 1, 3], [1, 2, 11]],      # asfalto, luego tierra
              "waytype": [[0, 1, 1], [1, 2, 5]],       # carretera, luego trocha
              "steepness": [[0, 1, 0], [1, 2, 4]],     # plano, luego 12–15 %
              "waycategory": [[0, 1, 0], [1, 2, 128]]} # vado en el segundo tramo
    f = F.analizar([(desvio, extras)], HABITUAL, T3S3)
    assert abs(f["km_pavimentada"] - 5.5) < 0.2 and abs(f["km_sin_pavimentar"] - 5.5) < 0.2
    assert f["km_trocha"] > 5 and f["km_pendiente_12"] > 5 and f["vados"] == 1
    assert F.cortes_sin_pavimentar(f) == [(-77.95, -8.15)] or len(F.cortes_sin_pavimentar(f)) == 1


def test_tramo_compartido_con_la_habitual_no_cuenta():
    f = F.analizar([(HABITUAL, {"surface": [[0, 1, 11]]})], HABITUAL, T3S3)
    assert f["km_desvio"] == 0 and f["km_sin_pavimentar"] == 0


def test_curva_cerrada_critica_para_semirremolque_pero_no_para_c2():
    curva = arco(-77.9, -8.1, 18)                      # radio 18 m, lejos de la habitual
    extras = {"surface": [[0, len(curva) - 1, 3]]}     # pavimentada
    f_t = F.analizar([(curva, extras)], HABITUAL, T3S3)
    f_c = F.analizar([(curva, extras)], HABITUAL, C2)
    assert f_t["curvas"] and 15 < f_t["curvas"][0]["radio_m"] < 21
    assert f_t["curvas_criticas"] == 1 and f_c["curvas_criticas"] == 0


def test_pros_contras_y_orden():
    base = {"km_desvio": 10, "km_pavimentada": 10, "km_sin_pavimentar": 0, "km_desconocida": 0, "km_trocha": 0,
            "km_pendiente_7": 0, "km_pendiente_12": 0, "vados": 0, "tuneles": 0, "curvas": [],
            "curvas_criticas": 0, "curvas_invade": 0, "tramos_sin_pavimentar": []}
    trocha = dict(base, km_pavimentada=2, km_sin_pavimentar=8)
    pros, contras = F.pros_contras(base, 90, 80, 12)
    assert any("pavimentado" in p for p in pros) and any("10 min más" in c for c in contras)
    assert F.clave_orden(base, 90) < F.clave_orden(trocha, 80)   # pista aunque sea más lenta


def test_gpx():
    g = F.a_gpx("Alterna A", [[-78.0, -8.0], [-78.1, -8.1]])
    assert '<trkpt lat="-8.000000" lon="-78.000000"/>' in g and "<name>Alterna A</name>" in g
