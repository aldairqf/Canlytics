# F1-08 — "Confirm in Real-Time" sin captura en vivo

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-08-confirm-realtime-offline` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F1-03 (ya en `dev`)
- **Base commit:** 46cadbf

## Problema
Con un log cargado offline, el menú contextual de Candidate Interpretations ofrece
"Confirm in Real-Time Analysis...". La acción abre Real-Time vacío, porque Real-Time solo se
alimenta de `connection_vm.chunk_ready` (captura o replay en curso).

Contexto (verificado):
- `views/candidate_interpretations_window.py:~1078`: `confirm_action = menu.addAction(get_text("candidate_confirm_in_realtime"))`
  siempre habilitada si hay `_real_time_analysis_manager`; `:~1086` llama a
  `open_window_for_can_id`.
- El ribbon ya resuelve lo mismo para su botón: `views/main_window.py:208` conecta
  `connection_vm.running_changed` → `self._ribbon.set_real_time_analysis_enabled`.
- `views/realtime_analysis_window_manager.py` se construye en `views/main_window.py` (~línea 84).

## Propiedad
- **Puede editar:** `views/realtime_analysis_window_manager.py`,
  `views/candidate_interpretations_window.py` (solo el menú contextual de esta acción),
  `views/main_window.py` (solo la construcción de `RealTimeAnalysisWindowManager`),
  `config/ui_text.py` (strings nuevos), tests en `tests/`, `tests/README.md`,
  `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** la lógica de búsqueda de Candidate (`services/candidate_*`), su
  ViewModel, Mux Detection, HMI/OCR.

## Decisiones cerradas
- `RealTimeAnalysisWindowManager` recibe `is_live: Callable[[], bool]` (en `main_window.py`:
  `lambda: self.vm.connection_vm.running`) y expone `is_live() -> bool`.
- En Candidate, si `not manager.is_live()`, la acción se agrega **deshabilitada** con un texto
  nuevo vía `get_text`, p. ej. `"Confirm in Real-Time Analysis (needs a live capture or replay)"`.
  Con captura en vivo o replay, todo sigue igual.
- No se toca `open_window_for_can_id`: los demás llamadores no cambian.

## Trabajo
1. `is_live` en el manager y su cableado en `main_window.py`.
2. Acción deshabilitada con texto explicativo en Candidate.

## Pruebas
- Regresión primero (rojo → verde), sin widgets reales: el manager devuelve lo que diga
  `is_live` (con la ventana parcheada como en `tests/test_realtime_analysis_window_manager.py`).
  Si puedes extraer la decisión del menú a una función pura (p. ej.
  `confirm_in_realtime_state(is_live) -> (enabled, text_key)`), pruébala.
- Suite completa en verde.
- `/verify-ui` (el orquestador): log de Fase 02 cargado offline → acción deshabilitada con el
  texto; durante un replay → habilitada y abre Real-Time acotado al ID.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica
