# P-04 — SDK de transmisión para plugins

- **Estado:** Pendiente
- **Fase:** P de `docs/plan.md`
- **Rama:** `feature/p-04-plugin-transmit-sdk` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02, F7-01, P-02
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
`canlytics_sdk` ofrece `send_frame` como API del host; los plugins necesitan primitivas de transmisión J1939 y espera de respuestas sin bloquear la UI. F7-01 añade `services/j1939_transport.py`, que esta tarjeta debe reutilizar para BAM y RTS/CTS.

## Propiedad
- **Puede editar:** `canlytics_sdk/`, adaptadores SDK/host, `services/j1939_transport.py` solo si F7-01 requiere una extensión compatible, pruebas SDK y documentación.
- **No puede editar:** `views/` o `viewmodels/` desde plugins como API pública estable, lógica de Mux Detection, HMI/OCR, protecciones centrales de CAN Send fuera de interfaces acordadas ni otras tarjetas.

## Decisiones cerradas
- Depende de F7-01 y reutiliza `services/j1939_transport.py` como emisor BAM y RTS/CTS; no implementa un segundo transporte.
- Solo conexión real activa; nunca transmite en replay. Cada llamada pasa por las protecciones centrales de CAN Send y aparece en TX Log.
- Cada secuencia que transmite requiere confirmación explícita y respeta límites de tasa, cantidad de frames y timeout.
- `wait_for(pgn, sa, timeout)` es asíncrono/no bloqueante para UI, cancelable y con timeout obligatorio. No inicia solicitudes al activar el plugin.
- El plugin sigue siendo código de confianza; el SDK no promete sandbox.

## Trabajo
1. Definir API versionada `send_frame`, `send_pgn`, `request_pgn` y `wait_for` con tipos y errores estables.
2. Integrar transmisión J1939 con `services/j1939_transport.py` y el transporte central del host.
3. Añadir bloques Memory Access DM14/DM15/DM16 cuando el fabricante los requiera.
4. Documentar límites, concurrencia, cancelación y compatibilidad de API.

## Pruebas
- Probar API SDK con transporte falso: frames, PGN, respuestas, timeout y cancelación.
- Verificar que cada frame pasa por TX Log, confirmación y límites de tasa.
- Verificar rechazo durante replay y sin conexión real.
- Probar que la UI no se bloquea al esperar respuestas y que el plugin recibe errores de transporte.
- Suite completa verde.
- `/verify-ui`: habilitar plugin de prueba, confirmar operación y revisar TX Log; comprobar rechazo en replay.

## Cierre
- [ ] CHANGELOG `## Unreleased`  - [ ] fila de `docs/plan.md`  - [ ] `docs/bugs.md` si aplica
