"""Regla de decisión: esperar, desviar o continuar. Lógica pura, sin APIs."""
from .modelos import ParametrosCarga, Recomendacion
from .parametros import MARGEN_MIN, HORAS_CALOR


def fmt_min(m: float | None) -> str:
    if m is None:
        return "—"
    m = int(round(m))
    h, r = divmod(m, 60)
    return f"{h} h {r:02d} min" if h else f"{r} min"


def espera_secuencial(bloqueos: list) -> tuple:
    """Espera acumulada recorriendo los bloqueos en orden de avance.
    bloqueos: [(minutos de viaje hasta el bloqueo, minutos hasta su reapertura), ...] contados desde ahora,
    con el tiempo de viaje medido SIN esperas. Devuelve (espera total, espera más larga en un solo bloqueo).
    Cada espera retrasa la llegada a los bloqueos siguientes."""
    reloj, viaje_previo, total, mayor = 0.0, 0.0, 0.0, 0.0
    for t_viaje, reapertura in sorted(bloqueos):
        reloj += t_viaje - viaje_previo
        viaje_previo = t_viaje
        espera = max(0.0, reapertura - reloj)
        reloj += espera
        total += espera
        mayor = max(mayor, espera)
    return total, mayor


def _decidir(t_orig_min, t_alt_min, espera_total, espera_mayor, t_primer_min, carga: ParametrosCarga,
             hora_local, margen_min, horas_calor, n_bloqueos) -> Recomendacion:
    calor = horas_calor[0] <= hora_local < horas_calor[1]
    factor = carga.factor_calor if calor else 1.0
    varios = n_bloqueos > 1
    espera_txt = "La espera total estimada" if varios else "La espera estimada"

    if t_alt_min is None:
        return Recomendacion(
            "SIN_ALTERNA", "Sin ruta alterna: esperar",
            razones=["No se encontró una ruta que evite " + ("los bloqueos" if varios else "el bloqueo")
                     + " para este vehículo."],
            espera_real_min=espera_total)

    holgura = t_alt_min - t_orig_min
    umbral_costo = max(0.0, (holgura - margen_min) / factor)
    limite = carga.max_detenido_min
    espera_max = min(umbral_costo, limite) if limite is not None else umbral_costo

    avisos = []
    if calor and factor > 1:
        avisos.append(f"Horario de calor: cada minuto de espera cuenta ×{factor:g} para {carga.nombre.lower()}.")
    if carga.max_transito_min is not None:
        if t_orig_min + espera_total > carga.max_transito_min:
            avisos.append(f"Esperando, el viaje superaría el máximo en tránsito ({fmt_min(carga.max_transito_min)}).")
        if t_alt_min > carga.max_transito_min:
            avisos.append(f"Por la alterna, el viaje superaría el máximo en tránsito ({fmt_min(carga.max_transito_min)}).")

    if espera_total <= 0:
        llegada = ("Llega a cada bloqueo después de su reapertura estimada." if varios else
                   f"Llega al bloqueo en {fmt_min(t_primer_min)}, después de la reapertura estimada.")
        return Recomendacion(
            "CONTINUAR", "Continuar y reevaluar",
            razones=[llegada, "Se vuelve a evaluar antes del punto de decisión con la información de ese momento."],
            avisos=avisos, espera_real_min=0.0, espera_max_min=espera_max)

    if limite is not None and espera_mayor > limite:
        return Recomendacion(
            "DESVIAR", "Desviar por la alterna",
            razones=[f"Tendría que esperar {fmt_min(espera_mayor)} detenido en un bloqueo; el máximo para "
                     f"{carga.nombre.lower()} es {fmt_min(limite)}."],
            avisos=avisos, espera_real_min=espera_total, espera_max_min=espera_max)

    if espera_total > umbral_costo:
        return Recomendacion(
            "DESVIAR", "Desviar por la alterna",
            razones=[f"{espera_txt} ({fmt_min(espera_total)}) supera la espera máxima conveniente "
                     f"({fmt_min(umbral_costo)})."],
            avisos=avisos, espera_real_min=espera_total, espera_max_min=espera_max)

    return Recomendacion(
        "ESPERAR", "Esperar la reapertura",
        razones=[f"{espera_txt} ({fmt_min(espera_total)}) está dentro de la espera máxima ({fmt_min(espera_max)}).",
                 f"La alterna toma {fmt_min(holgura)} más que la ruta habitual."],
        avisos=avisos, espera_real_min=espera_total, espera_max_min=espera_max)


def recomendar(t_orig_min: float, t_alt_min: float | None, t_hasta_bloqueo_min: float,
               reapertura_min: float, carga: ParametrosCarga, hora_local: int,
               margen_min: float = MARGEN_MIN, horas_calor: tuple = HORAS_CALOR) -> Recomendacion:
    """Un solo bloqueo sobre la ruta habitual."""
    return recomendar_varios(t_orig_min, t_alt_min, [(t_hasta_bloqueo_min, reapertura_min)],
                             carga, hora_local, margen_min, horas_calor)


def recomendar_varios(t_orig_min: float, t_alt_min: float | None, bloqueos: list,
                      carga: ParametrosCarga, hora_local: int,
                      margen_min: float = MARGEN_MIN, horas_calor: tuple = HORAS_CALOR) -> Recomendacion:
    """
    t_orig_min: duración restante por la ruta habitual, sin contar esperas.
    t_alt_min: duración por la alterna que evita todos los bloqueos (None si no hay).
    bloqueos: [(minutos de viaje hasta el bloqueo, minutos hasta su reapertura)] de los que están
              sobre la ruta habitual.
    """
    total, mayor = espera_secuencial(bloqueos)
    primero = min(b[0] for b in bloqueos) if bloqueos else 0.0
    return _decidir(t_orig_min, t_alt_min, total, mayor, primero, carga, hora_local,
                    margen_min, horas_calor, len(bloqueos))
