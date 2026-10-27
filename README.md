# Rutas alternas · El Rocío

Sistema para decidir si un camión debe **esperar**, **desviar** o **continuar** ante una interrupción de la vía.
Fase actual: **validación** en Streamlit Community Cloud con OpenRouteService.

## Estructura
- `app.py` — interfaz Streamlit (solo presentación).
- `core/` — lógica pura: modelos, parámetros provisionales, regla de decisión, geometría. No depende de Streamlit.
- `engines/ors.py` — adaptador del motor de rutas. Al migrar a ORS propio solo cambia `base_url`.
- `data/hidrologia.py` — último dato de cada estación hidrológica (BigQuery).
- `jobs/descargar_rios.py` — descarga el trazado de los ríos de la tabla de hidrología desde OpenStreetMap.
- `datos/rios.geojson` — trazado de ríos generado por la acción «Actualizar ríos».
- `tests/` — pruebas de la lógica (`pytest`).

## Puesta en marcha (Streamlit Cloud)
1. Crea una cuenta en openrouteservice.org y genera una API key (plan Standard, gratuito).
2. Sube este repositorio a GitHub (sin `secrets.toml`).
3. En share.streamlit.io: *Create app* → elige el repo → archivo principal `app.py`.
4. En *Settings → Secrets* pega: `ORS_API_KEY = "tu_clave"`.

## Cuota de ORS (plan gratuito)
Cada clic en **Calcular** usa hasta 3 consultas (ruta habitual, ajuste del bloqueo a la vía y alterna).
Los resultados se guardan en caché 6 h para no repetir consultas.

## Ríos monitoreados
1. En GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   `GCP_SA_KEY` = contenido completo del JSON de la cuenta de servicio.
2. En la pestaña *Actions*, ejecuta **Actualizar ríos** (botón *Run workflow*). Al terminar,
   `datos/rios.geojson` queda en el repositorio y Streamlit se actualiza solo.
3. En los secretos de la app de Streamlit agrega `[gcp_service_account]` (ver `.streamlit/secrets.toml.example`).
4. La cuenta de servicio necesita los roles *BigQuery Data Viewer* (sobre el dataset) y *BigQuery Job User* (proyecto).

Vuelve a ejecutar la acción solo cuando se agreguen estaciones de ríos nuevos.

## Rutas predefinidas
1. En la consola de BigQuery ejecuta `sql/fen_7_rutas.sql` (crea la tabla y dos rutas de ejemplo).
2. Para agregar rutas, repite el `INSERT` con tus coordenadas. La app las lee cada 10 minutos.
3. Opcional: si la tabla tiene otro nombre, agrega `BQ_TABLA_RUTAS = "proyecto.dataset.tabla"` en los secretos.

## Prueba comparativa ORS vs. HERE
- Requiere `HERE_API_KEY` en los secretos. `HERE_LIMITE_DIARIO` (opcional, 100 por defecto) limita las consultas nuevas por día.
- Botón «Comparar con HERE» en el panel de resultados: 3 consultas (habitual, alterna rápida, alterna sin caminos de tierra).
- Las consultas repetidas salen de la caché y no consumen. La tabla se puede descargar en CSV para documentar la validación.
