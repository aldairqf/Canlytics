# F6-01 — Actividad de bits y heatmap

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-01-bit-activity` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-05, F2-02
- **Base commit:** `6300148`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md), [READ (IEEE TIFS)](https://doi.org/10.1109/TIFS.2018.2870826)

## Problema

El usuario necesita descubrir qué bits de cada ID se mueven y dónde pueden empezar/terminar
señales cuando no hay DBC. El análisis debe resumir cambios entre tramas consecutivas sin
retener el log ni recalcular la historia en cada chunk.

## Propiedad

- **Puede editar:** `services/bit_activity.py`, `viewmodels/bit_activity_viewmodel.py`,
  `viewmodels/main_window_viewmodel.py`, `viewmodels/bit_activity_worker.py`, `views/bit_activity_window.py`,
  `views/bit_activity_window_manager.py`, `views/main_window.py`, `views/menu/main_menu_factory.py`,
  `views/widgets/ribbon_bar.py`, `config/ui_text.py`, `config/defaults.py`,
  `tests/test_bit_activity.py`, pruebas de composición/UI relacionadas, `docs/plan.md`,
  `docs/testing.md`, `tests/README.md`, `docs/ui-design.md`,
  `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/range_diff.py`, lógicas de Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas

- Bits `0..63` numerados little-endian dentro del payload: bit 0 es el menos significativo de D0.
- READ es una heurística exploratoria; límites y clases son sugerencias, no decodificaciones
  confirmadas. La vista muestra la cantidad de muestras.
- La tasa se calcula por bit con los pares de tramas que realmente contienen ese bit. Tramas
  consecutivas de longitudes distintas solo se comparan en los bits compartidos.
- El acumulador conserva contadores de flips, último payload y 256 bins por byte; nunca guarda
  la secuencia de frames. Los chunks normales actualizan solo los IDs afectados.
- Una reconstrucción completa ocurre al abrir el análisis o reemplazar/reordenar el DataFrame; se
  ejecuta en worker. Los deltas que llegan durante el worker se aplican después del snapshot.
- La matriz presenta tasa de flip, los segmentos muestran clase y límites sugeridos, y el panel
  del byte seleccionado muestra el histograma de valores observados. El segmento seleccionado se
  envía mediante `AnalysisContext` al menú común, incluido Working DBC para guardarlo como señal.

## Trabajo

1. Implementar un acumulador Qt-free incremental para tasas de flip, magnitud logarítmica, límites
   preliminares READ, heurísticas de counter/CRC/constante/física e histogramas por byte.
2. Añadir ViewModel con reconstrucción en worker y consumo incremental de `rows_appended`.
3. Añadir heatmap ID × bit con selección de segmento/byte, resumen de muestras y acceso desde Tools
   y el ribbon; respetar ambos temas.

## Pruebas

- Regresiones Qt-free para flips en cortes de chunk, IDs independientes, DLC variable, magnitud,
  límites/clases, histogramas, entradas vacías y equivalencia incremental/full.
- Suite completa en verde.
- `/verify-ui`: abrir Bit Activity en Dark y Light, comprobar ejes/color, filtrar/seleccionar ID,
  consultar segmento e histograma, y confirmar actualización tras nuevos frames.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa, revisión code-reviewer y qt-mvvm-reviewer
- [x] Capturas de UI revisadas
