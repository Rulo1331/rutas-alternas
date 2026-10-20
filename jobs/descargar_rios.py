"""Descarga de OpenStreetMap el trazado de los ríos que tienen estación en la tabla de hidrología
y lo guarda en datos/rios.geojson. Se ejecuta desde GitHub Actions ("Actualizar ríos").

Variables de entorno:
  GCP_SA_KEY      JSON de la cuenta de servicio (lee la lista de ríos desde BigQuery)
  BQ_TABLA_HIDRO  proyecto.dataset.tabla de hidrología
  RIOS            (opcional, para pruebas) "Chicama|La Libertad;La Leche|Lambayeque" en vez de BigQuery

Si un río tiene en OpenStreetMap un nombre distinto al de la tabla, agrégalo en datos/alias_rios.csv.
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import shapely
from shapely.geometry import LineString, MultiLineString, mapping
from shapely.ops import linemerge, unary_union

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from core.geometria import ProyeccionLocal  # noqa: E402
from core.rios import clave_rio, normalizar_rio, plano  # noqa: E402

OVERPASS = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
SALIDA = RAIZ / "datos" / "rios.geojson"
ALIAS = RAIZ / "datos" / "alias_rios.csv"
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


def cargar_alias(ruta: Path = ALIAS) -> dict:
    """{nombre normalizado en la tabla: [nombres en OpenStreetMap]}. Líneas con # se ignoran."""
    alias = {}
    if ruta.exists():
        filas = (l for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#"))
        for fila in csv.reader(filas):
            if len(fila) >= 2 and fila[0].strip().lower() != "rio_tabla":
                alias.setdefault(normalizar_rio(fila[0]), []).append(fila[1].strip())
    return alias


def nombres_buscados(rios: list, alias: dict) -> dict:
    """{nombre normalizado a buscar en OSM: río tal como está en la tabla}."""
    buscados = {}
    for r in rios:
        for nombre in [r] + alias.get(normalizar_rio(r), []):
            buscados.setdefault(normalizar_rio(nombre), r)
    return buscados


def consulta_overpass(departamento_osm: str, nombres: list) -> str:
    tipo = '["waterway"~"^(river|canal)$"]'
    filtros = "\n".join(
        f'  relation{tipo}["name"~"{patron_nombre(n)}",i](area.a);\n'
        f'  way{tipo}["name"~"{patron_nombre(n)}",i](area.a);' for n in nombres)
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


def _solo_lineas(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if hasattr(geom, "geoms"):
        return [l for g in geom.geoms for l in _solo_lineas(g)]
    return []


def unir_lineas(lineas: list):
    """Une los tramos de un río. Funciona tanto si queda una sola línea como si quedan varias."""
    partes = _solo_lineas(unary_union(lineas))
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else linemerge(MultiLineString(partes))


def construir_features(elementos: list, rios: list, departamento: str, alias: dict | None = None) -> list:
    """Agrupa los tramos por río, los une y simplifica. Devuelve un Feature por río encontrado."""
    buscados = nombres_buscados(rios, alias or {})
    lineas = {}
    for el in elementos:
        rio = buscados.get(normalizar_rio(el.get("tags", {}).get("name", "")))
        if rio:
            lineas.setdefault(rio, []).extend(lineas_de_elemento(el))
    features = []
    for rio, ls in lineas.items():
        unido = unir_lineas(ls) if ls else None
        if unido is None:
            continue
        c = unido.centroid
        proj = ProyeccionLocal(c.x, c.y)
        simple = shapely.set_precision(proj.a_grados(proj.a_metros(unido).simplify(TOLERANCIA_M)), 1e-5)
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
        print(f"  Overpass respondió {r.status_code}; reintento en {30 * (intento + 1)} s", flush=True)
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

    alias = cargar_alias()
    features, faltan, errores = [], [], []
    for depto, rios in sorted(por_depto.items()):
        nombre_osm = DEPARTAMENTOS.get(plano(depto))
        if not nombre_osm:
            print(f"⚠ Departamento no reconocido: {depto!r} ({', '.join(rios)})", flush=True)
            faltan += [f"{r} ({depto})" for r in rios]
            continue
        print(f"→ {nombre_osm}: {', '.join(rios)}", flush=True)
        try:
            nombres = list(nombres_buscados(rios, alias))
            nuevos = construir_features(pedir_overpass(consulta_overpass(nombre_osm, nombres)), rios, depto, alias)
        except Exception as e:  # un departamento con problemas no detiene a los demás
            print(f"  ✗ Error en {nombre_osm}: {e.__class__.__name__}: {str(e)[:200]}", flush=True)
            errores.append(nombre_osm)
            continue
        encontrados = {f["properties"]["rio"] for f in nuevos}
        print(f"  ✓ {len(encontrados)} de {len(rios)} encontrados", flush=True)
        faltan += [f"{r} ({depto})" for r in rios if r not in encontrados]
        features += nuevos
        time.sleep(5)  # uso respetuoso del servicio público

    if not features:
        raise SystemExit("No se obtuvo ningún río; se mantiene el archivo anterior.")
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps({
        "type": "FeatureCollection",
        "metadata": {"generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "fuente": "© OpenStreetMap contributors (ODbL)"},
        "features": features}, ensure_ascii=False), encoding="utf-8")
    print(f"✓ {len(features)} ríos guardados en {SALIDA.relative_to(RAIZ)}", flush=True)
    if faltan:
        print("⚠ No encontrados en OpenStreetMap (revisa el nombre o agrega un alias):\n  - "
              + "\n  - ".join(faltan), flush=True)
    if errores:
        print("✗ Departamentos con error (vuelve a ejecutar más tarde): " + ", ".join(errores), flush=True)



if __name__ == "__main__":
    main()
