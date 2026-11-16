# F7-03 — Ingeniería inversa activa

- **Estado:** Hecho
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
- Toda transmisión de RE activo pasa por CAN Send. Replay bloquea el envío, y cada intento queda en TX Log. No se agregan confirmaciones, límites extra de tasa ni restricciones adicionales.
- Replay de subconjunto y generación de rampas aceptan IDs/rangos explícitos; las rampas requieren geometría y valores válidos. Diff compara ventanas etiquetadas antes/después.

## Trabajo
1. Añadir replay de un subconjunto filtrado usando el flujo de replay existente.
2. Implementar generador de rampas por señal con validación de rango, paso, periodo y límite de tasa.
3. Añadir «inyectar y observar» con marcadores de ventana y handoff a Diff. Hecho.
4. Mostrar confirmación, estado de transmisión y controles de parada.

## Pruebas
- Probar replay filtrado sin acceso al transmisor.
- Probar rampas: límites, tasa, cancelación, desconexión y errores.
- Probar confirmación y TX Log para cada transmisión; verificar que replay la bloquea.
- Probar que el resultado observado llega a Diff con rangos correctos. Hecho.
- Suite completa verde.
- `/verify-ui`: revisar confirmación, límites, TX Log, parada y rechazo en replay.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` (no había fila pendiente)
- [x] `docs/bugs.md` si aplica (sin bug nuevo)

Ronda de correcciones: el replay filtrado ya no falla (import local), filtra IDs normalizados y error frames, y espera a que la sesión previa se detenga; el rango de tiempo es opcional y usa la misma base en vista previa y replay; las rampas codifican Motorola/con signo/float/mux y construyen IDs J1939 de 29 bits; hay periodo configurable entre frames (`active_re_ramp_period_ms`); t0/t1 y el marcador usan el TS del stream, esperando un flush antes de Diff; los IDs de TX Log son únicos por corrida; el modo manual expone orden de bytes, escala/offset, signo y ID extendido.

Implementado: replay filtrado, rampas manuales y desde Working DBC, envío por CAN Send, e inyección con captura configurable antes/después, marcador temporal y Diff automático con `AnalysisContext`. La captura cancela sin bloquear la interfaz y Range Diff ejecuta el análisis en su worker con progreso y ETA.
