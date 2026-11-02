# M-01 — Servidor MCP headless

- **Estado:** Hecho
- **Fase:** M
- **Rama:** `feat/m-01-mcp-headless` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-02
- **Base commit:** 3933884

## Problema
Los servicios Qt-free de Canlytics no están disponibles para clientes MCP; el trabajo offline exige abrir la UI.

## Propiedad
- **Puede editar:** `mcp_server/`, `requirements.txt`, `services/candidate_interpretations.py` (publicar la entrada ya usada por el ViewModel), `viewmodels/candidate_interpretations_viewmodel.py`, `tests/test_mcp_server.py`, `tests/README.md`, `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otras partes de `services/` o UI/MVVM, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Transporte local stdio del SDK oficial `mcp` v2, con funciones de dominio en `services/` existentes.
- Un proceso tiene un log cargado a la vez.
- Exportaciones y artefactos solo escriben bajo `~/.canlytics/mcp/`; los logs de campo se leen y nunca se modifican.
- Envío CAN solo se registra si se arranca con `--allow-can-send`; cada intento habilitado queda en TX log. No se prueba contra hardware.

## Trabajo
1. Añadir tools para carga/consulta de logs, candidatos, diff, constraint search, exportación y guardado de señales/marcadores.
2. Proteger la carpeta de logs al resolver todas las rutas de escritura.
3. Añadir `send_frame` detrás del flag de arranque y registrar cada intento.

## Pruebas
- Tests Qt-free para sesión, análisis, exportación segura, artefactos y bloqueo/envío CAN con bus simulado.
- Prueba del servidor MCP stdio o de su registro de tools.
- Suite completa en verde: 1046 tests.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa (1046 tests), smoke del protocolo stdio y TX simulado
