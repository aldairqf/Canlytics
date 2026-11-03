# Decisiones de arquitectura (ADR)

Cada decisión de diseño, con contexto, la decisión tomada y sus consecuencias. Un ADR
aceptado no se edita para cambiar la decisión. Un cambio incompatible crea un ADR nuevo
que **sustituye** al anterior, y el anterior queda marcado como sustituido.

| ADR | Decisión | Estado |
|---|---|---|
| [001](001-streaming-append-delta.md) | Streaming con contrato append-delta: el trabajo por flush es O(chunk) | Aceptado |
| [002](002-no-ram-cap.md) | Sin tope de RAM en captura; guardián de memoria que avisa y nunca descarta | Aceptado |
| [003](003-working-dbc.md) | DBC de trabajo editable, separado del DBC cargado (que es de ayuda) | Aceptado |
| [004](004-analysis-context.md) | Contexto de análisis compartido entre ventanas | Aceptado |
| [005](005-dual-orchestration.md) | Orquestación dual de agentes (Claude→Codex y Codex→Codex), config versionada | Aceptado |
| [006](006-mcp-live-session-bridge.md) | Puente MCP local y acotado a la sesión abierta de la app | Aceptado |

Plantilla: `# NNN — Título` · **Estado** · **Contexto** · **Decisión** · **Consecuencias**.
