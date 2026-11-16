# F7-02 - Diagnostico de error frames y protocolos

- **Estado:** Hecho
- **Fase:** 7 de `docs/plan.md`
- **Rama:** `feature/f7-02-error-frames` (sale de `dev`)
- **Base commit:** `89d6776`

## Problema
Las tramas de error deben conservarse como diagnosticos separados en carga, replay y streaming. El observador pasivo debe manejar solo trafico de direccionamiento diagnostico, tolerar PCI invalido y mantener memoria y UI acotadas.

## Decisiones cerradas
- Error frames se clasifican por flags/ID o token parseado, nunca por una expresion regular sobre la linea completa; no se insertan en las filas ordinarias.
- El import de candump detecta errores con Polars y solo parsea las filas candidatas, manteniendo progreso y cancelacion.
- ISO-TP observa `0x7DF`, `0x7E0-0x7EF`, `0x18DAxxyy`, `0x18DB33F1` y los IDs adicionales configurados. PCI invalido no aborta el chunk; timeout N_Cr se renueva en cada CF.
- Mensajes y actualizaciones visuales tienen limites configurables. Al cargar/reemplazar una fuente o iniciar stream se reinician los contadores; import usa timestamps del log y la captura en vivo usa una ventana monotona.
- UDS positivo se clasifica por SID + `0x40`; NRC `0x78` se muestra como response pending. OBD se limita a modos `0x01-0x0A` y respuestas `0x41-0x4A` en direccionamiento OBD.
- Las consultas manuales requieren conexion y confirmacion, quedan en TX Log y se bloquean durante replay. No se agrega rate limit: las solicitudes diagnosticas siguen el comportamiento de CAN Send.
- J1939 Request envia 3 bytes; el source address es configurable.

## Trabajo
La implementacion cubre los 18 puntos de F7-02: parser compacto y `candump -e`, importacion/replay en una pasada, SSH con `candump -e`, errores Kvaser, tasas/clases CAN_ERR, observer ISO-TP/UDS/OBD acotado, consultas, textos traducibles y escaneo del historial cargado con filtro vectorizado y worker con progreso/ETA.

## Pruebas
Regresiones en `test_can_data_parser.py`, `test_protocol_observer.py`, `test_diagnostics.py` y `test_can_source.py`, incluidas tramas compactas/sufijos, `ERRORFRAME` con espacios, chunk real con ID `0x00`, SF invalido, CF mas alla del timeout inicial, respuestas UDS positivas/pending, replay impar, Kvaser y flush offscreen.
La suite completa ejecuta 1,520 tests en 113 modulos; la suite final paso completa, incluidas las regresiones de historial cargado y NRC.
