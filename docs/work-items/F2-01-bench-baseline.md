# F2-01 — Benchmark de línea base del streaming

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `perf/f2-01-bench-baseline` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 807f3a3

## Problema
La Fase 2 (ADR 001) promete costo por flush plano a medida que crece el log. Hoy
`scripts/bench_stream.py` solo mide `merge_frames`, `sorted_can_ids` e
`IncrementalTableFilter`: línea base 4.3 → 30.2 ms/flush entre los 5 y los 20 min. Faltan los
consumidores que más pesan en la UI: `TableModel`, Real-Time y Plot.

## Propiedad
- **Puede editar:** `scripts/bench_stream.py`, `docs/plan.md`, `CHANGELOG.md` (sección
  `### Interno`), `docs/architecture/overview.md` (tabla o nota de rendimiento, si existe),
  esta tarjeta.
- **No puede editar:** nada en `services/`, `viewmodels/`, `views/` (solo se mide, no se
  optimiza), `tests/`. D-01 corre en paralelo.

## Decisiones cerradas
- El bench sigue siendo un script sin ventana: `TableModel` y `RealTimeAnalysisViewModel` son
  `QObject`/`QAbstractTableModel`; créalos con un `QCoreApplication`/`QApplication` offscreen
  (`QT_QPA_PLATFORM=offscreen`) sin mostrar widgets.
- Etapas nuevas a medir por flush, cada una con su columna en el reporte:
  - `TableModel`: el camino real que recorre un flush hasta la tabla principal (filtro →
    `table_vm.set_dataframe` o el método que use hoy el pipeline; léelo en
    `viewmodels/main_window_viewmodel.py` y `viewmodels/table_viewmodel.py`).
  - Real-Time: `RealTimeAnalysisViewModel.ingest_df(chunk)` con `set_enabled(True)` + el costo
    de su refresco (`_emit_if_dirty`/`_emit_current_view`) una vez por flush.
  - Plot: el camino por flush de un `PlotViewModel` con 4 señales sobre IDs del tráfico
    (`set_dataframe` + `ingest_raw_chunk`, lo que use hoy `PlotWindowManager`).
- Perfil por defecto: 900 fps, 40 IDs (tráfico real de Fase 02). Opción `--minutes` como hoy.
- Reporte: tabla por checkpoint (min 5, 10, 20, …) con ms/flush promedio por etapa y total.
- Meta de la Fase 2 (documentarla en el docstring): costo total plano < 5 ms/flush.

## Trabajo
1. Agregar las tres etapas al bench.
2. Correr `--minutes 10` y anotar la línea base en la tarjeta (tabla) y en `docs/plan.md`
   (texto de F2-01 → borrar la fila y dejar la línea base en el texto de la Fase 2).

## Pruebas
- El script corre sin errores con `--minutes 2 --report-every 1` (smoke).
- Suite completa en verde (no debería cambiar nada).

## Línea base medida

Perfil: 900 fps, 40 IDs, 90 filas/flush. Tiempo promedio por flush en cada intervalo de un
minuto; la etapa `Plot` mide `ingest_raw_chunk` y actualización del DataFrame acumulado.

| Min | Filas | Merge | Emit IDs | Analyze IDs | Filtro | TableModel | Real-Time | Plot | Total |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 54,000 | 0.19 | 0.57 | 0.55 | 1.18 | 6.76 | 1.72 | 4.88 | 15.84 |
| 2 | 108,000 | 0.19 | 0.88 | 0.88 | 1.90 | 12.81 | 1.52 | 4.39 | 22.56 |
| 3 | 162,000 | 0.18 | 0.97 | 0.94 | 2.24 | 16.40 | 1.09 | 3.65 | 25.47 |
| 4 | 216,000 | 0.33 | 3.66 | 3.72 | 5.88 | 45.11 | 2.56 | 6.07 | 67.34 |
| 5 | 270,000 | 0.35 | 5.05 | 4.73 | 8.20 | 64.81 | 2.77 | 6.49 | 92.39 |
| 6 | 324,000 | 0.34 | 4.66 | 4.46 | 8.84 | 69.33 | 2.17 | 5.78 | 95.58 |
| 7 | 378,000 | 0.34 | 3.02 | 3.11 | 7.78 | 62.33 | 1.42 | 4.59 | 82.58 |
| 8 | 432,000 | 0.27 | 2.83 | 2.78 | 7.02 | 59.74 | 1.23 | 3.97 | 77.85 |
| 9 | 486,000 | 0.31 | 3.25 | 3.23 | 8.37 | 69.62 | 1.22 | 4.05 | 90.05 |
| 10 | 540,000 | 0.39 | 5.67 | 5.61 | 12.63 | 109.19 | 1.69 | 4.99 | 140.16 |

Todos los tiempos están en ms/flush. `TableModel` domina el costo; queda evidencia de una
línea base por encima de la meta de Fase 2 (<5 ms/flush).

## Cierre
- [x] CHANGELOG `## Unreleased` (`### Interno`)
- [x] fila de `docs/plan.md` retirada y resultado conservado en la Fase 2
