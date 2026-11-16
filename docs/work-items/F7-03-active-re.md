# F7-03 — Ingeniería inversa activa

- **Estado:** Pendiente
- **Fase:** 7 de `docs/plan.md`
- **Rama:** `feature/f7-03-active-re` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02, F6-03, D-02
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
La aplicación tiene reproducción de logs y CAN Send con protección explícita contra transmisión durante replay (`viewmodels/can_send_viewmodel.py`, `viewmodels/connection_stream_viewmodel.py`). Hace falta extender estos flujos para reproducir subconjuntos, generar rampas por señal y comparar la respuesta en Diff.

## Propiedad
- **Puede editar:** ViewModels y servicios de replay/envío, integración con Diff y UI dedicadas a RE activo, configuración, pruebas y documentación de la tarjeta.
- **No puede editar:** servicios de recepción compartidos salvo el cableado necesario, HMI/OCR, lógica de Mux Detection, tarjetas concurrentes ni esquema persistido sin acuerdo previo.

## Decisiones cerradas
- Toda transmisión exige conexión real activa; replay nunca transmite y las acciones de RE activo se deshabilitan durante replay.
- Cada operación requiere confirmación explícita antes del primer envío y muestra CAN ID, datos, duración y tasa.
- Cada frame transmitido se registra en TX Log, incluidos los envíos periódicos y errores.
- Límites de tasa y duración configurables con valores conservadores; no hay bucles sin límite ni repetición automática tras reconectar.
- Las rampas requieren señal y rango explícitos; detener/cancelar corta la generación. Diff compara ventanas etiquetadas antes/después.

## Trabajo
1. Añadir replay de un subconjunto filtrado usando el flujo de replay existente.
2. Implementar generador de rampas por señal con validación de rango, paso, periodo y límite de tasa.
3. Añadir «inyectar y observar» con marcadores de ventana y handoff a Diff.
4. Mostrar confirmación, estado de transmisión y controles de parada.

## Pruebas
- Probar replay filtrado sin acceso al transmisor.
- Probar rampas: límites, tasa, cancelación, desconexión y errores.
- Probar confirmación y TX Log para cada transmisión; verificar que replay la bloquea.
- Probar que el resultado observado llega a Diff con rangos correctos.
- Suite completa verde.
- `/verify-ui`: revisar confirmación, límites, TX Log, parada y rechazo en replay.

## Cierre
- [ ] CHANGELOG `## Unreleased`  - [ ] fila de `docs/plan.md`  - [ ] `docs/bugs.md` si aplica
