# F2-06 — Derivados incrementales en Plot

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `perf/f2-06-plot-derived-incremental` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02
- **Base commit:** 18e2a45

## Problema
`PlotViewModel.ingest_raw_chunk()` extiende los decodes crudos, pero cada redibujado vuelve a
evaluar todas las fórmulas derivadas sobre el DataFrame completo. Esto hace que el costo crezca con
la captura; `services/signal_aligner.py::align()` vuelve a unir toda la historia para fórmulas que
alinean señales. El plan limita esta tarjeta a derivados y `align_incremental`; la guía de diseño
archivada está en `docs/archive/claude-md-2026-07.md`, § “Real-time plot — Incremental update”.

## Propiedad
- **Puede editar:** `services/signal_aligner.py`, `services/formula_context.py`,
  `viewmodels/plot_viewmodel.py`, `views/plot/plot_window_manager.py`,
  `tests/test_signal_aligner.py`, `tests/test_plot_incremental.py`, `tests/README.md`,
  `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otras vistas, `scripts/`, lógica de Mux Detection, HMI/OCR.

## Decisiones cerradas
- Los derivados procesan los datos nuevos desde `chunk_ready`; nunca usan un watermark por filas
  del DataFrame acumulado.
- `align_incremental()` recibe los pares (TS, valor) del delta y el último valor conocido de cada
  entrada; produce el eje unión del delta y replica el forward-fill de `align()`.
- Reemplazar el DataFrame o cambiar una configuración que afecta la fórmula invalida el estado
  incremental y fuerza una única reconstrucción completa.
- `get_plot_data()` sigue siendo la lectura autoritativa completa para cursores y exportación.
- Las fórmulas con operaciones históricas, control de flujo, metadatos dependientes del tamaño,
  slicing, loops o ensamblado BAM conservan el recorrido completo. La ruta incremental cubre
  operaciones puntuales sobre `signal()`, `raw_bits()`, `raw_extract()` y `raw_frames()`.

## Trabajo
1. Añadir y caracterizar `align_incremental()` contra el sufijo de `align()` para splits y bordes.
2. Mantener por derivado su resultado acumulado y el estado de alineación; evaluar solo cada chunk.
3. Mantener un fallback seguro para fórmulas cuyo resultado no puede establecerse de manera
   incremental, invalidándolo al reemplazar el log.
4. Verificar en la app con replay que los datos derivados continúan y el viewport se conserva con
   Auto-scroll apagado.

## Pruebas
- Para varios puntos de corte, concatenar el resultado incremental debe ser idéntico a evaluar la
  fórmula completa (incluidos inputs intercalados y timestamps coincidentes).
- Chunks vacíos, cambios de fórmula y reemplazo del DataFrame no deben duplicar ni perder puntos.
- Suite completa verde.
- `/verify-ui`: replay con al menos un derivado sin `align()` y otro que alinee dos señales; captura
  después de varios chunks.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
- [x] Suite completa y verificación UI

## Evidencia
- Suite completa: 1002 tests, todos pasan.
- Replay de `candump-sample.log`: 2300 frames; se ven 4 series, incluidas las 2 derivadas.
- El viewport se mantuvo en `(1779067274.373376, 1779067274.873376)` con Auto-scroll apagado.
- Captura revisada fuera del repo: `scratchpad/verify/f206/f206-derived-live.png`.
- Revisiones `code-reviewer` y `qt-mvvm-reviewer`: ship, sin hallazgos pendientes.
