# F3-07 - Salidas de Analyze, Constraint Search y Plot

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-07-analysis-outputs` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01 a F3-06
- **Base commit:** `ebc11c7`

## Problema
Analyze Data, Constraint Search y Plot producen evidencia útil, pero no permiten continuar el análisis en las otras herramientas con el contexto seleccionado.

## Propiedad
- **Puede editar:** `views/analyze_data_window.py`, `views/analyze_data_window_manager.py`, `views/candidate_interpretations_window.py`, `views/candidate_constraint_search.py`, `views/plot/plot_window.py`, `views/plot/plot_window_manager.py`, `views/plot/add_to_plot_menu.py` si hace falta, `config/ui_text.py`, pruebas UI/managers relacionadas, `scripts/verify_f307_outputs.py`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** servicios de análisis, lógica de Mux Detection, HMI/OCR, DBC de trabajo, MCP, Fases 6–7.

## Decisiones cerradas
- Reusar `AnalysisContextViewModel` y el menú común "Enviar a…"; no crear rutas paralelas.
- Analyze envía los bytes seleccionados del CAN ID activo a Plot y comparte ID, bytes, rango y caso MUX con los otros destinos.
- Constraint Search envía el candidato seleccionado a Plot y a las herramientas de análisis con su ID y bits.
- Plot envía la señal seleccionada a Candidate, Diff, Analyze y Real-Time; Working DBC permanece deshabilitado.
- Mantener la selección de Analyze y las ventanas A/B ya presentes en Constraint Search.

## Trabajo
1. Añadir una acción visible de salida desde Analyze Data.
2. Permitir enviar un resultado seleccionado de Constraint Search.
3. Añadir destinos de análisis para la señal seleccionada en Plot.
4. Cubrir construcción de contextos y rutas sin abrir nuevas ventanas dentro de `unittest discover`; verificar los flujos visibles con QTest en scripts dirigidos.

## Pruebas
- Regresión de contexto: ID/bytes/bits, rango, mux y origen conservados.
- QTest directo de menús desde Analyze, Constraint Search y Plot.
- Suite completa en verde y capturas de las tres salidas revisadas.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` eliminada
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa: 1087 tests aprobados
- [x] Verificación de las tres rutas UI y capturas revisadas
