"""Rutas predefinidas guardadas en BigQuery (tabla fen_7_rutas)."""
import json

from .hidrologia import validar_tabla

SQL = """
SELECT id, nombre, origen_nombre, origen_lat, origen_lon, destino_nombre, destino_lat, destino_lon,
       puntos_paso, tipo_carga, perfil, activo
FROM `{tabla}`
QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY actualizado DESC) = 1
"""


def a_ruta(fila: dict) -> dict:
    """Convierte una fila de BigQuery en la ruta que usa la app (coordenadas como (lon, lat))."""
    paso = fila.get("puntos_paso")
    try:
        paso = [tuple(p) for p in json.loads(paso)] if paso else []
    except (ValueError, TypeError):
        paso = []
    return {"id": fila["id"], "nombre": fila["nombre"],
            "origen_nombre": fila.get("origen_nombre") or "Origen",
            "destino_nombre": fila.get("destino_nombre") or "Destino",
            "origen": (fila["origen_lon"], fila["origen_lat"]),
            "destino": (fila["destino_lon"], fila["destino_lat"]),
            "puntos_paso": paso, "tipo_carga": fila.get("tipo_carga"), "perfil": fila.get("perfil")}


def rutas_activas(info_cuenta: dict, tabla: str) -> list:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    cred = service_account.Credentials.from_service_account_info(info_cuenta)
    cliente = bigquery.Client(credentials=cred, project=cred.project_id)
    filas = [dict(f.items()) for f in cliente.query(SQL.format(tabla=validar_tabla(tabla))).result()]
    rutas = [a_ruta(f) for f in filas if f.get("activo") is not False]
    return sorted(rutas, key=lambda r: r["nombre"])
