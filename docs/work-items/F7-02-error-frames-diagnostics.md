# F7-02 — Diagnóstico de error frames y protocolos

- **Estado:** Pendiente
- **Fase:** 7 de `docs/plan.md`
- **Rama:** `feature/f7-02-error-frames-diagnostics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
`services/can_stream.py` descarta `frame.is_error` durante la recepción; `services/can_data_parser.py` omite error y remote frames al cargar logs. `viewmodels/connection_stream_viewmodel.py` orquesta el flujo recibido. Se necesita conservar diagnósticos sin confundirlos con tramas de datos y añadir herramientas de observación de protocolos.

## Propiedad
- **Puede editar:** `services/can_stream.py`, `services/can_data_parser.py`, `services/can_source.py`, `viewmodels/connection_stream_viewmodel.py`, ViewModels y vistas dedicadas a diagnóstico, textos, pruebas y documentación asociadas.
- **No puede editar:** HMI/OCR, lógica de Mux Detection, transportes de hardware fuera de los adaptadores requeridos, otras tarjetas ni el esquema del DataFrame sin acuerdo previo.

## Decisiones cerradas
- Error frames se contabilizan y exponen como diagnóstico separado; no se insertan como tramas de datos ordinarias ni se decodifican como señales.
- Mantener separados los errores observados por el bus, errores de transporte y errores de aplicación.
- Las consultas activas requieren conexión real; nunca se ejecutan durante replay. Cada transmisión requiere confirmación explícita, queda registrada en TX Log y respeta límites de tasa.
- ISO-TP/UDS/OBD y consultas J1939/OBD son acciones explícitas; no hay sondeo automático al conectar.

## Trabajo
1. Definir un modelo diagnóstico para contar y presentar error frames descartados en recepción.
2. Trazar el tratamiento de error frames al importar logs y ofrecer diagnóstico sin alterar el DataFrame ordinario.
3. Añadir observación ISO-TP/UDS/OBD y consultas de referencia J1939/OBD según el alcance acordado.
4. Documentar métricas, límites y configuración.

## Pruebas
- Caracterizar error frames en fuente en vivo y parser, incluyendo que no se conviertan en filas normales.
- Probar contadores, reset por sesión y separación entre error CAN, transporte y aplicación.
- Probar conexión real, confirmación, TX Log, límite de tasa y rechazo de consultas en replay.
- Suite completa verde.
- `/verify-ui`: mostrar diagnóstico, actualizar contadores y revisar estados sin conexión y en replay.

## Cierre
- [ ] CHANGELOG `## Unreleased`  - [ ] fila de `docs/plan.md`  - [ ] `docs/bugs.md` si aplica
