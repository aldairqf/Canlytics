# P-04 — SDK de transmisión para plugins

- **Estado:** Hecho
- **Fase:** P de `docs/plan.md`
- **Rama:** `feature/p-04-plugin-transmit-sdk` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02, F7-01, P-02
- **Base commit:** `b06638d`

## Problema
`canlytics_sdk` ofrece `send_frame` como API del host; los plugins necesitan primitivas de transmisión J1939 y espera de respuestas sin bloquear la UI. F7-01 añade `services/j1939_transport.py`, que esta tarjeta debe reutilizar para BAM y RTS/CTS.

## Propiedad
- **Puede editar:** `canlytics_sdk/`, adaptadores SDK/host, `services/j1939_transport.py` solo si F7-01 requiere una extensión compatible, pruebas SDK y documentación.
- **No puede editar:** `views/` o `viewmodels/` desde plugins como API pública estable, lógica de Mux Detection, HMI/OCR, protecciones centrales de CAN Send fuera de interfaces acordadas ni otras tarjetas.

## Decisiones cerradas
- Depende de F7-01 y reutiliza `services/j1939_transport.py` como emisor BAM y RTS/CTS; no implementa un segundo transporte.
- Solo conexión real activa; nunca transmite en replay. Cada llamada pasa por las protecciones centrales de CAN Send y aparece en TX Log.
- Se aplican las mismas validaciones, bloqueo replay y TX Log de CAN Send; no se agregan confirmaciones ni limites de tasa. El emisor permite una sesion por clave SA/DA (BAM por SA), usa T3 para CTS/EOM ACK y T4 para hold; el receptor activo responde CMDT dirigido.
- `wait_for(pgn, sa, timeout)` es asíncrono/no bloqueante para UI, cancelable y con timeout obligatorio. No inicia solicitudes al activar el plugin.
- El plugin sigue siendo código de confianza; el SDK no promete sandbox.

## Trabajo
1. Definir API versionada `send_frame`, `send_pgn`, `request_pgn` y `wait_for` con tipos y errores estables.
2. Integrar transmisión J1939 con `services/j1939_transport.py` y el transporte central del host.
3. DM14/DM15/DM16 quedan fuera del alcance generico; requieren protocolo de fabricante.
4. Documentar límites, concurrencia, cancelación y compatibilidad de API.

## Pruebas
- Round-trip de BAM y RTS/CTS con el reensamblador; CTS parcial, Abort, timeout y respuesta simulada.
- Verificar que cada frame pasa por TX Log y replay se rechaza.
- Verificar rechazo durante replay y sin conexion real.
- Verificar que `wait_for` devuelve un Future y no bloquea quien llama.
- Revision 3: abort unico, colas TP, mapeo T3/T4, CMDT receptor, cierre, callbacks GUI y limites de timeout.
- Revision 4: receptor rearma timers por DT, respeta RTS max-packets y ventana configurable, T2 tras CTS/T1 entre DTs, source address local por wait_for y Abort/CTS inesperados del emisor.
- Revision 5: filtro CTS ligado al tiempo de solicitud RTS con tolerancia de 10 ms; Abort por CTS inesperado mantiene separado el DT pendiente hasta confirmar el Abort; RTS con limite cero aborta.
- Suite completa: 1448 tests; 1441 pasan y 7 pruebas MCP fallan por restricciones named-pipe/subprocess del sandbox.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` retirada
- [x] Guia, testing y mapa de tests actualizados
