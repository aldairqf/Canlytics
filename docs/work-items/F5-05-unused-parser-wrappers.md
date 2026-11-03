# F5-05 — Retirar wrappers CAN sin consumidores

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-05-remove-unused-parsers` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02
- **Base commit:** `9e6740f`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

`services/can_frame_formatter.py` solo reexporta símbolos de `can_data_parser.py`, y
`services/candump_parser.py` solo adapta `StreamCanParser`. La búsqueda de referencias en el código
de la aplicación no encontró consumidores de ninguno de los módulos. `PipelineBuilder`, en cambio,
se importa y construye desde `views/signal/derived_signal_dialog.py`; por eso no es código muerto y
se conserva.

## Propiedad

- **Puede editar:** `services/can_frame_formatter.py`, `services/candump_parser.py`,
  `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `views/signal/pipeline_builder.py`,
  `views/signal/derived_signal_dialog.py`, otros servicios o vistas, Mux Detection, HMI/OCR.

## Decisiones cerradas

- Se eliminan solo los dos wrappers sin consumidores.
- `PipelineBuilder` sigue en la UI de señales derivadas y queda fuera de esta limpieza.
- No se cambia `services/can_data_parser.py` ni el formato público de frames.

## Trabajo

1. Eliminar los módulos que no tienen importadores en la aplicación ni en las pruebas.
2. Cerrar la fila de F5-05 y registrar el cambio en Unreleased.

## Pruebas

- Suite completa verde; comprobar imports y referencias restantes.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa en verde (1149 tests)
- [x] `PipelineBuilder` verificado en uso y conservado
