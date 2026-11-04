# P-03 — Herramientas MCP de plugins

- **Estado:** Hecho
- **Fase:** P de `docs/plan.md`
- **Rama:** `feature/p-03-plugin-mcp` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** M-01, P-01
- **Base commit:** `ad4d705`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

Los plugins pueden extender la UI, pero el servidor MCP de M-01 solo publica herramientas
integradas. Los plugins habilitados deben poder ofrecer herramientas tipadas a clientes MCP.

## Propiedad

- **Puede editar:** `canlytics_sdk/`, `services/plugin_manager.py`, `mcp_server/`,
  `tests/test_mcp_server.py`, `docs/plugins.md`, `docs/plan.md`, `docs/testing.md`,
  `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otras vistas/ViewModels, Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas

- Solo se cargan plugins habilitados según `.canlytics_state/plugins.json`.
- El nombre MCP es `p<longitud>_<plugin_id>_<tool_name>` para aislar el espacio de nombres de
  forma inequívoca y no superar 128 caracteres.
- El callback declara argumentos con anotaciones tipadas; el SDK MCP genera el esquema y valida
  las llamadas.
- El servidor headless no ofrece UI, suscripciones en vivo ni transmisión CAN a plugins.
- Plugins conservan los permisos del usuario; no hay sandbox.

## Trabajo

1. Añadir `PluginAPI.register_mcp_tool(name, callback, description=...)` y enumeración por plugin.
2. Cargar plugins habilitados y publicar sus tools en el servidor MCP de M-01; aislar errores de
   registro y limpiar recursos al terminar el servidor.
3. Documentar el contrato y verificar publicación, validación de argumentos y ejecución.

## Pruebas

- Tests Qt-free: plugins apagados no publican herramientas; plugins activos publican herramientas
  namespaced con schema tipado y ejecutan callbacks.
- Suite completa en verde.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa: 1193 tests en verde
- [x] Revisión code-reviewer y qt-mvvm-reviewer: hallazgos corregidos
