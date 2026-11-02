# F2-05 — Matrix Live incremental

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `perf/f2-05-matrix-live-delta` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02
- **Base commit:** 3ec4019

## Problema
Matrix Live volvía a filtrar `_df` por cada CAN ID plano en cada chunk. El costo de reevaluar esos
IDs crecía con la duración de la captura.

## Propiedad
- **Puede editar:** `services/analyze_data.py`, `viewmodels/analyze_data_viewmodel.py`,
  `tests/test_analyze_data.py`, `tests/test_analyze_data_viewmodel.py`, `tests/README.md`,
  `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otros servicios/ViewModels/vistas, `scripts/`, lógica de Mux Detection,
  HMI/OCR.

## Decisiones cerradas
- Mantener el último timestamp y los últimos valores de byte por ID en un tracker Qt-free.
- En cada chunk, comparar únicamente las filas nuevas con ese estado; reportar IDs nuevos,
  IDs que empezaron a moverse y chunks fuera de orden.
- Materializar la serie histórica completa de un ID solo al aparecer o al pasar de plano a móvil.
  Los IDs planos ya vistos no vuelven a filtrar `_df` mientras no cambie su estado.
- Un reemplazo/desordenamiento invalida la matriz y el tracker; el siguiente build completo vuelve
  a sembrar el estado.

## Trabajo
1. Añadir tracker incremental y pruebas de movimiento, bytes ausentes y timestamps fuera de orden.
2. Integrarlo con `ingest_raw_chunk()` y posponer la materialización hasta actualizar el DataFrame.
3. Añadir regresión que pruebe que los IDs planos no llaman al filtro histórico por cada chunk.
4. Verificar Matrix Live en la app con replay.

## Pruebas
- El tracker incremental detecta los mismos cambios que el recorrido completo.
- Chunks planos repetidos no llaman a `build_matrix_entries_for_id`.
- Al empezar a moverse, el ID se agrega/actualiza con su serie histórica y queda en la matriz.
- Suite completa verde y `/verify-ui` con replay.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
- [x] Suite completa y verificación UI con replay

## Evidencia
- Suite completa: 989 tests, todos pasan.
- Replay de `candump-sample.log`: 1150 frames; Matrix muestra 184 celdas con Live activado.
- Captura revisada fuera del repo: `scratchpad/verify/f205/f205-matrix-live.png`.
- Revisiones `code-reviewer` y `qt-mvvm-reviewer`: ship, sin hallazgos.
