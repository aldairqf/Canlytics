# F1-03 — Real-Time solo trabaja con su ventana abierta

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-03-realtime-only-when-open` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 4775fd0

## Problema
Real-Time sigue trabajando aunque su ventana no exista: sus timers corren y acumula entradas
en cada chunk en vivo.

Causa (verificada):
- `viewmodels/real_time_analysis_viewmodel.py:67-78`: `_refresh_timer` (100 ms) y
  `_highlight_expiry_timer` arrancan en `__init__` y nunca se detienen.
- `viewmodels/main_window_viewmodel.py:81` conecta `connection_vm.chunk_ready` →
  `real_time_analysis_vm.ingest_df` para siempre, y `ingest_df` (`:113`) recorre fila por
  fila cada chunk aunque nadie mire.
- `set_enabled` (`:202`) existe y guarda `_enabled`, pero nadie lo llama y nada lo consulta.

## Propiedad
- **Puede editar:** `viewmodels/real_time_analysis_viewmodel.py`,
  `views/realtime_analysis_window_manager.py`, tests de Real-Time en `tests/`,
  `docs/testing.md`, `docs/bugs.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/main_window_viewmodel.py`, `views/main_window.py`,
  `views/realtime_analysis_window.py` (los tocan F1-04 y F1-07), Mux Detection, HMI/OCR.

## Decisiones cerradas
- `set_enabled` es el interruptor:
  - `False` (estado inicial): los dos timers detenidos e `ingest_df` retorna de inmediato sin
    tocar el estado.
  - `True`: limpia el estado con la lógica de `clear()` (una ventana nueva arranca de cero;
    en vivo se llena en menos de 1 s) y arranca los dos timers.
- La conexión `chunk_ready` → `ingest_df` de `main_window_viewmodel.py` **no cambia**; el
  early-return la vuelve gratis.
- El manager llama `set_enabled(True)` en `_create_window` y `set_enabled(False)` en
  `_on_window_destroyed` (override que llama a `super()`). La ventana ya usa
  `WA_DeleteOnClose`, así que `destroyed` llega al cerrar.
- `set_refresh_interval_ms` no debe arrancar el timer si la VM está deshabilitada.

## Trabajo
1. ViewModel: timers sin `start()` en `__init__`; `set_enabled` los arranca o detiene; early
   return en `ingest_df`.
2. Manager: activar y desactivar la VM con el ciclo de vida de la ventana.
3. Tests existentes que llaman `ingest_df` directo: habilitar la VM en su `setUp`.

## Pruebas
- Regresión primero (rojo → verde), sin construir widgets:
  - VM recién creada: timers inactivos, `ingest_df(chunk)` no crea entradas;
  - `set_enabled(True)`: timers activos, `ingest_df` crea entradas;
  - `set_enabled(False)`: timers detenidos, `ingest_df` ya no cambia el estado;
  - re-habilitar arranca con estado limpio.
- Suite completa en verde.
- `/verify-ui` (el orquestador): replay de un log de Fase 02; Real-Time cerrado no acumula
  entradas; al abrirlo se llena; al cerrarlo, los timers se detienen.

## Ajustes de la revisión (orquestador)
- B-33: la ventana desconecta sus slots de la VM en `closeEvent` (antes, `RuntimeError` en
  cada refresco tras cerrarla); el manager tolera el cierre de la app y un constructor fallido.
- Handoff "Confirm in Real-Time": la ventana nueva arranca vacía, así que el alcance pedido
  queda pendiente y se aplica cuando llegan los IDs (`_apply_pending_scope`).
- `CanIdPanelWidget.set_can_ids` usa `merge_checked_can_ids` (movida a `utils/can_id.py`): un
  ID nuevo se marca solo si estaban todos marcados.
- Verificado con replay de `DD422-07/log_5.txt`: cerrado no ingiere ni corre timers; abrir,
  cerrar y reabrir sin tracebacks; los 8 IDs marcados; handoff a 1B2 deja solo 1B2.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica (sin entrada adicional: la causa y la regresión quedan documentadas en esta tarjeta)
