# F1-04 — Analyze Data recibe datos solo con su ventana abierta

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-04-analyze-only-when-open` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 4775fd0

## Problema
Analyze Data procesa cada flush en vivo aunque su ventana esté cerrada.

Causa (verificada):
- `viewmodels/main_window_viewmodel.py:68-69` conecta `data_vm.dataframe_changed` →
  `analyze_data_vm.set_dataframe` y `dataframe_replaced` → `reset_dataframe` para siempre.
- `viewmodels/main_window_viewmodel.py:83` conecta `connection_vm.chunk_ready` →
  `analyze_data_vm.ingest_raw_chunk` para siempre.
- `set_dataframe` (`viewmodels/analyze_data_viewmodel.py:114`) llama `sorted_can_ids` sobre el
  df completo en cada flush y puede disparar `_full_refresh()`.
- Candidate Interpretations ya resolvió lo mismo: ver
  `views/candidate_interpretations_window_manager.py` (patrón a copiar).

## Propiedad
- **Puede editar:** `views/analyze_data_window_manager.py`,
  `viewmodels/main_window_viewmodel.py` (solo las líneas 68, 69 y 83 de este cableado),
  `views/main_window.py` (solo la construcción de `AnalyzeDataWindowManager`), tests en
  `tests/`, `docs/testing.md`, `docs/bugs.md`, `docs/plan.md`, `CHANGELOG.md`,
  `docs/architecture/overview.md` si describe este cableado, esta tarjeta.
- **No puede editar:** `viewmodels/real_time_analysis_viewmodel.py`,
  `views/realtime_analysis_window*.py`, `viewmodels/can_send_viewmodel.py`,
  `viewmodels/connection_stream_viewmodel.py` (tarjetas en paralelo), la lógica de
  `viewmodels/analyze_data_viewmodel.py` salvo que sea imprescindible (justifícalo), Mux
  Detection, HMI/OCR.

## Decisiones cerradas
- El manager recibe `data_vm` y `connection_vm`. En `_create_window`:
  1. prime: `vm.reset_dataframe(data_vm.df)` y luego `vm.set_dataframe(data_vm.df)`;
  2. conecta `dataframe_changed` → `set_dataframe`, `dataframe_replaced` → `reset_dataframe`
     y `chunk_ready` → `ingest_raw_chunk`.
- `_on_window_destroyed` desconecta las tres (con `try/except (TypeError, RuntimeError)`) y
  llama a `super()`. La ventana ya usa `WA_DeleteOnClose`.
- Se borran las tres conexiones de `main_window_viewmodel.py`. `shutdown()` sigue igual.
- Antes de borrar, comprueba con grep que nada más dependa de `analyze_data_vm` actualizado
  con la ventana cerrada (handoffs, menús). Si algo depende, repórtalo y no lo rompas.

## Trabajo
1. Cableado perezoso en el manager.
2. Quitar el cableado permanente y pasar las dependencias nuevas desde `main_window.py`.

## Pruebas
- Regresión primero (rojo → verde), sin construir la ventana real (usa un `_create_window`
  stub o mocks de señales):
  - antes de abrir, emitir `dataframe_changed` / `chunk_ready` no llama a la VM;
  - al abrir, la VM queda primada con el df actual y conectada;
  - al destruirse la ventana, se desconecta y libera el estado del análisis;
  - si falla el constructor, no quedan conexiones y una reapertura conecta una sola vez.
- Suite completa en verde.
- `/verify-ui` (el orquestador): con un log de Fase 02, abrir Analyze Data muestra los IDs y
  la matriz igual que antes; en replay, se actualiza mientras está abierta.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica (no aplica)
