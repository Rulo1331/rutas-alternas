"""Regla de decisión: esperar, desviar o continuar. Lógica pura, sin APIs."""
from .modelos import ParametrosCarga, Recomendacion
from .parametros import MARGEN_MIN, HORAS_CALOR


def fmt_min(m: float | None) -> str:
    if m is None:
        return "—"
    m = int(round(m))
    h, r = divmod(m, 60)
    return f"{h} h {r:02d} min" if h else f"{r} min"


def recomendar(t_orig_min: float, t_alt_min: float | None, t_hasta_bloqueo_min: float,
               reapertura_min: float, carga: ParametrosCarga, hora_local: int,
               margen_min: float = MARGEN_MIN, horas_calor: tuple = HORAS_CALOR) -> Recomendacion:
    """
    t_orig_min: duración restante por la ruta habitual, sin contar la espera.
    t_alt_min: duración restante por la alterna (None si no hay alterna).
    t_hasta_bloqueo_min: cuánto tarda el camión en llegar al bloqueo.
    reapertura_min: minutos (desde ahora) hasta la reapertura estimada.
    """
    espera_real = max(0.0, reapertura_min - t_hasta_bloqueo_min)
    calor = horas_calor[0] <= hora_local < horas_calor[1]
    factor = carga.factor_calor if calor else 1.0

    if t_alt_min is None:
        return Recomendacion(
            "SIN_ALTERNA", "Sin ruta alterna: esperar",
            razones=["No se encontró una ruta que evite el bloqueo para este vehículo."],
            espera_real_min=espera_real)

    holgura = t_alt_min - t_orig_min
    espera_max = max(0.0, (holgura - margen_min) / factor)
    limite_duro = carga.max_detenido_min is not None and carga.max_detenido_min < espera_max
    if limite_duro:
        espera_max = float(carga.max_detenido_min)

    avisos = []
    if calor and factor > 1:
        avisos.append(f"Horario de calor: cada minuto de espera cuenta ×{factor:g} para {carga.nombre.lower()}.")
    if carga.max_transito_min is not None:
        if t_orig_min + espera_real > carga.max_transito_min:
            avisos.append(f"Esperando, el viaje superaría el máximo en tránsito ({fmt_min(carga.max_transito_min)}).")
        if t_alt_min > carga.max_transito_min:
            avisos.append(f"Por la alterna, el viaje superaría el máximo en tránsito ({fmt_min(carga.max_transito_min)}).")

    if espera_real <= 0:
        return Recomendacion(
            "CONTINUAR", "Continuar y reevaluar",
            razones=[f"Llega al bloqueo en {fmt_min(t_hasta_bloqueo_min)}, después de la reapertura estimada.",
                     "Se vuelve a evaluar antes del punto de decisión con la información de ese momento."],
            avisos=avisos, espera_real_min=0.0, espera_max_min=espera_max)

    if espera_real > espera_max:
        motivo = (f"La espera estimada ({fmt_min(espera_real)}) supera el máximo detenido para "
                  f"{carga.nombre.lower()} ({fmt_min(carga.max_detenido_min)})." if limite_duro else
                  f"La espera estimada ({fmt_min(espera_real)}) supera la espera máxima conveniente ({fmt_min(espera_max)}).")
        return Recomendacion("DESVIAR", "Desviar por la alterna", razones=[motivo],
                             avisos=avisos, espera_real_min=espera_real, espera_max_min=espera_max)

    return Recomendacion(
        "ESPERAR", "Esperar la reapertura",
        razones=[f"La espera estimada ({fmt_min(espera_real)}) está dentro de la espera máxima ({fmt_min(espera_max)}).",
                 f"La alterna toma {fmt_min(holgura)} más que la ruta habitual."],
        avisos=avisos, espera_real_min=espera_real, espera_max_min=espera_max)
