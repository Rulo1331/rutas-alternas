"""Descarga de OpenStreetMap el trazado de los ríos que tienen estación en la tabla de hidrología
y lo guarda en datos/rios.geojson. Se ejecuta desde GitHub Actions ("Actualizar ríos").

Variables de entorno:
  GCP_SA_KEY      JSON de la cuenta de servicio (lee la lista de ríos desde BigQuery)
  BQ_TABLA_HIDRO  proyecto.dataset.tabla de hidrología
  RIOS            (opcional, para pruebas) "Chicama|La Libertad;La Leche|Lambayeque" en vez de BigQuery
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import shapely
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge, unary_union

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from core.geometria import ProyeccionLocal  # noqa: E402
from core.rios import clave_rio, normalizar_rio, plano  # noqa: E402

OVERPASS = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
SALIDA = RAIZ / "datos" / "rios.geojson"
TOLERANCIA_M = 25  # simplificación del trazado

DEPARTAMENTOS = {plano(n): n for n in [
    "Amazonas", "Áncash", "Apurímac", "Arequipa", "Ayacucho", "Cajamarca", "Callao", "Cusco",
    "Huancavelica", "Huánuco", "Ica", "Junín", "La Libertad", "Lambayeque", "Lima", "Loreto",
    "Madre de Dios", "Moquegua", "Pasco", "Piura", "Puno", "San Martín", "Tacna", "Tumbes", "Ucayali"]}
_VARIANTES = {"a": "[aá]", "e": "[eé]", "i": "[ií]", "o": "[oó]", "u": "[uúü]", "n": "[nñ]"}


def patron_nombre(rio: str) -> str:
    """Expresión regular tolerante a tildes y mayúsculas: 'Virú' coincide con 'Río Viru', 'RIO VIRÚ', etc."""
    base = normalizar_rio(rio)
    cuerpo = "".join(" +" if c == " " else _VARIANTES.get(c, re.escape(c)) for c in base)
    return f"^(r[ií]o +)?{cuerpo}$"


def consulta_overpass(departamento_osm: str, rios: list) -> str:
    filtros = "\n".join(
        f'  relation["waterway"="river"]["name"~"{patron_nombre(r)}",i](area.a);\n'
        f'  way["waterway"="river"]["name"~"{patron_nombre(r)}",i](area.a);' for r in rios)
    return (f'[out:json][timeout:180];\n'
            f'area["boundary"="administrative"]["admin_level"="4"]["name"="{departamento_osm}"]->.a;\n'
            f'(\n{filtros}\n);\nout geom;')


def lineas_de_elemento(el: dict) -> list:
    if el.get("type") == "way" and el.get("geometry"):
        tramos = [el["geometry"]]
    elif el.get("type") == "relation":
        tramos = [m["geometry"] for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
    else:
        tramos = []
    return [LineString([(p["lon"], p["lat"]) for p in t]) for t in tramos if len(t) >= 2]


def construir_features(elementos: list, rios: list, departamento: str) -> list:
    """Agrupa los tramos por río, los une y simplifica. Devuelve un Feature por río encontrado."""
    buscados = {normalizar_rio(r): r for r in rios}
    lineas = {}
    for el in elementos:
        clave = normalizar_rio(el.get("tags", {}).get("name", ""))
        if clave in buscados:
            lineas.setdefault(clave, []).extend(lineas_de_elemento(el))
    features = []
    for clave, ls in lineas.items():
        if not ls:
            continue
        unido = linemerge(unary_union(ls))
        c = unido.centroid
        proj = ProyeccionLocal(c.x, c.y)
        simple = shapely.set_precision(proj.a_grados(proj.a_metros(unido).simplify(TOLERANCIA_M)), 1e-5)
        rio = buscados[clave]
        features.append({"type": "Feature", "geometry": mapping(simple),
                         "properties": {"rio": rio, "departamento": departamento,
                                        "clave": clave_rio(rio, departamento)}})
    return features


def rios_desde_bigquery() -> list:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    from data.hidrologia import validar_tabla
    cred = service_account.Credentials.from_service_account_info(json.loads(os.environ["GCP_SA_KEY"]))
    cliente = bigquery.Client(credentials=cred, project=cred.project_id)
    sql = (f"SELECT DISTINCT rio, departamento FROM `{validar_tabla(os.environ['BQ_TABLA_HIDRO'])}` "
           "WHERE fecha_hora >= DATETIME_SUB(CURRENT_DATETIME('America/Lima'), INTERVAL 30 DAY) "
           "AND rio IS NOT NULL AND departamento IS NOT NULL")
    return [(f["rio"], f["departamento"]) for f in cliente.query(sql).result()]


def pedir_overpass(consulta: str) -> list:
    for intento in range(4):
        r = requests.post(OVERPASS, data={"data": consulta}, timeout=240,
                          headers={"User-Agent": "rutas-alternas-elrocio/1.0"})
        if r.status_code == 200:
            return r.json().get("elements", [])
        print(f"  Overpass respondió {r.status_code}; reintento en {30 * (intento + 1)} s")
        time.sleep(30 * (intento + 1))
    raise RuntimeError("Overpass no respondió tras varios intentos")


def main():
    if os.environ.get("RIOS"):
        pares = [tuple(x.split("|", 1)) for x in os.environ["RIOS"].split(";") if "|" in x]
    else:
        pares = rios_desde_bigquery()
    por_depto = {}
    for rio, depto in pares:
        por_depto.setdefault(depto, []).append(rio)

    features, faltan = [], []
    for depto, rios in sorted(por_depto.items()):
        nombre_osm = DEPARTAMENTOS.get(plano(depto))
        if not nombre_osm:
            print(f"⚠ Departamento no reconocido: {depto!r} ({', '.join(rios)})")
            faltan += [f"{r} ({depto})" for r in rios]
            continue
        print(f"→ {nombre_osm}: {', '.join(rios)}")
        nuevos = construir_features(pedir_overpass(consulta_overpass(nombre_osm, rios)), rios, depto)
        encontrados = {f["properties"]["rio"] for f in nuevos}
        faltan += [f"{r} ({depto})" for r in rios if r not in encontrados]
        features += nuevos
        time.sleep(5)  # uso respetuoso del servicio público

    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps({
        "type": "FeatureCollection",
        "metadata": {"generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "fuente": "© OpenStreetMap contributors (ODbL)"},
        "features": features}, ensure_ascii=False), encoding="utf-8")
    print(f"✓ {len(features)} ríos guardados en {SALIDA.relative_to(RAIZ)}")
    if faltan:
        print("⚠ No encontrados en OpenStreetMap: " + "; ".join(faltan))


if __name__ == "__main__":
    main()
