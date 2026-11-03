# M-03 — MCP conectado a la sesión abierta

- **Estado:** Hecho
- **Fase:** M de `docs/plan.md`
- **Rama:** `feature/m-03-mcp-live-session` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01, M-01
- **ADR:** [006](../architecture/decisions/006-mcp-live-session-bridge.md)
- **Base commit:** `2f1fe85`

## Problema

El servidor de [M-01](M-01-mcp-headless-server.md) trabaja con un log propio y no ve la sesión
abierta de Canlytics. Para consultar una captura o el contexto actual, el usuario tendría que
exportar/copiar datos a otro proceso.

## Propiedad

- **Puede editar:** `services/mcp_session.py`, `viewmodels/mcp_session_viewmodel.py`,
  `viewmodels/main_window_viewmodel.py`, `main.py`, `mcp_server/session_client.py`, `mcp_server/server.py`,
  `mcp_server/tools.py` si hace falta, `config/defaults.py`, `tests/test_mcp_session.py`,
  `tests/test_mcp_session_ipc.py`, `scripts/verify_mcp_session.py`, `docs/plan.md`,
  `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta,
  ADR 006 y su índice.
- **No puede editar:** envío CAN, lógica Mux Detection, HMI/OCR, transportes de conexión CAN,
  exportación estándar M-02, fases 6–7.

## Decisiones cerradas

- La app publica un canal local autenticado; el stdio MCP sigue atendiendo al cliente MCP.
- El servidor MCP solo recibe snapshots delgados, nunca referencias a `QWidget`, ViewModels ni al
  DataFrame completo. El anillo de frames recientes es acotado y se actualiza por delta.
- Añadir las herramientas `get_open_session`, `get_recent_frames`, `get_analysis_context`,
  `add_session_marker` y `list_session_markers`. Los marcadores viven en memoria hasta cerrar la app.
- El contexto se consulta, no se modifica. No se carga, borra ni exporta el log por este puente.
- Usar timestamp absoluto en segundos; limitar cada respuesta de frames a 500 filas.

## Trabajo

1. Crear el snapshot Qt-free con estado de sesión, IDs, fuentes, anillo de frames, contexto y
   marcadores efímeros.
2. Publicarlo por el puente local autenticado en un worker `QThread` propiedad del composition root.
3. Añadir el cliente IPC y las cinco herramientas MCP para consultar la sesión y anotar eventos.
4. Cubrir actualización por delta, límites, autenticación, apagado y conexión desde el servidor MCP.

## Pruebas

- Regresión primero (rojo → verde): estado y frames recientes tras reemplazo/append, límites del
  anillo y del payload, contexto serializado, marcadores y rechazo de solicitudes inválidas.
- Smoke de proceso MCP conectado a la app y captura de una sesión de fixture; comprobar que cerrar
  la app elimina el endpoint y que no queda un worker vivo.
- Suite completa en verde; usar logs fixture de solo lectura. Verificado: 1098 tests.
- `scripts/verify_mcp_session.py`: stdio, frames, contexto, marcador, delta y apagado verificados.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; sin cambios aplicables
- [x] Suite completa y smoke de IPC
