# F4-01 — Servicio Qt-free para DBC de trabajo

- **Estado:** Hecho
- **Fase:** 4 de `docs/plan.md`
- **Rama:** `feature/f4-01-working-dbc` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **ADR:** [003](../architecture/decisions/003-working-dbc.md)
- **Base commit:** `8282256`

## Problema

El DBC cargado es de solo lectura y no existe una capa para conservar señales descubiertas.
ADR 003 define `services/working_dbc.py` como núcleo Qt-free; hoy no existe ese servicio.

## Propiedad

- **Puede editar:** `services/working_dbc.py`, `tests/test_working_dbc.py`, `docs/plan.md`,
  `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `DbcManager`, ViewModels, vistas, `main.py`, DBC fuente, Mux Detection,
  HMI/OCR, otras tarjetas F4.

## Decisiones cerradas

- Crear un `WorkingDbc` Qt-free basado en `cantools.Database`; el DBC fuente nunca se modifica.
- CRUD de mensajes y señales, validación de rangos y solapes por bits, con solapes permitidos
  solo entre señales mux con casos mutuamente excluyentes o entre selector y sus ramas.
- Exportar a una ruta `.dbc` explícita sin crear persistencia ni integrarse aún con `DbcManager`.
- Al importar un DBC fuente, conservar su ruta para impedir que la exportación sobrescriba el original.
- Mantener soporte de frames CAN clásico de hasta 8 bytes en este servicio.

## Trabajo

1. Implementar construcción y edición de mensajes/señales con validación de nombres, CAN ID,
   longitud, conversión y geometría de bits (LE/BE).
2. Validar solapes considerando la geometría real y relaciones multiplexadas.
3. Eliminar señales y mensajes, exportar el DBC de trabajo y comprobar el round-trip de decodificación.

## Pruebas

- Regresión primero: CRUD, validación de IDs/DLC/geometría, conversiones, solapes LE/BE y mux.
- Ida y vuelta con un archivo temporal: crear, exportar, recargar con cantools y comparar decode.
- Suite completa verde; fixtures de solo lectura.
- Verificado: 1108 tests; round-trip real en archivo temporal.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; sin cambios aplicables
- [x] Suite completa en verde (1108 tests)\n