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


# ---------- Varios bloqueos ----------
from core.decision import espera_secuencial, recomendar_varios


def test_espera_secuencial_considera_el_retraso_acumulado():
    # Bloqueo 1 a los 40 min (reabre a los 60) y bloqueo 2 a los 90 min de viaje (reabre a los 120).
    # Tras esperar 20 min en el 1, llega al 2 a los 110 → espera 10 más. Total 30, la mayor 20.
    assert espera_secuencial([(90, 120), (40, 60)]) == (30, 20)


def test_espera_secuencial_sin_espera():
    assert espera_secuencial([(40, 10), (90, 60)]) == (0, 0)


def test_limite_duro_se_aplica_por_bloqueo_no_al_total():
    # Pollo vivo, sin calor: dos esperas de 20 min (cada una bajo 30), total 40 bajo el umbral de costo (90 - 10 = 80).
    r = recomendar_varios(60, 150, [(10, 30), (60, 100)], VIVO, hora_local=8)
    assert r.accion == "ESPERAR" and r.espera_real_min == 40


def test_varios_bloqueos_desviar_si_uno_supera_el_maximo_detenido():
    r = recomendar_varios(60, 150, [(10, 15), (60, 140)], VIVO, hora_local=8)
    assert r.accion == "DESVIAR" and "máximo" in r.razones[0]
