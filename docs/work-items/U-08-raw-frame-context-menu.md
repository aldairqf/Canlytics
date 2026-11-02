# U-08 — Raw-frame context menu

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-08-raw-frame-context-menu` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** b00350c

## Problema
El menú contextual de la tabla aparece sobre líneas decodificadas, pero no sobre la fila cruda
del frame. Desde la tabla principal y Real-Time faltan acciones rápidas para reutilizar ese frame.

## Propiedad
- **Puede editar:** `views/table/table_view.py`, `views/table/frame_context_menu.py`, `views/main_window.py`, `views/realtime_analysis_window_manager.py`, `config/ui_text.py`, `tests/test_frame_context_menu.py`, `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/`, `services/`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- El menú contextual de la fila cruda ofrece copiar CAN ID, copiar frame como `ID#DATA`, plotear cada byte presente y abrir el ID en Candidate.
- El menú se comparte entre la tabla principal y Real-Time.
- El menú existente para una línea decodificada conserva su comportamiento.
- Plot byte N crea una señal de 8 bits en el offset correspondiente, con selector exacto para el CAN ID.

## Trabajo
1. Agregar una señal para contexto de fila cruda sin desplazar la acción de líneas decodificadas.
2. Implementar un único menú reutilizable con las cuatro acciones.
3. Conectar las dos tablas a PlotWindowManager y CandidateInterpretationsWindowManager.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: mostrar el menú en ambas tablas; comprobar copy ID/frame, plot de byte y handoff a Candidate.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1027 tests
- [x] UI verificada: menú en ambas tablas, copy ID/frame, plot byte y Candidate
