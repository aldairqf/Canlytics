# P-01 — Cargador y contrato inicial de plugins

- **Estado:** Hecho
- **Fase:** P de `docs/plan.md`
- **Rama:** `feature/p-01-plugin-loader` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F4-01, F5-01, D-02 (completadas)
- **Base commit:** `b28cccf`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

El plan define extensiones de terceros por carpeta o entry point, pero Canlytics no tiene un
cargador, un contrato inicial ni una forma de ver y controlar los plugins instalados. Los
plugins son código de confianza y un error de uno no debe impedir iniciar ni usar la app.

## Propiedad

- **Puede editar:** `models/plugin.py`, `services/plugin_manager.py`, `canlytics_sdk/`, `viewmodels/plugin_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `views/settings/plugins_dialog.py`, `views/main_window.py`, `views/menu/main_menu_factory.py`, `views/widgets/ribbon_bar.py`, `config/ui_text.py`, `tests/test_plugin_manager.py`, pruebas UI relacionadas, `examples/plugins/`, `docs/plugins.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/dbc_manager.py`, `services/working_dbc.py`, `viewmodels/main_window_viewmodel.py` salvo el adaptador de acceso que requiera el registro; `views/widgets/ribbon_bar.py`, `views/widgets/hmi_frame_editor_widget.py`, Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas

- Las carpetas viven en `%APPDATA%/Canlytics/plugins` o en `CANLYTICS_PLUGINS_DIR`; los paquetes usan el grupo `canlytics.plugins`.
- Cada carpeta tiene `plugin.toml` con `id`, `name`, `version`, `api_version` y `entry_point` (`module:callable`). La API incompatible no se carga.
- El servicio de plugins no depende de Qt. Un error de parseo, importación o registro se conserva por plugin y no interrumpe otros.
- Los plugins pueden activarse y desactivarse desde Configuración → Plugins; la preferencia se guarda fuera de los archivos de configuración versionados.
- Los plugins tienen los permisos del usuario y ejecutan código confiable, sin sandbox.

## Trabajo

1. Implementar descubrimiento, validación de metadatos, activación, desactivación y aislamiento de errores para carpetas y entry points.
2. Definir un SDK pequeño y estable que entregue un contexto de sesión de solo lectura y puntos de registro para fuentes de DBC, importadores y exportadores.
3. Añadir una pantalla de plugins con estado, errores y controles de activación; incluir una guía y un plugin de ejemplo que no se cargue automáticamente.

## Pruebas

- Regresión Qt-free para descubrimiento, metadata/API inválida, activación, errores aislados, persistencia y entry points.
- Suite completa en verde.
- `/verify-ui`: abrir Configuración → Plugins, revisar estados, errores legibles y activar/desactivar un plugin de ejemplo.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] Guía, ejemplo y overview actualizados
- [x] Suite completa: 1174 tests en verde
- [x] Revisión code-reviewer y qt-mvvm-reviewer: hallazgos corregidos
- [x] Captura del ribbon y flujo de activar/desactivar revisados
