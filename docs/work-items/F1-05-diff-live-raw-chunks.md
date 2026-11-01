# F1-05 — Diff Live se alimenta del chunk crudo

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-05-diff-live-raw-chunks` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 792fddb

## Problema
Diff Live calcula qué filas son nuevas con un watermark por cantidad de filas sobre el df
acumulado. Eso se rompe cuando `merge_frames` re-ordena: el slice deja de ser "lo nuevo" y
alimenta filas viejas o se salta filas. ADR 001 prohíbe ese patrón.

Causa (verificada):
- `viewmodels/range_diff_viewmodel.py:100-104`: `set_dataframe` (conectado a
  `data_vm.dataframe_changed` en `viewmodels/main_window_viewmodel.py:76`) llama a
  `_feed_live_from_watermark` cuando el live está activo.
- `viewmodels/range_diff_viewmodel.py:167-172`: `_feed_live_from_watermark` hace
  `self._df.slice(self._live_watermark, …)`.
- `capture_live_baseline` (`:144-151`) fija `_live_watermark = self._df.height`.
- Analyze Data ya resolvió lo mismo con `ingest_raw_chunk` alimentado por
  `connection_vm.chunk_ready` (ver `viewmodels/analyze_data_viewmodel.py::ingest_raw_chunk`).

## Propiedad
- **Puede editar:** `viewmodels/range_diff_viewmodel.py`, `viewmodels/main_window_viewmodel.py`
  (solo agregar la conexión `chunk_ready` → Diff), tests de Diff en `tests/`,
  `tests/README.md`, `docs/testing.md`, `docs/bugs.md`, `docs/plan.md`, `CHANGELOG.md`,
  `docs/architecture/overview.md` (diagrama de flujo), esta tarjeta.
- **No puede editar:** `services/range_diff.py` salvo que sea imprescindible (justifícalo),
  `views/main_window.py`, Real-Time, Plot y Timezone (F1-07 en paralelo), Mux Detection,
  HMI/OCR.

## Decisiones cerradas
- Nuevo slot `RangeDiffViewModel.ingest_live_chunk(df_new)`, conectado a
  `connection_vm.chunk_ready` en `main_window_viewmodel.py` (después de `data_vm.append_df`).
  Si el live está activo: `feed_live_accumulators(self._live_acc, df_new)`; si no, retorna.
- Se borran `_live_watermark` y `_feed_live_from_watermark`. `set_dataframe` solo actualiza
  `_df` (y lo que ya hace aparte del feed).
- La línea base sigue saliendo de `observe_dataframe_bytes(self._df)` en
  `capture_live_baseline`. Límite conocido y aceptado: como `dataframe_changed` sale por lotes
  (QTimer 100 ms) y `chunk_ready` sale al instante, las filas en tránsito en el momento exacto
  de capturar (≤ un flush) no entran ni en la línea base ni en el live. Documéntalo en una
  línea en el docstring de `capture_live_baseline`.
- Un replay o una conexión nueva (`dataframe_replaced`) sigue deteniendo el live como hoy.

## Trabajo
1. `ingest_live_chunk` + borrar el watermark.
2. Cablear `chunk_ready` en `main_window_viewmodel.py`.
3. Actualizar el diagrama de `docs/architecture/overview.md`.

## Pruebas
- Regresión primero (rojo → verde), sin widgets:
  - con live activo, `ingest_live_chunk(chunk)` alimenta los acumuladores con exactamente las
    filas del chunk;
  - un `set_dataframe` con un df re-ordenado (filas viejas intercaladas) **no** alimenta nada;
  - con live inactivo, `ingest_live_chunk` no hace nada;
  - `stop_live` / `reset_dataframe` siguen limpiando el estado live.
- Suite completa en verde.
- `/verify-ui` (el orquestador): replay de un log de Fase 02, Diff Live con línea base y
  cambios detectados en vivo.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` eliminada
- [x] Pruebas y documentación de pruebas actualizadas
- [x] Diagrama de arquitectura actualizado
- [x] `docs/bugs.md`: no existe una entrada F1-05 que actualizar
