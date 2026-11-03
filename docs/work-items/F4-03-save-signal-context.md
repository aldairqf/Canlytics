# F4-03 — Guardar como señal desde el contexto

- **Estado:** Hecho
- **Fase:** 4 de `docs/plan.md`
- **Rama:** `feature/f4-03-save-signal-context` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01 a F3-07, F4-01, F4-02
- **Base commit:** `d9c3408`
- **ADR:** [003](../architecture/decisions/003-working-dbc.md), [004](../architecture/decisions/004-analysis-context.md)

## Problema

Candidate, Diff, Analyze, Plot y la tabla ya conservan o producen el contexto de la señal,
pero Working DBC aún no es un destino utilizable desde esas herramientas. ADR 003 define
guardar la interpretación desde ese contexto; `analysis_send_destinations()` todavía deshabilita
Working DBC y los menús de Diff/tabla no ofrecen esa acción.

## Propiedad

- **Puede editar:** `views/plot/add_to_plot_menu.py`, `views/main_window.py`,
  `views/range_diff_window.py`, `views/range_diff_window_manager.py`,
  `views/plot/plot_window_manager.py`, `views/table/frame_context_menu.py`,
  `views/widgets/save_signal_dialog.py`,
  `viewmodels/main_window_viewmodel.py`, `models/analysis_context.py`, `config/ui_text.py`,
  `tests/test_analysis_context.py`, `tests/test_working_dbc_persistence.py`,
  `tests/test_frame_context_menu.py`,
  `scripts/verify_f403_save_signal.py`, `docs/architecture/overview.md`,
  `docs/ui-design.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** servicios DBC, MCP, `DbcManager`, `services/`, cambios a la detección,
  Mux Detection, HMI/OCR, otras tarjetas F4.

## Decisiones cerradas

- Reusar `AnalysisContext` como evidencia de origen; no crear un segundo formato de handoff.
- El menú Working DBC abre un diálogo común desde Candidate, Diff, Analyze, Plot y la tabla.
- Prellenar CAN ID y cualquier byte/bit/rango/mux que aporte el contexto; dejar editables los
  campos de la señal y validar al guardar con el servicio existente.
- Las vistas solo presentan el diálogo y solicitan la operación a `MainWindowViewModel`; no
  llaman al servicio DBC.
- Guardar copia primero el mensaje externo completo si hace falta y mantiene sus señales; la
  persistencia y el refresco de decode usan el flujo F4-02.

## Trabajo

1. Habilitar Working DBC en los menús compartidos de análisis y conectarlo al diálogo común.
2. Añadir las acciones a los menús de contexto de Diff y de la tabla principal.
3. Crear el diálogo con campos prellenados y edición de parámetros estándar de señal.
4. Cablear guardado validado, feedback de error/éxito y persistencia sin llamadas de vista a servicios.
5. Cubrir el contexto y wiring que puede probarse sin widgets en `unittest`; verificar los cinco
   orígenes en la app y revisar capturas.

## Pruebas

- Regresión de handoff: ID, geometría de bits, endianess, rango y mux conservados donde existan.
- Suite completa verde; DBC/log fixtures solo lectura.
- `/verify-ui`: abrir Guardar como señal desde Candidate, Diff, Analyze, Plot y tabla; verificar
  prefills, edición, validación y confirmación de persistencia en Working DBC con capturas.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde (1124 tests)
- [x] Capturas de los cinco orígenes revisadas
