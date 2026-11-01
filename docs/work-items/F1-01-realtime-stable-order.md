# F1-01 — Orden estable de filas en Real-Time

- **Estado:** Hecho
- **Fase:** 1
- **Rama:** `fix/f1-01-realtime-stable-order` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 3aa5b7a
- **Bug:** B-31 (registrar en `docs/bugs.md`)

## Problema
El usuario lo describe así: "antes en realtime los ids siempre se mantenían en el mismo orden,
pero ahora cuando viene un id nuevo o cuando se demora en llegar un id y estoy en modo
changing se mueven los CAN id y eso dificulta ver los cambios".

Causa (verificada):
- `views/table/table_view.py:14`: `DataTableView.__init__` llama a `setSortingEnabled(True)`. Qt
  responde con `model.sort(0, Qt.DescendingOrder)` implícito, porque el indicador por defecto
  del header es la sección 0 descendente. La columna 0 de `REAL_TIME_ANALYSIS_COLUMNS` es `TS`.
- `viewmodels/table_model.py:200-202`: `TableModel.sort` guarda `_sort_column=0` y
  `_sort_descending=True` **antes** del early-return con df vacío.
- `viewmodels/table_model.py:63-69` (commit `509fc98`, fix B-09): con `optimize_append=False`
  (Real-Time, `views/realtime_analysis_window.py:61`), `set_dataframe` reaplica
  `_apply_active_sort` en cada tick de 100 ms. Resultado: el ID más nuevo sube y el lento baja.
- El orden natural del ViewModel ya es estable por primera aparición
  (`viewmodels/real_time_analysis_viewmodel.py`, `_id_order`/`first_seen_index`).

## Propiedad
- **Puede editar:** `views/table/table_view.py`, `viewmodels/table_model.py`,
  `tests/test_table_model.py`, `docs/bugs.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`,
  esta tarjeta.
- **No puede editar:** nada más. En particular, no toques `real_time_analysis_viewmodel.py`
  (su orden ya es correcto) ni la lógica de Mux Detection.

## Decisiones cerradas
- Sin orden implícito al crear la vista. Al abrir, se muestra el orden natural del ViewModel.
- Si el usuario hace clic en un header, ordena por esa columna y ese orden sobrevive a los
  refrescos (B-09 se mantiene). Un tercer clic vuelve al orden natural
  (`header.setSortIndicatorClearable(True)`).
- El orden es estable: `df.sort(col, descending=..., maintain_order=True)`, para que los empates
  respeten el orden de primera aparición.
- `TableModel.sort(column < 0)` significa "sin orden": `_sort_column = None`. **Cuidado:** hoy
  `self._columns[-1]` tomaría la última columna. `sort(-1)` no debe reordenar `_df`; el orden
  natural vuelve en el siguiente `set_dataframe` del ViewModel.
- La tabla principal (`optimize_append=True`) no cambia de comportamiento.

## Trabajo
1. `DataTableView.__init__`: antes de `setSortingEnabled(True)`, poner
   `horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)`, y además
   `setSortIndicatorClearable(True)`.
2. `TableModel.sort`: si `column < 0`, `_sort_column = None` y return (sin `layoutChanged`
   innecesario si no hay datos).
3. `_apply_active_sort`: agregar `maintain_order=True`.

## Pruebas
- **Regresión primero (rojo → verde)** en `tests/test_table_model.py`. **No construyas widgets**
  (`QTableView`/`QWidget`) dentro de `tests/`: cuelgan `unittest discover`, ver la nota ⚠️ de
  `docs/testing.md`. Prueba sobre `TableModel` (es `QAbstractTableModel`, seguro):
  - `sort(-1, …)` después de un sort activo deja `_sort_column is None`, y el siguiente
    `set_dataframe` con `optimize_append=False` conserva el orden del ViewModel (llegada de ID
    nuevo y "ID lento").
  - El orden con empates es estable (`maintain_order`).
  - Siguen pasando los tests B-09 existentes.
- Suite completa en verde.
- `/verify-ui` (lo hace el orquestador): replay de un log real con la ventana Real-Time
  abierta y capturas de pantalla, para confirmar que las filas no se mueven.

## Cierre
- [x] CHANGELOG `## Unreleased` (sección "Correcciones", prosa para el usuario)
- [x] borrar la fila F1-01 de `docs/plan.md`
- [x] `docs/bugs.md`: nueva entrada **B-31** con el formato de B-09 (Dónde / Qué / Fix aplicado /
  Regresión) y agregarla a la lista de corregidos
