# F3-02 — Diff → Candidate con contexto

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-02-diff-to-candidate`
- **Implementa:** Codex
- **Depende de:** F3-01
- **Base commit:** `63f22ce`

## Problema
`views/range_diff_window.py::_open_plot_context_menu` actualmente abre Candidate solo con el CAN ID. Se pierden el byte seleccionado y los rangos A/B del reporte.

## Propiedad
- **Puede editar:** `services/candidate_interpretations.py`, `viewmodels/candidate_interpretations_viewmodel.py`, `views/main_window.py`, `views/range_diff_window.py`, `views/range_diff_window_manager.py`, `views/candidate_interpretations_window_manager.py`, tests de Candidate/Range Diff/contexto, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, otros work-items de Fase 3.

## Decisiones cerradas
- Candidate recibe los rangos A y B como unión de ventanas inclusivas, sin analizar los frames entre rangos.
- La búsqueda se restringe a señales cuyas posiciones de bit caen dentro de los bytes seleccionados en Diff.
- El contexto se conserva en `AnalysisContextViewModel`; la búsqueda concreta vive en `services/candidate_interpretations.py`.

## Trabajo
1. Al elegir «Analyze as signal» en una fila de byte, publicar `AnalysisContext` con ID, byte, A/B y origen.
2. Abrir Candidate con el ID marcado, buscar únicamente dentro de ambos rangos y limitar los candidatos a los bytes elegidos; cancelar workers previos y descartar sus resultados viejos al cambiar el contexto.
3. Añadir regresiones para la unión A/B (sin filas del hueco intermedio), límites de bytes/endianness y workers obsoletos.
4. Cerrar tarjeta, plan, CHANGELOG, mapa de pruebas y arquitectura si aplica.

## Pruebas
- Regresión primero: el buscador incluye los dos rangos, excluye el hueco y solo produce bits en los bytes elegidos.
- Suite completa verde.
- `/verify-ui`: Diff → clic derecho en byte → Analyze as signal; Candidate queda acotado al ID/contexto.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite y verificación de UI
