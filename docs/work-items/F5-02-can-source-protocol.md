# F5-02 — Fuentes CAN detrás de un protocolo

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-02-can-source` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F1-06
- **Base commit:** `40baf6d`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

`_ConnectionStreamWorker` mezcla conexión SSH, probing y recepción Kvaser, replay, timestamp,
buffering y emisión de chunks. Las decisiones por modo y los loops ocupan
`viewmodels/connection_stream_viewmodel.py`, aunque el ViewModel debe adaptarlos. La lógica debe
vivir en `services/` tras un contrato que permita sustituir fuentes y probarlas sin Qt ni hardware.

## Propiedad

- **Puede editar:** `services/can_source.py`, `services/can_sources.py`,
  `services/can_stream.py`, `viewmodels/connection_stream_viewmodel.py`,
  `tests/test_can_source.py`, `tests/test_connection_stream_viewmodel.py`,
  `tests/test_connection_stream_bitrate_probe.py`, `tests/test_connection_stream_disconnect.py`,
  `docs/architecture/overview.md`,
  `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** vistas, `services/can_data_parser.py`, `services/remote_connection.py`,
  `services/kvaser_config.py`, lógica CAN Send fuera del transporte, Mux Detection, HMI/OCR,
  otras tarjetas.

## Decisiones cerradas

- `CanSource` será un `Protocol` Qt-free para abrir, recibir, enviar y cerrar una fuente.
- Las implementaciones SSH, Kvaser y replay vivirán en `services/`; las dependencias de hardware
  se importan de forma perezosa.
- El servicio de streaming conserva el contrato actual: frames convertidos a `FRAME_SCHEMA`,
  timestamps, orden, tamaño/intervalo de flush, errores, cancelación y replay.
- Los callbacks de estado, cancelación, bombeo de eventos y entrega de chunks se inyectan; los
  servicios no importan Qt. El bombeo permite que los envíos CAN sigan procesándose durante RX.
- La UI y los ViewModels mantienen sus métodos públicos y las preferencias actuales.

## Trabajo

1. Definir el protocolo y una implementación de cada modo sin importar Qt.
2. Extraer buffering/timestamps/replay loop y probing Kvaser a `services/`.
3. Reducir `_ConnectionStreamWorker` a ciclo de vida Qt, callbacks y señales.
4. Caracterizar cancelación, envío durante RX, bitrate probe, timestamps y chunks con fuentes falsas.

## Pruebas

- Services se importan sin `PySide6`, `can` ni `paramiko` requeridos al importar el módulo.
- Fuentes falsas verifican el contrato; tests existentes de configuración Kvaser se conservan.
- Suite completa verde y `/verify-ui` de replay, parada y estado de conexión.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde
- [x] Capturas de replay/parada revisadas
- [x] Envío CAN encolado durante RX caracterizado
