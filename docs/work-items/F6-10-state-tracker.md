# F6-10 — State Tracker de bits

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-10-state-tracker` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F6-01, F2-06, F6-05
- **Base commit:** `eff9a3f`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Candidate y Bit Activity encuentran candidatos, pero no muestran su estado como una secuencia de barras alineada con el tiempo. Para validar una hipótesis de bit durante un movimiento, el usuario necesita ver dónde cambia 0↔1 y seguir el mismo instante con el cursor global.

## Propiedad

- **Puede editar:** models/bit_track.py, `services/state_tracker.py`, nuevo `viewmodels/state_tracker_viewmodel.py`, `views/plot/plot_window.py`, `views/plot/plot_window_manager.py`, `views/plot/plot_ribbon.py`, diálogo de selección de bit bajo `views/plot/`, `config/ui_text.py`, pruebas de state tracker/plot/cursor, `CHANGELOG.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** parser/esquema CAN, taxonomía F3-05, DBC/Mux Detection, HMI/OCR, `PlotRenderer` salvo una necesidad confirmada por el smoke visual.

## Decisiones cerradas

- Esta entrega crea carriles para bits crudos de CAN (ID, byte, bit). No requiere DBC; una sola hipótesis de bit se puede validar directamente con cualquier log.
- Cada carril muestra estados 0/1 como bandas de tiempo, y se pueden añadir varios carriles al mismo plot.
- El carril comparte el eje temporal X del Plot y el cursor global; arrastrar sobre el carril también mueve el cursor compartido.
- Los cambios se calculan sobre el log inicial una vez y después sobre `rows_appended` por chunk. Un reemplazo de fuente reconstruye los carriles; nunca se recalcula toda la historia por flush.
- Frames sin el byte seleccionado no cuentan como estado y no alteran el último valor observado.

## Trabajo

1. Implementar el acumulador Qt-free de cambios 0/1 para un ID/byte/bit, con igualdad batch/incremental.
2. Añadir al Plot un control para agregar carriles y una vista de bandas alineada al eje X.
3. Sincronizar el cursor global en ambos sentidos, incluyendo el eje de tiempo normalizado de Plot.
4. Conectar altas de chunks y reemplazos al ciclo de vida del Plot abierto.
5. Verificar varios carriles, cambios de fuente y cursor con capturas.

## Pruebas

- Servicio: bytes ausentes, estado repetido, transiciones, timestamps empatados y batch == incremental.
- ViewModel: consume solo chunks crudos, limpia/reconstruye al reemplazar fuente y no duplica transiciones.
- Suite completa y smoke UI con dos bits distintos y cursor sincronizado.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica cambio
- [x] Suite completa: 1302 tests
- [x] Revisión de código y MVVM
- [x] Smoke UI y capturas revisadas
