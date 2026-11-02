# F2-07 — Guardián de memoria y estado de medición

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `feat/f2-07-live-status-memory-guard` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-03, F2-02
- **Base commit:** 54bae6f

## Problema
Durante una medición, la barra de estado no reúne conexión, tasa de frames, tamaño de la captura,
RAM, DBC activos, filtro temporal y zona horaria. ADR 002 pide advertir antes de que una sesión
larga consuma demasiada memoria, sin descartar frames automáticamente.

## Propiedad
- **Puede editar:** `services/measurement_status.py`, `viewmodels/measurement_status_viewmodel.py`,
  `viewmodels/main_window_viewmodel.py`, `viewmodels/table_filter_viewmodel.py`,
  `views/main_window.py`, `config/defaults.py`, `config/ui_text.py`,
  `tests/test_measurement_status.py`, `tests/test_measurement_status_viewmodel.py`, `tests/README.md`, `docs/testing.md`,
  `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/continuous_recorder.py`, captura/guardado D-03, lógica de Mux
  Detection, HMI/OCR, `requirements.txt`.

## Decisiones cerradas
- La barra actualiza el fps desde chunks nuevos y los frames desde el DataFrame actual; no usa un
  watermark del DataFrame ni recorre su historial para calcular tasas.
- La RAM mostrada es el working set del proceso. El umbral es el menor entre 2 GiB y el 60 % de
  RAM física, ambos ajustables mediante `DEFAULT_OPTIONS`; se mide en Windows, Linux y macOS, y
  no se limita ni descarta memoria.
- D-03 ya graba continuamente. El aviso ofrece guardar un snapshot completo y limpiar después de
  que la exportación termine correctamente. Para preservar consistencia, esa acción detiene y
  drena la captura; cancelar o fallar el guardado conserva el DataFrame.
- DBC y rango de tiempo muestran un resumen compacto con el detalle completo en tooltip.

## Trabajo
1. Mostrar conexión coloreada, fps, frames, working set, DBC activo, rango de tiempo y zona horaria
   como widgets permanentes de la barra de estado.
2. Calcular memoria del proceso sin dependencias nuevas y avisar una sola vez por cruce del umbral.
3. Ofrecer guardar el snapshot y limpiar la memoria solo tras un guardado correcto.
4. Verificar barra/aviso en la app y actualizar arquitectura y guías de pruebas.

## Pruebas
- Caracterizar ventana de fps, expiración de muestras y selección del umbral.
- Suite completa verde.
- `/verify-ui`: abrir la app, confirmar los siete indicadores, conectar un replay y observar fps,
  frames y grabación; verificar el estado de filtro/DBC/zona horaria.
- Revisar el flujo de guardado/limpieza; no limpiar si se cancela la exportación.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
- [x] Suite completa y verificación UI

## Evidencia
- Suite completa: 1009 tests, todos pasan; `code-reviewer` y `qt-mvvm-reviewer`: ship.
- Replay de `candump-sample.log`: se mostraron 272 fps y 494 frames en vivo; al drenar, 685
  frames. La barra mostró conexión coloreada, fps, frames, RAM, DBC, filtro y zona horaria.
- Umbral forzado solo para verificar el diálogo: al elegir “Later”, los 929 frames recibidos
  siguieron en memoria. Capturas revisadas fuera del repo en `%TEMP%/canlytics-f207/`.
