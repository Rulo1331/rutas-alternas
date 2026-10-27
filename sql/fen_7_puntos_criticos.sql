-- Puntos críticos de bloqueo. Las rutas afectadas NO se registran: el sistema las detecta por cercanía.
CREATE TABLE IF NOT EXISTS `appsheetgr.BD_Procesamiento.fen_7_puntos_criticos` (
  id                   STRING    NOT NULL,  -- PC-001, PC-002…
  nombre               STRING    NOT NULL,  -- "Puente Virú", "Quebrada San Idelfonso"
  referencia           STRING,              -- "km 515 Panamericana Norte", "entrada a Chao"
  lat                  FLOAT64   NOT NULL,
  lon                  FLOAT64   NOT NULL,
  tipo_evento          STRING    NOT NULL,  -- huaico | derrumbe | inundacion | desborde | erosion_socavacion |
                                            -- colapso_puente | conflicto_social | accidente_recurrente | otro
  frecuencia           STRING,              -- alta | media | baja
  eventos_10_anios     INT64,               -- veces que se cerró en los últimos 10 años (si se sabe)
  duracion_tipica_h    FLOAT64,             -- cuánto suele durar el cierre, en horas
  meses_riesgo         STRING,              -- "ene,feb,mar"
  ultimo_evento        DATE,
  fuente               STRING,              -- historial_interno | choferes | geocatmin | cenepred | provias | noticias | otro
  rio_quebrada         STRING,              -- río o quebrada asociada (si aplica)
  alterna_conocida     STRING,              -- descripción libre de la alterna que se usa hoy
  alterna_apta         STRING,              -- si | no | no_se  (¿pasan los camiones de la empresa?)
  alterna_apta_para    STRING,              -- "C2, C3" / "todos menos T3S3"…
  observaciones        STRING,
  activo               BOOL      NOT NULL,
  actualizado          TIMESTAMP NOT NULL
);
-- Carga desde la plantilla CSV: en BigQuery, abre la tabla → "Agregar datos" (o "Cargar") → archivo CSV,
-- modo "Anexar a la tabla", "Filas de encabezado que se omitirán" = 1. Las columnas activo y actualizado
-- ya vienen en la plantilla.
