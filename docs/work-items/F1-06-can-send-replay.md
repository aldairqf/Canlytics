# F1-06 — CAN Send deshabilitado durante un replay

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-06-can-send-replay` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 4775fd0

## Problema
Durante un replay, el botón de enviar de CAN Send está habilitado, pero el envío siempre
falla.

Causa (verificada):
- `viewmodels/can_send_viewmodel.py:38-39`: `send_enabled` devuelve `connection_vm.running`,
  que es `True` también en replay.
- `viewmodels/can_send_viewmodel.py:137-141`: `_on_running_changed` emite `running` tal cual.
- `viewmodels/connection_stream_viewmodel.py:495-496`: `request_send` rechaza el envío en
  modo replay con `send_failed`.

## Propiedad
- **Puede editar:** `viewmodels/can_send_viewmodel.py`,
  `viewmodels/connection_stream_viewmodel.py` (solo agregar una propiedad de lectura),
  `views/can_send_window.py`, `config/ui_text.py` (solo strings nuevos), tests en `tests/`,
  `docs/testing.md`, `docs/bugs.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/main_window_viewmodel.py`, `views/main_window.py`,
  Real-Time y Analyze (tarjetas en paralelo), Mux Detection, HMI/OCR.

## Decisiones cerradas
- `ConnectionStreamViewModel` expone `is_replay: bool` (corriendo y `mode == "replay"`).
- `send_enabled` = `running and not is_replay`. `_on_running_changed` emite ese valor y
  detiene los envíos periódicos cuando queda en `False`.
- La guarda de `request_send` en el modo replay se queda como defensa.
- La ventana muestra por qué está deshabilitado: tooltip o texto de estado con un string
  nuevo vía `get_text()` (p. ej. "Sending is not available while replaying a log.").

## Trabajo
1. Propiedad `is_replay`.
2. `send_enabled` y su señal.
3. Mensaje en la ventana.

## Pruebas
- Regresión primero (rojo → verde), con un `connection_vm` falso (QObject con
  `running_changed`, `send_succeeded`, `send_failed`, `running`, `is_replay`):
  - en replay: `send_enabled` es `False` y la señal emite `False`;
  - en vivo (SSH/Kvaser): `True`;
  - detenido: `False`, y los periódicos se detienen.
- Suite completa en verde.
- `/verify-ui` (el orquestador): con un replay de un log de Fase 02, abrir CAN Send y ver los
  envíos deshabilitados con el mensaje.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica (no aplica)
