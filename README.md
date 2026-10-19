# Rutas alternas · El Rocío

Sistema para decidir si un camión debe **esperar**, **desviar** o **continuar** ante una interrupción de la vía.
Fase actual: **validación** en Streamlit Community Cloud con OpenRouteService.

## Estructura
- `app.py` — interfaz Streamlit (solo presentación).
- `core/` — lógica pura: modelos, parámetros provisionales, regla de decisión, geometría. No depende de Streamlit.
- `engines/ors.py` — adaptador del motor de rutas. Al migrar a ORS propio solo cambia `base_url`.
- `tests/` — pruebas de la lógica (`pytest`).

## Puesta en marcha (Streamlit Cloud)
1. Crea una cuenta en openrouteservice.org y genera una API key (plan Standard, gratuito).
2. Sube este repositorio a GitHub (sin `secrets.toml`).
3. En share.streamlit.io: *Create app* → elige el repo → archivo principal `app.py`.
4. En *Settings → Secrets* pega: `ORS_API_KEY = "tu_clave"`.

## Cuota de ORS (plan gratuito)
Cada clic en **Calcular** usa hasta 3 consultas (ruta habitual, ajuste del bloqueo a la vía y alterna).
Los resultados se guardan en caché 6 h para no repetir consultas.
