# D-03 — Grabación continua

- **Estado:** Hecho
- **Fase:** D
- **Rama:** `feature/d-03-continuous-recording` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-01, D-02
- **Base commit:** 2f40262

## Problema
Una captura activa solo vive en memoria y se pierde si el proceso termina de forma inesperada.
El plan propone escribir cada chunk durante la captura y ofrecer la recuperación al reiniciar.

## Propiedad
- **Puede editar:** `services/continuous_recorder.py`, `viewmodels/continuous_recorder_viewmodel.py`,
  `viewmodels/main_window_viewmodel.py`, `viewmodels/connection_stream_viewmodel.py`,
  `views/main_window.py`, `config/defaults.py`, `config/ui_text.py`, `tests/test_continuous_recorder.py`,
  `services/can_data_parser.py`, `tests/test_can_data_parser.py`,
  `tests/test_continuous_recorder_viewmodel.py`, `tests/README.md`, `docs/testing.md`,
  `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, `scripts/`, D-01/D-02 salvo para
  integración imprescindible de los flujos de cierre.

## Decisiones cerradas
- La grabación comienza y termina junto con cada captura/replay, sin depender del guardado manual.
- Escribir en candump estándar en un worker propio y encolado por chunks; nunca serializar todo
  el DataFrame acumulado.
- Guardar en una carpeta configurable y usar nombre con fecha, hora y fuente.
- Un marcador de sesión distingue una grabación completada de una interrumpida. Solo ofrecer la
  recuperación si quedó una sesión activa; no modificar logs de campo.
- La UI muestra estado, ruta y tamaño aproximado durante la captura. Los avisos D-01 indican la
  ruta de la grabación activa.

## Trabajo
1. Crear escritor incremental Qt-free, seguro ante errores y con cierre que vacía la cola.
2. Crear ViewModel worker con inicio/stop, estado y tamaño; conectar los chunks crudos de la
   conexión sin hacer trabajo de I/O en el hilo UI.
3. Añadir indicador y preferencia de carpeta.
4. Detectar una grabación interrumpida al abrir y ofrecer cargarla en Canlytics.
5. Integrar cierre normal y rutas de D-01 sin perder chunks pendientes.

## Pruebas
- Regresión primero: escritura incremental, cola drenada al parar, marcador completado, marcador
  residual recuperable, error de disco y separación de buses. El parser también lee el sufijo
  `R`/`T` que emite el exportador estándar de python-can.
- Suite completa verde: 958 pruebas.
- `/verify-ui`: capturar/reproducir, observar ruta/tamaño, cerrar con grabación activa y aceptar
  recuperación al relanzar. Las capturas están en el scratchpad de la sesión.
- Replay de campo para D-01: 1248 filas en memoria, 1248 frames guardados y flag sin guardar
  en `False`; el aviso incluye la ruta de grabación continua.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
