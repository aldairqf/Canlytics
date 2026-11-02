# U-01 — Ergonomía de Real-Time

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-01-realtime-ergonomics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 1b0e079

## Problema
Real-Time oculta Delta T y mantiene Refresh Interval y Highlight Hold en la fila principal de controles, junto al estado.

## Propiedad
- **Puede editar:** `views/realtime_analysis_window.py`, `config/ui_text.py`, `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/real_time_analysis_viewmodel.py`, `views/main_window.py`, `views/realtime_analysis_window_manager.py`, lógica de Mux Detection, HMI/OCR.

## Decisiones cerradas
- Mostrar la columna Delta T; Bus continúa oculta.
- Mover Refresh Interval y Highlight Hold a un menú desplegable «Options» con controles editables.
- Mantener el estado visible en la barra de estado propia de Real-Time.

## Trabajo
1. Mostrar Delta T en la tabla.
2. Mover los dos ajustes a Options sin cambiar sus valores ni señales.
3. Mover el indicador de estado a la barra inferior de la ventana.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: abrir Real-Time, comprobar Delta T, abrir Options y cambiar ambos intervalos; revisar el estado en la barra inferior.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`
