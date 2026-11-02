# F3-05 - Taxonomía común de cambios

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-05-change-taxonomy` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-04
- **Base commit:** `f22388a`

## Problema
La revisión funcional enumera cinco implementaciones de "qué cambió": `services/range_diff.py::classify_byte`, Real-Time frame a frame, `services/analyze_data.py` con diferencias de secuencia, Signal Coverage con `unique_count >= 2` y Candidate con `classify_signal_type`. La taxonomía pública de Diff ya existe, pero esos consumidores no comparten una observación base.

## Propiedad
- **Puede editar:** `services/range_diff.py`, `services/realtime_analysis.py`, `services/analyze_data.py`, `services/signal_coverage.py`, `services/candidate_interpretations.py`, pruebas de esos servicios, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** vistas/ViewModels, algoritmo de Mux Detection, HMI/OCR, esquemas públicos ni comportamiento visible; F3-06/F3-07.

## Decisiones cerradas
- `services/range_diff.py` es el módulo canónico para observaciones y clasificación de cambios.
- Mantener los cinco valores existentes de `ChangeType` y la semántica de Diff.
- Las métricas (conteo, valores distintos, movimiento) y la clase de comparación son facetas de una observación; no convertirlas en una categoría exclusiva si no hay evidencia suficiente.
- Las categorías de señal de Candidate (`COUNTER`, `BINARY`, etc.) conservan su significado.
- Preservar resultados: igualdad exacta de bytes, igualdad numérica y tolerancia actual de Candidate.
- No recorrer el DataFrame acumulado por flush; conservar las rutas O(chunk).

## Trabajo
1. Añadir una observación compartida de secuencia en `range_diff.py` que exponga cambios consecutivos, cardinalidad y movimiento; conservar la detección de contador de bytes.
2. Hacer que las cinco lógicas deleguen sus predicados de cambio a esa observación sin cambiar las salidas existentes.
3. Mantener el estado entre chunks donde el consumidor sea incremental y cubrir cortes arbitrarios.
4. Añadir regresiones de equivalencia para secuencias byte y numéricas, datos vacíos/constantes, tolerancias, cambios en límite de chunk y Candidate.

## Pruebas
- Caracterizar igualdad, transición, repetición, orden de captura y límites entre chunks.
- Suite completa: 1083 tests en verde.
- Verificar que la carga incremental no introduce un recorrido del DataFrame acumulado.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa (1083 tests), revisión de código y revisión MVVM
