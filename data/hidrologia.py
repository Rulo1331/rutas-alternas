"""Lectura del último dato de cada estación hidrológica desde BigQuery."""
import re

SQL = """
SELECT cod_estacion, estacion, rio, departamento, variable, unidad, fecha_hora, valor,
       umbral_amarillo, umbral_naranja, umbral_rojo
FROM `{tabla}`
WHERE fecha_hora >= DATETIME_SUB(CURRENT_DATETIME("America/Lima"), INTERVAL @dias DAY)
QUALIFY ROW_NUMBER() OVER (PARTITION BY cod_estacion, variable ORDER BY fecha_hora DESC) = 1
"""


def validar_tabla(tabla: str) -> str:
    if not re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", tabla or ""):
        raise ValueError(f"Nombre de tabla no válido: {tabla!r} (formato proyecto.dataset.tabla)")
    return tabla


def ultimos_datos(info_cuenta: dict, tabla: str, dias: int = 3) -> list:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    cred = service_account.Credentials.from_service_account_info(info_cuenta)
    cliente = bigquery.Client(credentials=cred, project=cred.project_id)
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("dias", "INT64", dias)])
    trabajo = cliente.query(SQL.format(tabla=validar_tabla(tabla)), job_config=config)
    return [dict(fila.items()) for fila in trabajo.result()]
