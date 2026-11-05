# F6-03 - Marcadores de eventos y Diff automático

- **Estado:** Hecho
- **Verificación:** 1228 tests; smoke visual con Ctrl+M, persistencia al reabrir y Diff automático en tema claro y oscuro
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-03-event-markers` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-04
- **Base commit:** `cec9d65`
- **Referencias:** [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Al analizar un equipo no queda una marca durable de cuándo se activó o desactivó una condición. El usuario debe volver a localizar los rangos a mano para comparar la línea base con el evento.

## Propiedad

- **Puede editar:** `services/event_markers.py`, `services/session_state.py`, `viewmodels/event_markers_viewmodel.py`, `viewmodels/analysis_context_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `viewmodels/data_viewmodel.py`, `viewmodels/range_diff_viewmodel.py`, `views/main_window.py`, `views/menu/main_menu_factory.py`, `views/widgets/ribbon_bar.py`, `views/event_markers_window.py`, `views/event_markers_window_manager.py`, `config/ui_text.py`, `tests/test_event_markers.py`, `tests/test_data_viewmodel.py`, `tests/test_range_diff_viewmodel.py`, `tests/test_session_state.py`, `tests/test_analysis_context.py`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR u otros work-items.

## Decisiones cerradas

- Un marcador tiene nombre, estado ON/OFF, timestamp y secuencia; toma el tiempo del frame seleccionado o del frame más reciente si no hay selección.
- Los marcadores se guardan por conjunto de archivos fuente en `.canlytics_state`, para no mezclar eventos de logs distintos.
- Un ON se empareja con el siguiente OFF del mismo nombre. Diff compara la línea base inmediatamente anterior, de igual duración (recortada al inicio del log), contra el intervalo ON-OFF. Si no hay muestras de línea base, no propone una comparación.
- La propuesta usa rangos inclusivos; el usuario puede ajustar A/B antes de ejecutar Diff.
- Clear durante una captura activa inicia un segmento vacío bajo la ruta de grabación actual y permite seguir creando marcas.
- El contexto de análisis incluye los marcadores persistidos junto con los marcadores MCP existentes.

## Trabajo

1. Implementar persistencia por sesión, validación de ON/OFF y emparejamiento con rangos A/B.
2. Añadir una ventana de marcadores accesible desde el ribbon y Ctrl+M; permitir insertar marcas sobre el tiempo actual de tabla/captura y ver el historial.
3. Ofrecer Diff entre eventos para cargar automáticamente A/B y lanzar Range Diff, incluso si otro análisis estaba ejecutándose.
4. Incluir los marcadores persistidos en los handoffs de `AnalysisContext` y actualizar la documentación.

## Pruebas

- Regresión: persistencia aislada por sesión, transiciones ON/OFF, pairing de nombres iguales, baseline insuficiente, rangos A/B inclusivos, limpieza de marcas y fuentes de sesión.
- Suite completa: 1228 tests.
- Smoke visual: registrar ON/OFF en un log cargado, reabrir la ventana y comprobar persistencia, lanzar Diff automático y revisar el ribbon, Ctrl+M y los temas claro/oscuro. Capturas temporales en `%TEMP%\canlytics-f6-03-verify`.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa, revisiones code-reviewer y qt-mvvm-reviewer
- [x] Capturas de UI revisadas
