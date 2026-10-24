from core import ventanas as V

# Ruta recta norte–sur de ~550 km (como Trujillo → Lima), un punto cada ~1 km
RUTA = [[-78.0, -8.0 - k * 0.009] for k in range(612)]
ACC = V.acumuladas_km(RUTA)


def test_distancia_haversine():
    assert abs(V.distancia_km((-78.0, -8.0), (-78.0, -9.0)) - 111.2) < 0.5


def test_ruta_larga_supera_el_limite():
    assert V.distancia_recta_total([RUTA[0], RUTA[-1]]) > 150


def test_ventana_maxima_respeta_el_limite_y_rodea_el_bloqueo():
    km_bloqueo = 300
    i, j = V.ventana(RUTA, ACC, km_bloqueo, km_bloqueo, 0, ACC[-1])
    assert V.distancia_km(RUTA[i], RUTA[j]) <= V.LIMITE_KM
    assert ACC[i] < km_bloqueo - 50 and ACC[j] > km_bloqueo + 50     # se amplió a ambos lados
    assert V.distancia_km(RUTA[i], RUTA[j]) > V.LIMITE_KM - 5         # y casi hasta el límite


def test_ventana_cerca_del_origen_se_amplia_hacia_adelante():
    i, j = V.ventana(RUTA, ACC, 10, 10, 0, ACC[-1])
    assert i == 0 and ACC[j] > 120


def test_bloqueos_lejanos_van_en_ventanas_separadas():
    grupos = V.agrupar([100, 110, 400], RUTA, ACC)
    assert grupos == [(100, 110), (400, 400)]
    (a_min, a_max), (b_min, b_max) = V.limites_de_grupos(grupos, ACC[-1])
    assert a_min == 0 and a_max == b_min == 255 and b_max == ACC[-1]


def test_empalme_y_tiempos():
    orig = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]]
    alt = [[1, 0], [1.5, 1], [3, 0]]
    assert V.empalmar(orig, [(1, 3, alt)]) == [[0, 0], [1, 0], [1.5, 1], [3, 0], [4, 0]]
    acc = V.acumuladas_km(orig)
    # Se reemplaza la mitad de la ruta (100 min, 200 km de 400) por una alterna de 150 min y 260 km
    t, d = V.tiempos_empalmados(200, 400, acc, [(1, 3, 150, 260)])
    assert abs(t - 250) < 0.5 and abs(d - 460) < 0.5
