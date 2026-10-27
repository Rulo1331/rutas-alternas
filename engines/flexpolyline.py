"""Decodificador del formato "Flexible Polyline" con que HERE entrega el trazado de las rutas.
Implementación propia y mínima (solo decodificar) para no agregar dependencias."""
_TABLA = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")}


def _sin_signo(texto: str):
    resultado = desplazamiento = 0
    for caracter in texto:
        valor = _TABLA[caracter]
        resultado |= (valor & 0x1F) << desplazamiento
        if valor & 0x20:
            desplazamiento += 5
        else:
            yield resultado
            resultado = desplazamiento = 0
    if desplazamiento:
        raise ValueError("Polilínea incompleta")


def _con_signo(valor: int) -> int:
    return ~(valor >> 1) if valor & 1 else valor >> 1


def decodificar(texto: str) -> list:
    """Devuelve [(lat, lon), ...] (o (lat, lon, z) si trae tercera dimensión)."""
    valores = _sin_signo(texto)
    if next(valores) != 1:
        raise ValueError("Versión de polilínea no soportada")
    cabecera = next(valores)
    precision, tercera, precision_z = cabecera & 15, (cabecera >> 4) & 7, (cabecera >> 7) & 15
    f, fz = 10.0 ** precision, 10.0 ** precision_z
    lat = lon = z = 0
    puntos = []
    while True:
        try:
            lat += _con_signo(next(valores))
        except StopIteration:
            return puntos
        lon += _con_signo(next(valores))
        if tercera:
            z += _con_signo(next(valores))
            puntos.append((lat / f, lon / f, z / fz))
        else:
            puntos.append((lat / f, lon / f))
