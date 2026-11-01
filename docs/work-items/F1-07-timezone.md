# F1-07 — Real-Time y Plot respetan la zona horaria

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-07-timezone` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F1-03 (ya en `dev`)
- **Base commit:** e1e9a3d

## Problema
La zona horaria elegida en Time Config no se aplica en Real-Time: su columna TS muestra
segundos crudos (verificado en captura con el log de campo `DD422-07/log_5.txt`). Además,
`PlotWindowManager.set_timezone` existe pero nadie lo llama.

Contexto (verificado):
- Tabla principal: `views/main_window.py:62-63` instala `TsDisplayDelegate(self._timezone_mode)`
  en la columna TS, y `_on_timezone_changed` (`views/main_window.py:~454`) llama a
  `set_timezone_mode` + `viewport().update()`. La fuente es `vm.timezone_changed`
  (`viewmodels/main_window_viewmodel.py`, reemite `time_config_vm.timezone_changed`).
- Real-Time: `views/realtime_analysis_window.py` solo instala un delegate en DATA
  (`REAL_TIME_ANALYSIS_COLUMNS.index("DATA")`, ~línea 69); TS no tiene delegate.
- Otras ventanas (Analyze, Candidate, Range Diff) reciben `timezone_mode` inicial por su
  manager (`get_timezone`) y escuchan `time_config_vm.timezone_changed`.
- Plot: `views/plot/plot_window.py:73` ya conecta `time_vm.timezone_changed` →
  `_set_timezone`; `views/plot/plot_window_manager.py:46-48` `set_timezone` no tiene
  llamadores (grep).
- Recuerda la trampa de AGENTS.md: en Plot nunca `plot.setAxisItems`.

## Propiedad
- **Puede editar:** `views/realtime_analysis_window.py`,
  `views/realtime_analysis_window_manager.py`, `views/main_window.py` (solo la construcción de
  `RealTimeAnalysisWindowManager`), `views/plot/plot_window_manager.py`, tests en `tests/`,
  `tests/README.md`, `docs/testing.md`, `docs/bugs.md`, `docs/plan.md`, `CHANGELOG.md`,
  esta tarjeta.
- **No puede editar:** `viewmodels/main_window_viewmodel.py`, `viewmodels/range_diff_viewmodel.py`
  (F1-05 en paralelo), `views/plot/plot_window.py` salvo que demuestres que Plot no respeta la
  zona (justifícalo), Mux Detection, HMI/OCR.

## Decisiones cerradas
- Real-Time sigue el patrón de las demás ventanas: el manager recibe `time_config_vm` y
  `get_timezone`, pasa `timezone_mode` inicial a la ventana, y la ventana instala
  `TsDisplayDelegate` en la columna TS y escucha `time_config_vm.timezone_changed`.
- La conexión a `timezone_changed` debe entrar en la lista de conexiones que la ventana
  desconecta en `closeEvent` (`_vm_connections`, ver B-33), o ser un slot ligado al objeto
  ventana; nunca una `lambda` que sobreviva a la ventana.
- Plot: primero comprueba (test o lectura) que una ventana de plot abierta se actualiza al
  cambiar la zona vía `time_vm`. Si es así, borra `PlotWindowManager.set_timezone` como código
  muerto. Si no, cablea lo mínimo para que funcione y explica por qué.

## Trabajo
1. Real-Time: delegate TS + zona inicial + cambio en vivo.
2. Manager y `main_window.py`: pasar `time_config_vm` y `get_timezone`.
3. Plot: confirmar y limpiar `set_timezone`.

## Pruebas
- Regresión primero (rojo → verde), sin construir widgets reales en `tests/` (ver la nota ⚠️ de
  `docs/testing.md`). Prueba lo que se pueda sin ventana: p. ej. que el manager pase
  `timezone_mode` y `time_config_vm` al construir (con la ventana parcheada, como
  `tests/test_analyze_data_window_manager.py`).
- Suite completa en verde.
- `/verify-ui` (el orquestador): replay del log de campo, Real-Time abierto, cambiar la zona en
  Time Config → la columna TS cambia de formato; un plot abierto también.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica
