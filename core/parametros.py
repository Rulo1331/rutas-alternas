"""Valores PROVISIONALES. Deben validarlos producción, calidad y comercial.
Más adelante se leerán desde BigQuery; por ahora viven aquí para poder probar."""
from .modelos import PerfilVehiculo, ParametrosCarga

# Máximos legales por configuración (RNV, DS 058-2003-MTC). Reemplazar por datos reales por placa.
PERFILES = {
    "granelero_t3s3": PerfilVehiculo("granelero_t3s3", "Granelero de alimento (T3S3)", 4.10, 2.60, 20.50, 48.0),
    "jaulero_c3": PerfilVehiculo("jaulero_c3", "Jaulero pollo vivo (C3)", 4.10, 2.60, 12.30, 25.0),
    "frigorifico_c2": PerfilVehiculo("frigorifico_c2", "Furgón frigorífico (C2)", 4.30, 2.60, 12.30, 18.0),
}

CARGAS = {
    "pollo_vivo": ParametrosCarga("pollo_vivo", "Pollo vivo", 30, 240, 2.0, "jaulero_c3"),
    "pollo_beneficiado": ParametrosCarga("pollo_beneficiado", "Pollo beneficiado", None, 360, 1.5, "frigorifico_c2"),
    "alimento": ParametrosCarga("alimento", "Alimento", None, None, 1.0, "granelero_t3s3"),
}

MARGEN_MIN = 10                 # solo se recomienda esperar con al menos este margen
HORAS_CALOR = (10, 16)          # [inicio, fin) en hora local
RADIO_BLOQUEO_M = 150           # tamaño de la zona excluida alrededor del bloqueo

# Para decidir se usa el extremo SUPERIOR de cada rango (criterio conservador)
REAPERTURA_OPCIONES = {"< 1 h": 60, "1–3 h": 180, "3–6 h": 360, "> 6 h": 720, "No sé": None}
REAPERTURA_DESCONOCIDA_MIN = 180  # se reemplazará por el promedio histórico por causa
