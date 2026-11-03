# M-02 — Herramientas MCP con DBC

- **Estado:** Hecho
- **Fase:** M de `docs/plan.md`
- **Rama:** `feature/m-02-mcp-dbc-tools` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F4-01, F4-02, F5-01, M-03
- **Base commit:** `555d2c1`
- **ADR:** [003](../architecture/decisions/003-working-dbc.md), [006](../architecture/decisions/006-mcp-live-session-bridge.md)

## Problema

El MCP ya consulta la sesión abierta, pero no puede decodificar un frame con los DBC activos ni
guardar una señal descubierta en Working DBC. F4-01/02 y F5-01 ya entregan el servicio editable,
la persistencia y el manager Qt-free; M-03 ofrece el canal autenticado a la app.

## Propiedad

- **Puede editar:** `mcp_server/server.py`, `mcp_server/session_client.py`,
  `viewmodels/mcp_session_viewmodel.py`, `viewmodels/main_window_viewmodel.py`,
  `services/working_dbc.py`, `tests/test_mcp_server.py`, `tests/test_mcp_session_ipc.py`,
  `tests/test_working_dbc.py`, `tests/test_working_dbc_persistence.py`,
  `scripts/verify_mcp_session.py`, `docs/architecture/decisions/006-mcp-live-session-bridge.md`,
  `docs/architecture/overview.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** CAN Send, carga/borrado/exportación de logs por el puente, cambios de contexto,
  Mux Detection, HMI/OCR, otras tarjetas F4/F5.

## Decisiones cerradas

- `decode_with_dbc` consulta el DBC activo de la app por el puente local autenticado; no necesita ruta de archivo.
- `save_signal_to_working_dbc` valida y persiste una señal por la app, con operaciones de dominio
  ejecutadas en el hilo GUI mediante una solicitud encolada desde el worker IPC.
- Si el CAN ID ya existe en un DBC cargado pero no en Working DBC, copiar el mensaje completo antes
  de añadir la señal; así se conservan las señales existentes.
- Si Working DBC tiene mensajes, toma precedencia de decode sobre los DBC externos; para IDs que no
  contiene, el manager continúa con los DBC activos en su orden previo.
- Sin app abierta no se escribe el DBC en disco; la herramienta devuelve un error explícito para no
  competir con la persistencia de la sesión.

## Trabajo

1. Enrutar las dos operaciones MCP específicas a un handler del composition root, sin acceso a QObject
   desde el hilo IPC.
2. Implementar decodificación con DBC activo y guardado validado en Working DBC, con cache/orden actualizados.
3. Registrar las dos tools MCP y exponer tipos/parámetros claros.
4. Cubrir auth/stdio real, ejecución en hilo GUI, persistencia, precedente de decode y errores.

## Pruebas

- Servicio: copiar un mensaje externo sin modificar el original y conservar su decode al guardar la señal nueva.
- IPC y proceso stdio: decode, save y consulta posterior de la sesión; verificar archivo y cache actualizados.
- Suite completa verde; DBC/log fixtures solo lectura.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde (1122 tests)
