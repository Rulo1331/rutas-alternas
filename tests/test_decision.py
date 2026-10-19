from core.decision import recomendar, fmt_min
from core.parametros import CARGAS

VIVO, BENEF, ALIM = CARGAS["pollo_vivo"], CARGAS["pollo_beneficiado"], CARGAS["alimento"]


def test_desviar_pollo_vivo_por_limite_duro():
    r = recomendar(65, 140, 15, 180, VIVO, hora_local=8)
    assert r.accion == "DESVIAR" and r.espera_max_min == 30


def test_esperar_cuando_la_reapertura_es_pronto():
    r = recomendar(65, 140, 15, 40, ALIM, hora_local=8)   # espera 25 min, máx 65 min
    assert r.accion == "ESPERAR"


def test_continuar_si_llega_despues_de_la_reapertura():
    r = recomendar(130, 165, 120, 60, BENEF, hora_local=8)
    assert r.accion == "CONTINUAR" and r.espera_real_min == 0


def test_calor_reduce_la_espera_maxima():
    sin = recomendar(60, 100, 10, 50, BENEF, hora_local=8).espera_max_min
    con = recomendar(60, 100, 10, 50, BENEF, hora_local=12).espera_max_min
    assert con < sin


def test_sin_alterna():
    assert recomendar(60, None, 10, 120, ALIM, hora_local=8).accion == "SIN_ALTERNA"


def test_fmt_min():
    assert fmt_min(65) == "1 h 05 min" and fmt_min(35) == "35 min"
