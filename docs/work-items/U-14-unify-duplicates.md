# U-14 — Unificar funciones duplicadas

- **Estado:** Hecho
- **Fase:** U2 de `docs/plan.md`
- **Rama:** `feature/u-14-unify-duplicates` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** U-10, U-13
- **Base commit:** `901082f`

## Problema
La revisión funcional 2 confirmó dos vistas XY, dos transportes que mueven el mismo cursor, dos matrices para explorar cambios y dos fuentes para nombrar señales. Candidate empieza buscando solo señales de 8 bits. Evidencia: [revisión funcional §5](../review/2026-11-functional-review-2.md#5-funciones-duplicadas-pedido-principal), y hallazgo R-07 para Tag.

## Propiedad
- **Puede editar:** `views/plot/`, `views/candidate_interpretations_window.py`, sus managers, `views/analyze_data_window.py`, `viewmodels/analyze_data_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `services/candidate_tag_migration.py`, `services/session_state.py`, `config/defaults.py`, `config/ui_text.py`, pruebas focalizadas y docs de U-14.
- **No puede editar:** Mux Detection, HMI/OCR, logs de campo, ni los worktrees hermanos.

## Decisiones cerradas
- XY vive solo como modo integrado de Plot y conserva rango temporal, snapshot, refresh y exportación de puntos alineados.
- Tag abre el mismo flujo de «Save as signal» y guarda en Working DBC. `signal_tags.json` se lee solo para una migración única; no se elimina.
- Analyze Matrix es la única matriz; Candidate abre esa vista con el CAN ID actual o los CAN IDs seleccionados y excluye bytes planos por defecto.
- Max Length predeterminado es 16; Min Length y preferencias existentes se conservan.
- Plot y Real-Time deben compartir un único ViewModel de reproducción ligado al cursor global.

## Trabajo
1. [x] Retirar XYWindow y conservar XYPlotWidget como modo XY del Plot.
2. [x] Guardar Candidate Tag en Working DBC, reconocer la señal guardada y migrar una vez los tags legados.
3. [x] Unificar PlaybackBar y el transporte offline con un ViewModel compartido ligado al cursor global.
4. [x] Sustituir la matriz de Candidate por el acceso filtrado a Analyze Matrix, con bytes planos ocultos inicialmente.
5. [x] Establecer Max Length en 16 desde `config/defaults.py`.

## Pruebas
- Regresiones focalizadas: `test_u14_duplicate_features.py` y filtro de Matrix en `test_analyze_data_viewmodel.py`.
- Suite completa: 1,536 tests en 115 módulos, todos en verde.
- Verificación offscreen: XY muestra el modo integrado y Candidate muestra el acceso a Analyze Matrix. El backend de fuentes de este entorno dibujó glifos cuadrados; la legibilidad requiere revisar en una sesión gráfica normal.
- `/verify-ui` de reproducción compartida queda pendiente junto con el ítem 3.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] `docs/ui-design.md` actualizado
- [x] `docs/testing.md` y `tests/README.md` actualizados en UTF-8
- [x] Suite ejecutada: 1,536 tests en verde. Verificación offscreen parcial; revisar legibilidad en sesión gráfica normal.
- [ ] Commit `feat(ui): one shared playback tied to the global cursor`
