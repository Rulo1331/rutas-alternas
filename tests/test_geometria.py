from core import geometria as G

ORIG = [[-79.03, -8.11], [-79.00, -8.20], [-78.97, -8.30], [-78.95, -8.40]]
ALT = [[-79.03, -8.11], [-79.00, -8.20], [-78.90, -8.25], [-78.92, -8.35], [-78.95, -8.40]]


def test_bloqueo_sobre_la_ruta():
    poly = G.poligono_bloqueo(-78.97, -8.30, 150)
    assert G.ruta_cruza(ORIG, poly) and not G.ruta_cruza(ALT, poly)


def test_fraccion_hasta():
    f = G.fraccion_hasta(ORIG, -78.97, -8.30)
    assert 0.5 < f < 0.8


def test_punto_divergencia():
    lon, lat, frac = G.punto_divergencia(ORIG, ALT)
    assert (lon, lat) == (-79.00, -8.20) and 0 < frac < 0.5


def test_enlace_google_maps():
    url = G.enlace_google_maps((-79.03, -8.11), (-78.95, -8.40), G.puntos_exclusivos(ALT, ORIG))
    assert url.startswith("https://www.google.com/maps/dir/?api=1") and "waypoints=" in url
