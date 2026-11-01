# F1-02 — Candidate Interpretations no debe borrar resultados en cada flush

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-02-candidate-keep-results` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 3aa5b7a
- **Bug:** B-32 (registrar en `docs/bugs.md`)

## Problema
Con la ventana Candidate Interpretations abierta durante una captura en vivo, los resultados
calculados desaparecen cada ~100 ms.

Causa (verificada):
- `views/candidate_interpretations_window_manager.py:28` conecta
  `data_vm.dataframe_changed` → `vm.set_dataframe` mientras la ventana está abierta.
- `viewmodels/candidate_interpretations_viewmodel.py:139-144`: `set_dataframe` llama a
  `self._clear_results()` en **cada** llamada.
- `dataframe_changed` se emite tanto en un append en vivo como en un reemplazo del log.
  `data_vm.dataframe_replaced` es la señal que distingue el reemplazo; ya la usan
  `analyze_data_vm`, `signal_coverage_vm` y `range_diff_vm` con un `reset_dataframe`.

## Propiedad
- **Puede editar:** `viewmodels/candidate_interpretations_viewmodel.py`,
  `views/candidate_interpretations_window_manager.py`, el test nuevo o existente de Candidate en
  `tests/`, `docs/bugs.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `views/table/*`, `viewmodels/table_model.py` (los toca F1-01 en paralelo),
  la lógica de búsqueda en `services/candidate_interpretations.py` y Mux Detection.

## Decisiones cerradas
- Patrón `set_dataframe` / `reset_dataframe`, igual que `RangeDiffViewModel` y
  `SignalCoverageViewModel`:
  - `set_dataframe(df)`: append. Actualiza `_df`, la lista de IDs y `_checked_ids` (como hoy),
    **sin** `_clear_results()`.
  - `reset_dataframe(df)`: reemplazo (log nuevo, recarga, Clear). Hace lo mismo que el
    `set_dataframe` actual, **con** `_clear_results()`.
- El manager conecta y desconecta **ambas** señales (`dataframe_changed` → `set_dataframe` y
  `dataframe_replaced` → `reset_dataframe`) en `_create_window` / `_on_window_destroyed`. El
  priming inicial al abrir la ventana usa `reset_dataframe`.
- Los demás disparadores de `_clear_results()` (time range, mux, parámetros de búsqueda) no
  cambian.
- Hoy `set_dataframe` recorre el df completo con `_sorted_can_ids(self._effective_df())`. Se
  mantiene así: lo optimiza la Fase 2 (F2-02). No lo toques en esta tarjeta.

## Trabajo
1. Separar `set_dataframe` / `reset_dataframe` en el ViewModel.
2. Cablear en el window manager (conectar y desconectar las dos señales).

## Pruebas
- **Regresión primero (rojo → verde)**, sin construir widgets (ver la nota ⚠️ en
  `docs/testing.md`; un `QObject` ViewModel sí es seguro). Busca un test existente del ViewModel
  de Candidate en `tests/` o crea `tests/test_candidate_interpretations_viewmodel.py`:
  - con resultados ya calculados (puedes inyectar `_items`/el estado que `_clear_results`
    vacía, o correr una búsqueda chica sobre un df sintético), `set_dataframe(df_mas_grande)`
    **no** emite resultados vacíos ni los borra;
  - `reset_dataframe(df)` sí los borra.
- Suite completa en verde.

## Cierre
- [x] CHANGELOG `## Unreleased` (sección "Correcciones", prosa para el usuario)
- [x] borrar la fila F1-02 de `docs/plan.md`
- [x] `docs/bugs.md`: nueva entrada **B-32** (Dónde / Qué / Fix aplicado / Regresión) y agregarla
  a la lista de corregidos

## Notas del orquestador
- La verificación en la app encontró una segunda causa en el mismo flujo: `_set_can_ids` reseteaba la selección de IDs en cada flush. Se corrigió en esta rama con `merge_checked_can_ids` y su test.
- Codex no pudo commitear porque el sandbox no puede escribir en `.git/worktrees/`. Los commits los hizo el orquestador.
