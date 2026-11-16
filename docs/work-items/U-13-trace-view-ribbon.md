# U-13 — Configuración de vista del trace en el ribbon

- **Estado:** Hecho
- **Fase:** U2 de `docs/plan.md`
- **Rama:** `feature/u-13-trace-view-ribbon`
- **Depende de:** F6-07, F6-09, ADR 001

## Problema

La barra de filtros y el resaltado de bytes saturaban la tabla principal. El formato de datos, las columnas opcionales y la vista de una fila por ID permiten adaptar el trace a la inspección sin ocupar una barra permanente.

## Trabajo realizado

- Se retiraron la barra de filtros de contenido, sus servicios y pruebas exclusivas, y el resaltado de bytes del trace principal. Real-Time conserva su análisis y delegate de bytes cambiados.
- Inicio → Vista reúne Hex/Dec/Bits, el diálogo de columnas y el toggle «Una fila por ID».
- El modo compacto mantiene el último frame por ID, actualiza su índice desde cada chunk y restaura la vista completa al desactivarlo. Conserva el orden numérico inicial, el sort, los filtros de ID y tiempo, el cursor global y la persistencia.

## Verificación

- `tests/test_u13_trace_view.py` cubre la vista, el ribbon, columnas, formato, persistencia y el modo compacto con datos cargados y chunks.
- Suite completa: 1411 tests en verde.
- `MainWindow` y el ribbon pasan pruebas offscreen. El intento de inspección del escritorio fue rechazado por la política automática de Computer Use al seleccionar la ventana Python; la comprobación visual manual queda pendiente.
