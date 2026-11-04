# P-02 — UI y extensiones interactivas de plugins

- **Estado:** Hecho
- **Fase:** P de `docs/plan.md`
- **Rama:** `feature/p-02-plugin-ui` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01, P-01 (completadas)
- **Base commit:** `73c35cf`
- **Arquitectura:** [overview](../architecture/overview.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

P-01 permite descubrir y activar plugins, pero todavía no pueden aportar herramientas visibles ni consumir el flujo en vivo. La tarjeta P-02 del plan pide ventanas con integración al ribbon y al tema, suscripción incremental, acciones comunes de análisis, marcadores y envío de frames.

## Propiedad

- **Puede editar:** `canlytics_sdk/`, `services/plugin_manager.py`, `viewmodels/plugin_viewmodel.py`, `viewmodels/can_send_viewmodel.py`, `viewmodels/analysis_context_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `models/analysis_context.py`, `views/main_window.py`, `views/widgets/ribbon_bar.py`, `views/widgets/ribbon_button.py`, `views/plot/add_to_plot_menu.py`, `views/table/frame_context_menu.py`, `config/ui_text.py`, pruebas de plugins/UI, `examples/plugins/`, `docs/plugins.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/can_source.py`, `services/can_sources.py`, `viewmodels/connection_stream_viewmodel.py`, lógica de Mux Detection, HMI/OCR, fases posteriores de transmisión P-04.

## Decisiones cerradas

- Los plugins son código confiable sin sandbox; excepciones de hooks deben aislarse para que no interrumpan la aplicación.
- Los datos live se entregan como chunks crudos y cada suscripción se desconecta al cerrar o desactivar el plugin.
- El contrato de streaming conserva O(chunk): no se reconstruye ni recorre el DataFrame acumulado al emitir datos live.
- `AnalysisContext` es el tipo compartido para las acciones de «Enviar a…»; el plugin no accede a widgets internos de otras ventanas.
- P-04 será responsable de capacidades de transmisión; esta tarjeta define la interfaz de registro/dispatch y mantiene la prohibición de enviar en replay.
- Los marcadores se reciben como evidencia opcional del contexto cuando exista una fuente de marcadores; no se crea una segunda implementación de F6-03.

## Trabajo

1. Importar carpetas o ZIPs con `plugin.toml` desde Plugins al directorio configurado, validar metadata, rechazar colisiones y rutas inseguras, y dejar los plugins importados desactivados.
2. Ampliar el SDK con registro de ventanas, acciones para "Enviar a", acciones contextuales, suscripciones a chunks, contexto de marcadores y solicitudes de envio de frames.
3. Adaptar ViewModel y composition root para aislar callbacks, limpiar ventanas y suscripciones al cerrar/desactivar, y despachar acciones con los contratos existentes.
4. Añadir un grupo dinámico Plugins en el ribbon, respetar el ciclo de vida de ventanas secundarias, persistir geometría y seguir el tema activo.
5. Documentar y demostrar un plugin de ejemplo con ventana, chunks incrementales y handoff de análisis.

## Pruebas

- Regresión primero para registro/dispatch, fallo aislado, alta/baja de listeners, cierre de ventana y restricciones de envío.
- Suite completa verde.
- `/verify-ui`: abrir plugin de ejemplo, observar su ventana en el grupo Plugins, validar tema/geometría y comprobar que cerrar/desactivar corta las actualizaciones.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` sin cambios (no se verificó otro bug)
- [x] Suite completa: 1188 tests en verde
- [x] Revisiones code-reviewer y qt-mvvm-reviewer: hallazgos corregidos
- [x] Capturas del ribbon, Connect/Start y ventana de ejemplo revisadas
