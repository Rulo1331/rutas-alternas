"""Estructuras de datos del sistema. Sin dependencias de Streamlit."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PerfilVehiculo:
    clave: str
    nombre: str
    alto_m: float
    ancho_m: float
    largo_m: float
    peso_t: float


@dataclass(frozen=True)
class ParametrosCarga:
    clave: str
    nombre: str
    max_detenido_min: float | None   # límite duro de espera detenido (None = sin límite)
    max_transito_min: float | None   # tiempo máximo total de viaje (None = sin límite)
    factor_calor: float              # cuánto "pesa" cada minuto de espera en horas de calor
    perfil_sugerido: str


@dataclass
class Ruta:
    duracion_min: float
    distancia_km: float
    coords: list                     # [[lon, lat], ...]


@dataclass
class Recomendacion:
    accion: str                      # DESVIAR | ESPERAR | CONTINUAR | SIN_ALTERNA
    titulo: str
    razones: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    espera_real_min: float = 0.0     # cuánto esperaría al llegar al bloqueo
    espera_max_min: float | None = None  # hasta cuánto conviene esperar
