# F3-01 — Contexto de análisis y menú común «Enviar a…»

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-01-analysis-context`
- **Implementa:** Codex
- **Depende de:** M-01
- **Base commit:** `8d2922b`

## Problema
Las ventanas no comparten un objeto para transportar la evidencia. ADR 004 define los datos necesarios y el composition root que debe conservar el contexto. El menú actual `views/plot/add_to_plot_menu.py::show_add_to_plot_menu` solo enruta señales al plot.

## Propiedad
- **Puede editar:** `config/ui_text.py`, `models/analysis_context.py`, `viewmodels/analysis_context_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `views/main_window.py`, `views/plot/add_to_plot_menu.py`, `views/plot/plot_window_manager.py`, `views/signal_coverage_window.py`, `views/signal_coverage_window_manager.py`, `views/candidate_interpretations_window.py`, `views/candidate_interpretations_window_manager.py`, pruebas relacionadas, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, contratos de streaming, funcionalidades específicas de F3-02 en adelante.

## Decisiones cerradas
- `AnalysisContext` permanece libre de Qt y representa ID, bytes/bits, rango o rangos A/B, mux y origen.
- `AnalysisContextViewModel` es el estado compartido del composition root.
- El menú de plot se convierte en una entrada del menú común; otros destinos pueden registrarse sin acoplar las vistas a sus managers.

## Trabajo
1. Añadir modelo validado y Qt-free y ViewModel compartido con señal para publicar contexto/destino.
2. Reemplazar el helper de «agregar al plot» por el menú común. Candidate, Diff, Analyze y Real-Time enrutan el contexto; Real-Time requiere captura o replay activo y Working DBC queda deshabilitado hasta que exista su editor.
3. Migrar los puntos actuales de envío al plot y Candidate al menú común. Añadir pruebas de modelo, estado, dispatch y conversión de señal a contexto.
4. Documentar el routing y sus límites en la arquitectura.

## Pruebas
- Regresión: construcción, copia/actualización de contexto y menú dispatch con destinos opcionales.
- Suite completa verde.
- `/verify-ui`: menú contextual de una señal y envío a plot.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica
