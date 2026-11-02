# F2-04 — Tabla principal incremental

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `perf/f2-04-incremental-table` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02, F2-03
- **Base commit:** 291d6ac

## Problema
La tabla principal recibe `dataframe_changed` con el acumulado en cada flush. El filtro usa un
watermark para filtrar solo filas nuevas, pero `TableModel.set_dataframe()` vuelve a comparar la
identidad de todas las filas y notifica cambios sobre las celdas anteriores.

## Propiedad
- **Puede editar:** `services/table_filter.py`, `viewmodels/table_filter_viewmodel.py`,
  `viewmodels/table_viewmodel.py`, `viewmodels/table_model.py`,
  `viewmodels/main_window_viewmodel.py`, `tests/test_table_filter.py`, `tests/test_table_model.py`,
  `tests/README.md`, `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otros servicios/ViewModels/vistas, `scripts/`, lógica de Mux Detection,
  HMI/OCR.

## Decisiones cerradas
- La captura ordenada llega a la tabla por `rows_appended`; el DataFrame completo se conserva como
  referencia para recalcular al cambiar el filtro y para las rutas de reemplazo.
- Los reemplazos completos y cambios de criterio reconstruyen la tabla; el flujo normal filtra y
  añade solo las filas del delta.
- `TableModel.append_rows` usa `beginInsertRows` y no compara identidad ni emite `dataChanged`
  sobre filas existentes. Si hay un orden de encabezado activo, inserta el delta en las posiciones
  ordenadas y conserva el orden natural para cuando se limpie ese criterio.
- El filtro y la tabla consolidan sus chunks cada 20 lotes.

## Trabajo
1. Añadir filtrado directo de deltas y mantener la ruta de reconstrucción completa.
2. Cablear `dataframe_replaced` y `rows_appended` a la tabla principal.
3. Añadir `TableModel.append_rows` y el throttle de rechunk.
4. Verificar la captura/replay real en la aplicación: 1150 filas en memoria y tabla.

## Pruebas
- El append filtrado incremental acumulado equivale al filtro completo.
- Un delta no emite DataFrame completo desde `TableFilterViewModel`.
- El modelo inserta filas sin reset ni `dataChanged` global.
- Suite completa verde y `/verify-ui` con replay.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
