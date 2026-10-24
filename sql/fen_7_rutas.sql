-- 1) Crear la tabla (una sola vez)
CREATE TABLE IF NOT EXISTS `appsheetgr.BD_Procesamiento.fen_7_rutas` (
  id              STRING    NOT NULL,   -- identificador corto, p. ej. 'TRU-PIU'
  nombre          STRING    NOT NULL,   -- lo que se ve en la lista de la app
  origen_nombre   STRING,
  origen_lat      FLOAT64   NOT NULL,
  origen_lon      FLOAT64   NOT NULL,
  destino_nombre  STRING,
  destino_lat     FLOAT64   NOT NULL,
  destino_lon     FLOAT64   NOT NULL,
  puntos_paso     STRING,               -- JSON [[lon, lat], ...] para forzar el camino habitual (opcional)
  tipo_carga      STRING,               -- pollo_vivo | pollo_beneficiado | alimento (opcional)
  perfil          STRING,               -- granelero_t3s3 | jaulero_c3 | frigorifico_c2 (opcional)
  activo          BOOL      NOT NULL,
  actualizado     TIMESTAMP NOT NULL,
  actualizado_por STRING
);

-- 2) Agregar rutas. Las coordenadas de ejemplo son los centros de cada ciudad:
--    reemplázalas por las de la planta, granja o comprador real.
INSERT INTO `appsheetgr.BD_Procesamiento.fen_7_rutas`
  (id, nombre, origen_nombre, origen_lat, origen_lon, destino_nombre, destino_lat, destino_lon,
   puntos_paso, tipo_carga, perfil, activo, actualizado, actualizado_por)
VALUES
  ('TRU-PIU', 'Trujillo → Piura', 'Trujillo', -8.1116, -79.0287, 'Piura', -5.1945, -80.6328,
   NULL, 'pollo_beneficiado', 'frigorifico_c2', TRUE, CURRENT_TIMESTAMP(), 'Eduardo'),
  ('TRU-CHA', 'Trujillo → Chao', 'Trujillo', -8.1116, -79.0287, 'Chao', -8.5395, -78.6789,
   NULL, 'alimento', 'granelero_t3s3', TRUE, CURRENT_TIMESTAMP(), 'Eduardo');

-- 3) Para CAMBIAR una ruta no se edita la fila: se inserta otra con el mismo id y la app usa la más reciente.
--    Para DESACTIVARLA, inserta una fila con el mismo id y activo = FALSE.
