# F3-04 — Estado y componente común de rango temporal

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-04-time-range` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01, F3-02, F3-03
- **Base commit:** `13d2f4b`

## Problema
El rango temporal escalar se conserva en ViewModels separados y los filtros de tabla, Analyze, Candidate y Mux Detection pueden divergir. Además, las ventanas mantienen copias locales del texto que escribió el usuario en `TimeFilterWidget`.

## Propiedad
- **Puede editar:** `models/analysis_context.py`, `viewmodels/time_range_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `viewmodels/table_filter_viewmodel.py`, `viewmodels/analyze_data_viewmodel.py`, `viewmodels/candidate_interpretations_viewmodel.py`, `viewmodels/mux_detection_viewmodel.py`, `services/table_filter.py`, `views/main_window.py`, managers/ventanas de Analyze y Candidate, `views/mux_detection_window.py`, `views/settings/time_filter_dialog.py`, `views/widgets/time_filter_widget.py`, pruebas relacionadas, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** algoritmo de Mux Detection, rangos A/B propios de Diff, HMI/OCR, F3-05 u otras tarjetas.

## Decisiones cerradas
- `TimeRangeViewModel` del composition root es la fuente única del rango escalar (límites inclusivos en segundos epoch) y del texto del filtro.
- Main Table, Analyze, Candidate y Mux Detection reciben el mismo rango al cambiarlo desde cualquiera de sus editores.
- El contexto A/B de Diff → Candidate sigue siendo un override puntual de búsqueda; no modifica el rango global.
- Los rangos A/B del comparador Diff siguen siendo propios de esa comparación.
- Se reutiliza `TimeFilterWidget`; no se modifica el algoritmo congelado de Mux Detection.

## Trabajo
1. Crear el ViewModel compartido con estado validado, copia defensiva y señal de cambios.
2. Cablear todos los consumidores desde el composition root y eliminar los rangos escalares duplicados como fuente de verdad.
3. Hacer que Main, Analyze, Candidate y Mux Detection abran el filtro desde el mismo estado; quitar los diccionarios locales duplicados.
4. Aplicar rangos múltiples de contexto al Candidate sin afectar el estado global.
5. Añadir regresiones de propagación, cancelación/invalidation si aplica y filtros inclusivos; actualizar documentación.

## Pruebas
- Regresión primero: al editar el rango desde cada herramienta, todos muestran el mismo estado y filtran los mismos límites inclusivos.
- Regresión: un contexto A/B restringe Candidate a ambas ventanas y no cambia el filtro global.
- Suite completa verde.
- `/verify-ui`: abrir los cuatro editores, cambiar límites y confirmar propagación; probar después el handoff Diff → Candidate.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite (1079 tests) y verificación de UI; capturas revisadas en `%LOCALAPPDATA%/Temp/canlytics-verify-f304-font`
