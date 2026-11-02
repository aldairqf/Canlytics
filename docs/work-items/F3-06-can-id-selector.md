# F3-06 - Selector común de CAN ID y búsqueda global

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-06-can-id-selector` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01, F3-04, F3-05
- **Base commit:** `37f80ce`

## Problema
La revisión funcional identifica cuatro selectores distintos. `CanIdPanelWidget` ya se usa en la tabla principal y Real-Time, pero Analyze y Candidate aún mantienen listas con búsqueda y selección propias (`views/analyze_data_window.py`, `views/candidate_interpretations_window.py`). No existe una búsqueda global que lleve un CAN ID a la tabla principal.

## Propiedad
- **Puede editar:** `views/widgets/can_id_panel.py`, nuevo diálogo reutilizable de salto a CAN ID, `views/main_window.py`, `views/analyze_data_window.py`, `views/analyze_data_window_manager.py`, `views/candidate_interpretations_window.py`, `views/candidate_interpretations_window_manager.py`, `viewmodels/data_viewmodel.py`, pruebas UI/managers relacionadas, `scripts/verify_can_id_jump.py`, `config/ui_text.py`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, algoritmos de clasificación de CAN ID, servicios de análisis, F3-07.

## Decisiones cerradas
- Reutilizar `CanIdPanelWidget` en Main, Real-Time, Analyze y Candidate; conservar los controles de interpretación solo donde ya aplican.
- Analyze mantiene un CAN ID activo; Candidate conserva su selección múltiple y el handoff de contexto.
- Ctrl+F abre una búsqueda sobre los CAN ID del log y navega al primer frame de ese ID en la tabla principal, conservando el resto de la selección de IDs.
- Si el rango temporal actual oculta todos los frames del ID, Ctrl+F limpia ese rango para que el salto tenga un resultado visible.
- La búsqueda ignora mayúsculas/minúsculas y acepta prefijo hex con `0x`.
- No persistir estado nuevo ni alterar formato de CAN ID del modelo.

## Trabajo
1. Adaptar `CanIdPanelWidget` para ser opcionalmente solo selector y emitir activación de ID sin duplicar controles.
2. Migrar Analyze y Candidate al panel; conservar selección, filtros y handoffs actuales.
3. Añadir diálogo de salto invocado por Ctrl+F con selección entre IDs disponibles y navegación a la fila del primer frame.
4. Cubrir búsqueda vacía/ID inexistente, selección, alcance de Candidate y preservación de Analyze.

## Pruebas
- Regresión de handoff a Candidate, selección de Analyze y filtros de tabla.
- QTest para activación del shortcut y navegación a la fila correcta.
- Suite completa en verde y capturas revisadas para Main, Analyze y Candidate.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa: 1087 tests aprobados.
- [x] QTest directo: Ctrl+F abre la búsqueda, limpia un rango que excluye el ID, conserva los IDs seleccionados y selecciona la primera fila.
- [x] Verificación UI: Main, diálogo Ctrl+F, salto a la fila, Analyze y Candidate capturados y revisados.
