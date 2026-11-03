# BUGS — Canlytics (bugs reales revisados)

> Es el registro de bugs verificados por revisión de código (con
> `archivo:línea` y escenario de fallo). Cada uno debería tener un **test de regresión**
> en `tests/` (ver [testing.md](testing.md)) antes o junto con su corrección.

Estado: **CONFIRMADO** (reproducible por lectura de código / reproducido) ·
**PLAUSIBLE** (real pero de disparo poco común o pendiente de decisión de diseño).
Severidad: 🔴 alta · 🟠 media · 🟡 baja.

Rutas relativas a la raíz del repo.

## Estado de corrección (rama `feature/range-diff`) — actualizado 2026-07-19

✅ **Corregidos** (con verificación, todos con test de regresión salvo donde se anota):
**B-01, B-02, B-03, B-04, B-05, B-06, B-07, B-08, B-09, B-10, B-11, B-12, B-13, B-14,
B-15, B-16, B-17, B-18, B-19, B-20, B-21, B-22, B-23, B-24, B-26, B-27, B-29, B-30, B-31,
B-32, B-34, B-35**
(B-29 solo necesitó test de caracterización, ver su entrada). **B-28** resuelto por
diseño (el control que tenía el bug ya no existe).

⏳ **Pendientes:** ninguno registrado.

Todo lo demás de la revisión 2026-07-18 (barrido de 4 agentes sobre Diff Analyzer,
Real-Time, Constraint Search y Analyze Data) quedó cerrado esta sesión.

---

## Range Diff / Diff Analyzer

### B-01 🟠 CONFIRMADO — Timeline vacío al abrir la ventana; cursores A/B no arrastrables ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py` (`__init__` solo hacía `_build_ui()`+`_wire()`);
  `viewmodels/range_diff_viewmodel.py` (el VM de vida larga emite `density_changed`/
  `ranges_changed` al cargar el log, antes de que la ventana exista).
- **Qué:** el `RangeDiffViewModel` se crea en el composition root y vive todo el tiempo;
  la ventana se crea perezosamente al abrirla. Al cargar un log, `reset_dataframe` emite
  densidad + rangos **al vacío** (nadie escucha). Al abrir la ventana después, nunca
  pedía el estado actual → timeline con densidad vacía, span `[0,1]`, bandas A/B de ancho
  cero pegadas al borde izquierdo.
- **Escenario:** cargar log → abrir Range Diff → histograma vacío, no hay bandas
  agarrables → "el timeline no sirve para mover los cursores".
- **Fix aplicado:** `RangeDiffViewModel.emit_current_state()` (re-emite densidad + rangos
  + reporte) llamado al final del `__init__` de la ventana. Mismo patrón que Candidate
  Interpretations (`set_dataframe` al final de su init).
- **Regresión:** `tests/test_range_diff_viewmodel.py::test_emit_current_state_repushes_density_and_ranges`.
  Verificado además con arrastre de mouse simulado (banda A movida 109.95→129.85, VM en sync).

### B-02 🟠 CONFIRMADO — Campos Range A/B: epoch crudo con `:g` → ignora timezone, ilegible y "salta al rango completo" ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py` (`_on_ranges` pinta `f"{range.start:g}"`, ~L227-230;
  `_parse_float` re-lee ese texto en `editingFinished`, ~L204-219).
- **Qué:** una sola raíz para tres síntomas. Con epoch ~1.78×10⁹, `:g` (6 cifras
  significativas) da **precisión de solo ~10 000 s**: `1.78377e+09`=1 783 770 000 vs
  `1.78378e+09`=1 783 780 000. Por eso: (1) no respeta el timezone configurado (muestra
  epoch, no hora); (2) es ilegible (notación científica); (3) al perder foco,
  `editingFinished` re-parsea el valor redondeado y la selección se **pega a bloques de
  ~10 000 s** ≈ medio log ("los rangos toman el rango completo"). No es aleatorio: es la
  pérdida de precisión del `:g`.
- **Escenario:** con timezone configurado y un log de timestamps epoch reales, elegir un
  rango fino con el timeline → al hacer clic fuera del campo, el rango salta a un bloque
  enorme.
- **Fix aplicado:** campos A/B ahora se pintan vía `utils/timezone_format.format_timestamp(value,
  tz_mode)` (respeta timezone; sin tz cae a `.2f` con precisión completa); `timezone_mode`
  cableado a la ventana (manager + `main_window` + `timezone_changed`, mismo patrón que las
  demás ventanas). Elimina el round-trip lossy texto→float — commit `1930cfb`.
- **Regresión:** cubierto por los tests existentes de `test_range_diff_viewmodel.py` +
  verificación manual del formato en los 3 modos de timezone. Suite completa sin regresiones.

### B-13 🟠 CONFIRMADO — Filtros desincronizados al reabrir la ventana (VM vive, ventana no) ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py:76` (`WA_DeleteOnClose`, la ventana se destruye y
  recrea con checkboxes en sus defaults de construcción, ~L113-124) vs.
  `viewmodels/range_diff_viewmodel.py` (`RangeDiffViewModel` es singleton de vida larga en
  `MainWindowViewModel`, su `_options` sobrevive al cierre).
- **Qué:** al reabrir, `emit_current_state()` (`range_diff_viewmodel.py:62-68`) re-emite
  `report.visible(self._options)` con las opciones **viejas** del VM, pero los checkboxes de
  la ventana nueva muestran los **defaults** (ej. "Only significant" desmarcado). El árbol
  queda filtrado por la config anterior mientras la UI muestra otra cosa, hasta que el
  usuario toca cualquier control.
- **Escenario:** activar "Only significant" → cerrar la ventana → reabrir → el árbol sigue
  filtrado por significancia pero el checkbox aparece desmarcado.
- **Fix aplicado:** `RangeDiffViewModel.options` (nuevo getter) + `_sync_options_from_vm()`
  en la ventana (con `blockSignals` en los 5 checkboxes + el spinbox), llamado en `__init__`
  antes de `emit_current_state()`.
- **Regresión:** `tests/test_range_diff_viewmodel.py::test_options_property_reflects_set_options`
  (automatizado). El escenario completo de reabrir la ventana se verificó con un smoke test
  manual (2 instancias de `RangeDiffWindow` sobre el mismo VM) — **no** se dejó como test
  automatizado: es el único test de este repo que construye una `QMainWindow` real, y se
  descubrió que colgaba de forma reproducible al correr después de los ~600 tests restantes
  de la suite (probablemente agotamiento de handles nativos de Windows por ventanas
  `WA_DeleteOnClose` nunca destruidas de verdad sin un event loop corriendo). Ver nota en
  [testing.md](testing.md).

### B-14 🟡 CONFIRMADO — Árbol de resultados sin orden por columna (siempre orden por score) ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py` — `setSortingEnabled` nunca se llama sobre `self.tree`.
- **Qué:** clicar un header de columna no hacía nada; el árbol siempre reflejaba el orden de
  `RangeDiffReport.visible()` (score descendente, `services/range_diff.py:107-109`).
- **Fix aplicado:** `self.tree.setSortingEnabled(True)` + `_RangeDiffTreeItem(QTreeWidgetItem)`
  con `__lt__` sobreescrito comparando un rol numérico (`_SORT_KEY_ROLE = Qt.UserRole + 10`)
  en vez del texto formateado — commit `de4c403`.
- **Regresión:** cubierto por el smoke manual de la ventana (construcción de `QTreeWidgetItem`
  no requiere `QMainWindow`, verificado directamente). Suite completa sin regresiones.

### B-15 🟡 CONFIRMADO — Reconstrucción completa del árbol en cada toggle de filtro (perf) ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py::_on_visible` (~L260-303) — `self.tree.clear()` +
  reconstruye cada `QTreeWidgetItem` desde cero en cada emisión de `visible_changed`.
- **Qué:** cada checkbox tocado, o cada tick de `min_frames_spin` (con scroll del mouse,
  ~47 emisiones de `valueChanged` al pasar de 3→50), disparaba un rebuild completo del árbol.
- **Fix aplicado:** split `_build_full_tree(report)` (caro, solo corre en un `report_changed`
  genuinamente nuevo) vs. `_apply_visibility(items)`/`_on_visible` (barato, solo `setHidden()`
  sobre items ya construidos, cacheados en `_built_top_items`/`_built_child_items`). Requirió
  extender `RangeDiffViewModel.emit_current_state()` para re-emitir también `report_changed`
  (antes solo emitía `visible_changed`) — sin esto el árbol de una ventana reabierta quedaba
  vacío. Commit `de4c403`.
- **Regresión:** cubierto por `tests/test_range_diff_viewmodel.py` (emisión de `report_changed`)
  + smoke manual (toggle de filtro no reconstruye items ya vistos). Suite completa sin regresiones.

### B-16 🟡 CONFIRMADO — Semántica de los checkboxes de filtro ambigua, sin tooltip ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py:112-119`.
- **Qué:** `chk_same_oscillation`/`chk_counters` marcados = **ocultar** esa categoría
  (`ignore_*=True`); `chk_presence` marcado = **mostrar** cambios de presencia
  (`include_presence=True`) — comportamiento opuesto sin indicación visual.
- **Fix aplicado:** tooltip agregado a los 4 checkboxes restantes explicando show-vs-hide —
  commit `de4c403`.

### B-17 🟡 CONFIRMADO — DBC hint solo como tooltip en la fila de ID, sin columna visible ni por-byte ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py:278-279` (`top.setToolTip(0, id_diff.dbc_hint)`).
- **Qué:** el hint de DBC no tenía columna dedicada, y era un string combinado de TODOS los
  bytes cambiados de ese ID, nunca desglosado por byte.
- **Fix aplicado:** nueva columna visible `range_diff_col_signal` + `dbc_hint_for_byte()` en
  `services/range_diff.py` (`return _dbc_hint_for_id(dbc_manager, can_id, {byte_index})`) para
  desglosar el hint por byte individual en las filas hijas — commit `de4c403`.

### B-18 🟡 CONFIRMADO — Export CSV sin manejo de errores ni confirmación de éxito ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py::_export_csv` (~L338-342);
  `services/range_diff.py::export_range_diff_csv` (352-359).
- **Qué:** ninguno de los dos tenía `try/except`; un path sin permisos o archivo bloqueado
  lanzaba una excepción no capturada a través del slot de Qt, sin diálogo de error.
- **Fix aplicado:** `try/except` alrededor de la escritura + `QMessageBox` de error/éxito —
  commit `de4c403`.

### B-19 🟡 PLAUSIBLE — Cerrar la ventana no espera al thread de comparación en curso ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py::closeEvent` (~L344-346) solo llamaba `vm.cancel()`,
  nunca `vm.shutdown()`.
- **Qué:** como el VM sobrevive al cierre de ventana (singleton), cerrar mientras corre un
  "Comparar" dejaba el thread terminando en segundo plano sin UI de progreso.
- **Fix aplicado:** `RangeDiffViewModel.cancel_and_wait_batch()` — más angosto que `shutdown()`:
  espera el thread de comparación BATCH en curso al cerrar la ventana, SIN tocar una sesión
  Live activa (a diferencia de `shutdown()`, que llama `stop_live()` incondicionalmente y solo
  debe usarse al cerrar la app). `closeEvent` ahora llama este método — commit `de4c403`.
- **Nota de seguimiento (no bloqueante):** `CandidateInterpretationsWindow.closeEvent` tiene la
  misma clase de gap (pide cancelación pero nunca espera el thread) — detectado en la pasada de
  pruebas integrales del 2026-07-19, no corregido todavía, ver el roadmap archivado (`docs/archive/roadmap-2026-07.md`).

### B-20 🟡 CONFIRMADO — Columna "Type" sobrecargada con dos significados distintos ✅ CORREGIDO
- **Dónde:** `views/range_diff_window.py:271` (fila de ID: mostraba `"LEN changed"`) vs. `:287`
  (fila de byte: `ChangeType` — "Const shift", "New territory", etc.).
- **Qué:** mismo header de columna, dos conceptos no relacionados según el nivel de fila.
- **Fix aplicado:** nueva columna separada `range_diff_col_len_changed` para la fila de ID —
  commit `de4c403`.

## Real-Time Analysis

### B-31 🔴 CONFIRMADO — Los CAN ID cambian de posición en cada actualización de Real-Time ✅ CORREGIDO
- **Dónde:** `views/table/table_view.py::DataTableView.__init__` (`setSortingEnabled(True)` dispara un `model.sort(0, Desc)` implícito, y la columna 0 es TS) + `viewmodels/table_model.py::sort`, que guardaba ese orden aunque el df estuviera vacío. Desde `509fc98` (fix B-09), `set_dataframe` lo reaplica en cada tick.
- **Qué:** cuando llegaba un ID nuevo o uno existente se demoraba, el orden por timestamp movía las filas, y eso hacía difícil seguir los cambios, sobre todo con "Changes only".
- **Fix aplicado:** la tabla arranca sin columna ordenada, permite limpiar el indicador (`setSortIndicatorClearable`), y `TableModel` trata `sort(-1)` como "sin orden". Cuando hay un orden activo, es estable (`maintain_order=True`): en empates se respeta el orden de primera aparición.
- **Regresión:** `tests/test_table_model.py::LiveTableSortPersistsAcrossRefreshTests` (limpiar el orden y empates estables), y los tests B-09 siguen en verde. Verificación con un log real (`Test2_MOV_state_DD422i_DM1_BOOM1.log`, 60 s, Real-Time con "Changes only"): antes se reordenaba en 599 de 600 ticks; ahora en 0 de 600, y el orden final es el de primera aparición.

### B-03 🟡 CONFIRMADO — "Only changes" ocultaba los IDs no cambiados en vez de solo atenuarlos ✅ CORREGIDO
- **Decisión de producto** (confirmada con el usuario 2026-07-20): atenuar, no ocultar —
  todos los IDs siguen visibles en la tabla; los no cambiados quedan con texto atenuado.
  El checkbox del panel de CAN IDs deja de usarse para esto (era el mecanismo que
  causaba el hide) y pasa a ser selección manual pura, independiente.
- **Fix aplicado:** `viewmodels/table_model.py::set_row_foreground_provider` — hook
  genérico de color de texto por fila (no específico de Real-Time). Wired en
  `views/realtime_analysis_window.py::_row_foreground_for_changes_only`: si "only
  changes" está activo y el ID de la fila no está en `changed_ids`, devuelve
  `theme.text_muted`; si no, `None` (color normal). `_apply_changes_only_selection`/
  `_on_changed_ids_delta` (el mecanismo de checkbox) se eliminaron por completo, junto
  con las señales `changed_ids_changed`/`changed_ids_delta_changed` (sin más
  consumidores tras el fix).
- **Primitiva compartida:** `ChangedIdsDelta`/`compute_changed_ids_delta` se extrajo de
  `services/realtime_analysis.py` a `services/monotonic_changed_set.py`
  (`ChangedSetDelta`/`compute_changed_set_delta`, ya no Real-Time-específico) — ver
  [roadmap archivado](archive/roadmap-2026-07.md) § primitiva "conjunto de cambiados monotónico". Sigue sin
  consumidor activo tras este fix (la distinción "creció vs. reset" ya no hace falta
  para atenuar), pero queda lista para AN3 (Matrix Live de Analyze Data), que sí la
  necesitará para decidir "agregar celdas nuevas" vs. "reconstruir todo".

### B-05 🔴 CONFIRMADO — Colisión de clave al reconfigurar mux corrompe stats en vivo silenciosamente ✅ CORREGIDO
- **Dónde:** `viewmodels/real_time_analysis_viewmodel.py::_reset_change_baseline` (276-299,
  llamado desde `set_mux_configuration` vía `reset_change_detection`, 241-258).
- **Qué:** al angostar/ensanchar la selección de bytes de mux, dos entradas antes distintas
  (mismo ID/LEN, distinto byte de mux) pueden mapear a la **misma** `new_key` — la segunda
  **sobrescribe** a la primera en `self._entries` (línea 299). La sobrescrita nunca se saca de
  `_id_to_entries` (nunca podado en todo el archivo) — queda congelada (ya no recibe más
  `ingest_df`) pero **sigue incluida para siempre** en `_aggregate_unique_counts` de ese CAN ID
  (`services/realtime_analysis.py:174-181`, sin guarda de "está viva"), sembrando un valor
  fantasma que se suma para siempre al conteo de "unique values per byte" del panel de
  detalles — **sin ningún indicio visual de que pasó**. Acotado: `_aggregate_frame_period`
  (:156-171) sí tiene guarda (`period_count <= 0: continue`) y el fantasma queda con
  `period_count=0` para siempre, así que el período/ΔT **no** se contamina — solo el conteo de
  valores únicos por byte.
- **Escenario:** reconfigurar mux con streaming activo de forma que dos entradas colisionen
  → el panel de detalles muestra un conteo de "valores únicos por byte" inflado de forma
  permanente para ese ID (el período sigue correcto), sin error ni aviso.
- **Fix aplicado:** nueva función pura `rekey_live_entries()` en
  `services/realtime_analysis.py` — dos pasadas: (1) saca todas las entradas de `entries` por
  su clave vieja antes de insertar ninguna (evita que una clave vieja coincida por accidente
  con la clave nueva de otra entrada aún no procesada), (2) inserta por `new_key` llevando un
  set de claves ya vistas; en colisión, descarta explícitamente al perdedor de
  `id_to_entries` también (no solo de `entries`). `_reset_change_baseline` ahora arma la
  lista `pending` y delega en esta función.
- **Regresión:** `tests/test_realtime_analysis.py::RekeyLiveEntriesTests` (5 tests: sin
  colisión, colisión 2-way, colisión 3-way, no contamina `_aggregate_unique_counts`, IDs no
  relacionados no se afectan). Suite completa: 609 tests OK.

### B-06 🟠 CONFIRMADO — Panel de detalles queda bloqueado permanentemente tras un clic en la tabla ✅ CORREGIDO
- **Dónde:** `views/realtime_analysis_window.py:71-73` (`_details_row`/`_details_can_id` init
  a `None`) — nada en el archivo los resetea a `None` después. `_refresh_details` (250-261)
  prioriza `_details_row` si es truthy.
- **Qué:** tras un solo clic en cualquier fila (`_on_table_interaction`, 241-248),
  `_details_row` queda truthy para siempre. Marcar/desmarcar IDs en el panel lateral sigue
  actualizando `_selected_ids` y llamando `_refresh_details()`, pero esa rama queda
  **inalcanzable por el resto de la sesión** — no hay forma de "limpiar selección" y volver
  al modo dirigido-por-panel.
- **Escenario:** clic en una fila de la tabla → desde ahí, marcar/desmarcar IDs en el panel
  no vuelve a afectar el panel de detalles hasta clicar otra fila distinta.
- **Fix aplicado:** botón **"Clear selection"** junto al header "Details"
  (`btn_clear_details_selection`) → `_clear_details_selection()` resetea `_details_row`/
  `_details_can_id` a `None` y refresca.
- **Regresión:** `tests/test_real_time_analysis_viewmodel.py::DetailsLookupIndependenceTests`
  (confirma que `details_data_for_row`/`details_data_for_selection` no se pisan) + smoke test
  manual del comportamiento real de la ventana (no automatizado, ver nota en
  [testing.md](testing.md) sobre construir `QMainWindow` en la suite).

### B-07 🟠 CONFIRMADO — `highlight_hold` no se aplica de forma independiente de `refresh_interval` ✅ CORREGIDO
- **Dónde:** un solo `QTimer` (`real_time_analysis_viewmodel.py:71-74`) maneja tanto el
  refresco de UI como la expiración de highlights (`_emit_if_dirty`→`_clear_expired_highlights`,
  333-359); `set_refresh_interval_ms` (227-232) reconfigura ese mismo timer.
- **Qué:** si `refresh_interval` (hasta 5000ms) es mayor que `highlight_hold` (mínimo 100ms),
  un byte resaltado no se re-chequea/expira hasta el próximo tick del timer compartido — hasta
  5 segundos después, no los ~100ms configurados. Los dos controles se presentan como
  independientes en la UI pero están acoplados por el mismo timer.
- **Escenario:** `refresh_interval=2000ms`, `highlight_hold=100ms` → el highlight visualmente
  dura ~2s, no ~100ms.
- **Fix aplicado:** `_highlight_expiry_timer` — `QTimer` separado, cadencia fija de 100ms
  (`_HIGHLIGHT_EXPIRY_CHECK_MS`), independiente de `_refresh_timer`/`refresh_interval_ms`.
  `_emit_if_dirty` ya no llama `_clear_expired_highlights` (ahora la llama
  `_check_highlight_expiry`, en su propio timer, y emite la vista si algo expiró). Efecto
  secundario positivo: con `refresh_interval` rápido (10ms) ya no se re-escanean todas las
  entradas en cada tick — la cadencia de expiración quedó fija en 100ms sin importar qué tan
  rápido esté configurado el refresco.
- **Regresión:** `tests/test_real_time_analysis_viewmodel.py::HighlightExpiryTimerIndependenceTests`
  (3 tests: dos timers distintos, cambiar `refresh_interval` no toca la cadencia de expiración
  y viceversa). Suite completa: 617 tests OK.

### B-08 🟡 CONFIRMADO — El auto-check de "changed" sobrescribe un desmarcado manual del usuario ✅ CORREGIDO
- **Dónde:** `views/realtime_analysis_window.py:222-230` (`_on_changed_ids_delta`) →
  `views/widgets/can_id_panel.py:200-215` (`check_ids`, fuerza-marca cualquier ID que entra
  a `changed_ids`, nunca desmarca).
- **Qué:** si el usuario desmarca manualmente un ID (queriendo ocultarlo permanentemente) y
  ese ID **luego** empieza a cambiar por primera vez, se re-marca automáticamente,
  sobrescribiendo la intención del usuario sin aviso. Distinto de B-03 (ese es sobre ocultar
  vs. desmarcar los que nunca cambiaron; este es sobre pisar una decisión manual explícita).
- **Escenario:** desmarcar el ID X (aún no había cambiado) → X empieza a cambiar → X se
  re-marca solo, ignorando el desmarcado previo.
- **Fix aplicado:** `CanIdPanelWidget._manually_unchecked: set[str]` — poblado por
  `_track_manual_uncheck`, conectado a `itemChanged` (fiable como proxy de "clic real del
  usuario" porque toda mutación programática ya envuelve sus cambios en `blockSignals`).
  `check_ids()` ahora resta `_manually_unchecked` del conjunto a marcar.
- **Regresión:** 4 tests (`test_check_ids_skips_a_manually_unchecked_id` y relacionados)
  corridos como módulo suelto **fuera** de `tests/` (ver nota ⚠️ en [testing.md](testing.md) —
  construir un `CanIdPanelWidget`, un `QWidget` liviano sin ventana, también cuelga bajo
  `unittest discover` pese a no ser una `QMainWindow`). Suite automatizada: 617 tests OK
  (sin cambio, este archivo no forma parte de `tests/`).

### B-09 🟡 CONFIRMADO — El orden por columna de la tabla se descarta en cada tick de refresco ✅ CORREGIDO
- **Dónde:** `views/table/table_view.py:14` (`setSortingEnabled(True)`) vs.
  `viewmodels/table_viewmodel.py:22-29`/`viewmodels/table_model.py:55-61` — cada refresco
  sobrescribe `self._df` con el orden de inserción del VM, sin reaplicar el sort elegido.
- **Qué:** clicar un header para ordenar funciona por un instante y luego revierte en el
  siguiente tick — efectivamente roto para una sesión en vivo.
- **Fix aplicado:** `TableModel` recuerda `_sort_column`/`_sort_descending` (poblados en
  `sort()`) y los reaplica en `set_dataframe()` — **solo cuando `optimize_append=False`**
  (el caso de Real-Time): ese modo nunca toma el camino rápido de inserción en la cola
  (`beginInsertRows`), así que reordenar `new_df` antes de las ramas de reemplazo/reset es
  seguro. La tabla principal (`optimize_append=True`, default) queda intacta a propósito —
  su camino rápido de apéndice asume el orden original del VM.
- **Regresión:** `tests/test_table_model.py` (4 tests: sobrevive un refresco de igual altura,
  sobrevive un cambio de cantidad de filas, sin sort activo no toca el orden del VM, y la
  tabla con `optimize_append=True` NO reaplica sort). `TableModel` es un `QAbstractTableModel`
  (QObject, no widget) — seguro dentro de `tests/` a diferencia de B-08/B-13. Suite completa:
  621 tests OK.

### B-10 🟡 CONFIRMADO — Texto de bits se desborda sobre celdas vecinas (sin recorte) ✅ CORREGIDO
- **Dónde:** `views/table/data_bytes_highlight_delegate.py::paint` — `drawText` sin
  `setClipRect`/clip a `text_rect`.
- **Qué:** en modo `show_bits`, el texto (~64 caracteres + espacios) es ~3x más largo que en
  modo hex (~23 caracteres); si la columna DATA está dimensionada para hex, el texto binario
  se dibuja fuera del área de la celda, sobre celdas vecinas.
- **Fix aplicado:** `painter.setClipRect(opt.rect)` justo después de `painter.save()` (se
  restaura solo con `painter.restore()` al final).
- **Regresión:** smoke test manual a nivel de píxel (`QPixmap`+`QStandardItemModel` real),
  celda angosta de 60px con texto de 8 bytes en modo bits — confirmado que ningún píxel se
  pinta fuera del rect de la celda. No forma parte de `tests/` (requiere un `QListWidget`
  para `opt.widget`, ver nota ⚠️ sobre widgets en [testing.md](testing.md)).

### B-11 🟡 CONFIRMADO — "Reset change detection" hace más de lo que su nombre indica, sin aviso ✅ CORREGIDO
- **Dónde:** `viewmodels/real_time_analysis_viewmodel.py::_reset_change_baseline` (286-291);
  botón siempre habilitado, sin tooltip (`views/realtime_analysis_window.py`, `btn_reset`).
- **Qué:** el botón borra incondicionalmente las estadísticas de período (min/max/avg) y los
  contadores de "unique values" por byte de **todos** los IDs trackeados, incluso con
  `detect_changes` **desactivado** — no solo el baseline de detección de cambios como sugiere
  la etiqueta.
- **Fix aplicado:** tooltip agregado a `btn_reset` explicando el alcance real — commit `dca9d5f`.

### B-12 🟡 CONFIRMADO — Strings hardcodeados en inglés sobrescriben el texto localizado ✅ CORREGIDO
- **Dónde:** `real_time_analysis_viewmodel.py::mux_configuration_summary` (97-99, `"No MUX"`/
  `f"{n} rule(s)"`), `_change_summary_text` (361-368, `"Change detection OFF"`/
  `f"Changed IDs: {x}/{y} (filtered)"`), panel de detalles (`views/realtime_analysis_window.py:275-278`).
- **Qué:** estos strings evitaban `get_text()`/`ui_text.py` que usa el resto de la ventana. El
  texto localizado solo duraba hasta el primer cambio de estado, que lo sobrescribía en inglés.
- **Fix aplicado:** `mux_configuration_summary()` y `_change_summary_text()` ahora usan
  `get_text()` con nuevas claves en `ui_text.py` en vez de strings hardcodeados — commit
  `dca9d5f`.
- **Regresión:** cubierto por `tests/test_real_time_analysis_viewmodel.py`. Suite completa
  sin regresiones.

## Candidate Interpretations

### B-04 🟡 CONFIRMADO — Barra de menú visible duplicaba el nuevo toolbar de iconos ✅ CORREGIDO
- **Dónde:** `views/candidate_interpretations_window.py` (`_setup_menu_bar` construía
  menús "Settings"/"Tools" visibles a la vez que `_setup_toolbar` los replicaba en iconos).
- **Qué:** tras mover las acciones al `QToolBar` de iconos, la barra de menú tradicional
  seguía visible arriba → dos superficies de navegación redundantes.
- **Fix aplicado:** `self.menuBar().setVisible(False)` tras `_setup_menu_bar()` (se mantiene
  la llamada para registrar los shortcuts de `QAction`, contexto `Qt::WindowShortcut`,
  como la ventana principal) + Export/Import Tags agregados al toolbar (iconos
  `download`/`upload`). Verificado headless: `menubar_visible: False`, 5 acciones en toolbar.

### Constraint Search ("Value at Time Search")

### B-21 🟠 CONFIRMADO — Sin progreso/cancelación; puede congelar la UI ✅ CORREGIDO
- **Dónde:** `views/candidate_constraint_search.py::_run_search` (184-243) — loop síncrono
  sobre el hilo de la GUI, sin `QThread`, sin `processEvents`, sin barra de progreso.
- **Qué:** con muchos candidatos ya calculados, esto podía congelar visiblemente la UI sin
  ningún feedback.
- **Fix aplicado:** reescritura completa como `services/constraint_search.py` (núcleo Qt-free:
  `search_candidates()`) + `ConstraintSearchWorker`/`ConstraintSearchViewModel` (`QThread`,
  mismo patrón que Diff Analyzer) + `EtaProgressDialog` en la ventana — commit `f7ae1ec`.
- **Regresión:** `tests/test_constraint_search.py` (21 tests) + `tests/test_constraint_search_viewmodel.py`
  (5 tests) — archivo que antes tenía **cero** tests. Suite completa sin regresiones.

### B-22 🟡 CONFIRMADO — Clamping silencioso de valores fuera de rango ✅ CORREGIDO
- **Dónde:** `views/candidate_constraint_search.py::_parse_constraints:180`
  (`norm_val = max(0.0, min(1.0, norm_val))`).
- **Qué:** un usuario que tipea "75" (pensando porcentaje) o "42" (pensando valor crudo)
  obtenía silenciosamente 1.0, sin ninguna indicación de que su valor fue reinterpretado.
- **Fix aplicado:** `services/constraint_search.py::clamp_target()` devuelve si hubo clamping;
  la ventana muestra un `QMessageBox` de aviso ("Value(s) clamped") antes de correr la
  búsqueda — commit `f7ae1ec`.

### B-23 🟡 CONFIRMADO — Grabaciones que cruzan medianoche mal manejadas en modo reloj ✅ CORREGIDO
- **Dónde:** `views/candidate_constraint_search.py::_time_to_abs` (42-52) — reconstruía el
  timestamp absoluto sobre el **mismo día calendario** del inicio de la grabación, sin campo
  de fecha.
- **Qué:** para un log que cruza medianoche, no había forma de apuntar a una hora del "día 2".
- **Fix aplicado:** `time_to_abs(..., day_offset=0)` en `services/constraint_search.py` +
  columna "Day" (`QSpinBox`) en la tabla de restricciones — commit `f7ae1ec`.

### B-24 🟡 CONFIRMADO — Exclusiones estructurales invisibles para el usuario ✅ CORREGIDO
- **Dónde:** `views/candidate_constraint_search.py:205-210`/`:214-218` — candidatos con <2
  muestras, varianza cero, o restricciones fuera de la ventana de precisión, descartados sin
  contador/resumen.
- **Qué:** no había ningún "N candidatos excluidos porque..." — el usuario no sabía por qué un
  candidato esperado no aparecía en los resultados.
- **Fix aplicado:** `search_candidates()` devuelve `(list[SearchResult], SearchExclusions)`
  (con propiedad `.total`); la ventana muestra el resumen de exclusiones vía `QMessageBox` y
  un mensaje explícito cuando la lista queda vacía — commit `f7ae1ec`.

## Analyze Data

### B-26 🟠 CONFIRMADO — Panel de estadísticas queda vacío al reabrir la ventana ✅ CORREGIDO
- **Dónde:** `views/analyze_data_window.py::__init__` (61-67) llama `_apply_byte_selection()`
  luego `self._vm.set_dataframe(getattr(self._vm, "_df", None))`; el guard de refresco de
  `set_dataframe()` (`viewmodels/analyze_data_viewmodel.py:63-64`) da `False` porque
  df/id/watermark no cambiaron → `_full_refresh()` (y por ende `summary_changed`) nunca se
  dispara. `_set_can_ids()` repuebla la lista con `blockSignals` (`:309-319`), así que
  `_on_can_id_changed` tampoco se dispara.
- **Qué:** la ventana es single-instance con `WA_DeleteOnClose` (se destruye y recrea en cada
  apertura, `views/base_window_manager.py:18-28`). Al reabrir: el **plot** se redibuja bien
  (porque `_apply_byte_selection()` re-emite `plot_changed` desde el acumulador ya vivo), pero
  el grid de **Statistics queda vacío** hasta que el usuario cambia CAN ID/mux/bytes o llega
  streaming nuevo — fácil de no notar porque el plot sí funciona.
- **Escenario:** abrir Analyze Data, ver stats → cerrar → reabrir → plot con datos, stats vacío.
- **Fix aplicado:** `AnalyzeDataViewModel.emit_current_state()` (re-emite `summary_changed` +
  `plot_changed` desde el acumulador ya vivo, sin recomputar) llamado al final del `__init__`
  de la ventana, mismo patrón que B-01 en Range Diff.
- **Regresión:** `tests/test_analyze_data_viewmodel.py` (nuevo archivo, 2 tests). Suite
  completa: 611 tests OK.

### B-27 🟡 CONFIRMADO — Selección de bytes/mux no persiste entre aperturas ✅ CORREGIDO
- **Dónde:** `views/analyze_data_window.py:214-215` (`setChecked(True)` para los 8 checkboxes
  en cada `_setup_toolbar()`).
- **Qué:** como la ventana se destruye/recrea (ver B-26), cada apertura resetea la selección a
  "todos los bytes" sin importar lo que el VM tenía acumulado como `_selected_bytes` de la
  sesión anterior. No hay hook a `session_state.py` como sí tienen otras configuraciones.
- **Fix aplicado:** `AnalyzeDataViewModel.selected_bytes` (nuevo getter) — los checkboxes se
  inicializan con `idx in self._vm.selected_bytes` en vez de `setChecked(True)` hardcodeado.
  Junto con esto se aprovechó para revertir los checkboxes de popup a **visibles inline en el
  toolbar** (decisión del usuario 2026-07-18, ver [roadmap archivado](archive/roadmap-2026-07.md)) — el botón
  `_btn_bytes`/`QMenu`/`QWidgetAction` se eliminó, quedan botones "All"/"None" + 8 `QCheckBox`
  directos en la toolbar.
- **Regresión:** `tests/test_analyze_data_viewmodel.py::test_selected_bytes_property_reflects_set_selected_bytes`
  + smoke test manual verificando que los checkboxes son widgets visibles (no popup) y
  reflejan el estado del VM tras "reabrir". Suite completa: 613 tests OK.

### B-28 ✅ RESUELTO POR DISEÑO — El label del botón "Bytes" nunca reflejaba la selección activa
- **Dónde (ya no existe):** `_btn_bytes` (popup) fue eliminado al revertir a checkboxes
  visibles inline (ver B-27). Cada checkbox ahora muestra su propio estado directamente — no
  hay label resumen que pueda desincronizarse.

### B-29 🟡 PLAUSIBLE — Chunks fuera de orden podrían perder contribución silenciosamente ✅ CARACTERIZADO
- **Dónde:** `services/analyze_data.py:265,282` (`ts_f >= self._last_ts` /
  `ts_f >= self._last_byte_change_ts[i]` como guardas monotónicas).
- **Qué:** si un chunk nuevo llega con timestamps anteriores a los ya procesados (posible con
  timestamp skew entre buses), esas filas se saltan silenciosamente en period-stats y
  byte-change-stats. Precisado con tests: `Frames`/`Distinct Payloads`/`Byte Changes` son
  **incondicionales** (cuentan la fila igual); `Mean/Min/Max Period` y `Byte Update
  Mean/Min/Max` **sí** se saltan la fila fuera de orden (no corrompen — simplemente no suman
  esa muestra); `_last_ts`/`_last_byte_change_ts` nunca retroceden. No era un bug que
  corrompiera datos, solo una omisión de muestra silenciosa — comportamiento ya razonable,
  documentado y anclado con test antes de multiplicarlo en la vista matriz.
- **Resultado:** no requirió cambio de código, solo test de caracterización — ver
  `tests/test_analyze_data.py::OutOfOrderChunkTests` (4 tests). Suite completa: 632 tests OK.

## Candidate Interpretations — hallazgo de la prueba integral 2026-07-19

### B-30 🔴 CONFIRMADO — Búsqueda por defecto no termina en un log real de tamaño típico ✅ CORREGIDO
- **Dónde:** `services/can_decoder.py::with_data_int()` (línea 17) — reconstruye la columna
  `DATA_INT` re-parseando el hex de `DATA` (`.str.slice()`+`.str.to_integer()` ×8) en vez de
  leer las columnas `D0..D7` (enteros) que el DataFrame ya trae. `decode_signal_raw()` (línea
  118) la llama **fresca en cada invocación de `decode_signal()`** — una vez por cada spec
  probado en la búsqueda de Candidate Interpretations (~32 specs por grupo `(can_id, len,
  mux)` con parámetros default: 8 start-bits × 2 byte-orders × 2 value-types), en vez de una
  vez por grupo.
- **Qué:** medido empíricamente sobre `candump-2026-07-11_153006.log` (Downloads, 4 040 230
  filas, 118 IDs): `with_data_int()` cuesta **5.32 ms/llamada** en un grupo representativo de
  ~47K filas. Con el proyectado de specs × grupos, la búsqueda default sobre los 118 IDs del
  log real **no terminó en 180s** (test cortado por timeout, 0 candidatos emitidos — no es un
  bug de corrección: una búsqueda aislada sobre 5 IDs sí encontró 100 candidatos reales en
  10.48s, confirmando que el motor funciona, solo que el costo por-spec no escala). Esto es
  la ya documentada "Item 1" del plan de perf de dataframe en `docs/archive/claude-md-2026-07.md`, ahora confirmada
  severa con datos reales, no solo en teoría.
- **Escenario:** cargar un log real de tamaño típico (~4M filas / ~100+ IDs) → abrir Candidate
  Interpretations → "Try All" con los 118 IDs marcados → la búsqueda no converge en un tiempo
  razonable, sin ningún error ni mensaje — solo la barra de progreso avanzando muy lento.
- **Fix aplicado:** `services/can_decoder.py::with_data_int()` ahora es idempotente
  (no-op si `DATA_INT` ya existe) y construye la columna desde `D0..D7` ya parseadas
  (`sum(pl.col(f"D{i}").cast(pl.UInt64) * 2**(8*i) for i in range(8))`) en vez de
  re-parsear el hex de `DATA`, con fallback al camino viejo si el DataFrame no trae
  `D0..D7`. `services/candidate_interpretations.py::_build_candidate_items()` llama
  `with_data_int(with_id_columns(mux_df))` **una vez por grupo** `(can_id, len, mux)`,
  antes del loop de specs, en vez de dejar que cada spec la reconstruya. Test dedicado
  `tests/test_can_decoder.py::WithDataIntCachingTests` (idempotencia + el camino rápido
  coincide con el resultado del re-parseo viejo). Además, la Matrix de Candidate
  Interpretations (ahora un tab, no ventana aparte) le da al usuario un camino barato
  (`build_candidate_matrix_entries`, ~ms) que ni siquiera pasa por la búsqueda cara.

---

### B-32 🟡 CONFIRMADO — Candidate Interpretations borra resultados en cada flush ✅ CORREGIDO
- **Dónde:** `viewmodels/candidate_interpretations_viewmodel.py::set_dataframe` y
  `views/candidate_interpretations_window_manager.py::_create_window`.
- **Qué:** con Candidate Interpretations abierta durante una captura, cada emisión de
  `dataframe_changed` reemplazaba el DataFrame acumulado y también vaciaba los resultados,
  aproximadamente cada 100 ms.
- **Fix aplicado:** `set_dataframe` conserva los resultados durante append; el nuevo
  `reset_dataframe` los limpia al abrir la ventana o cuando `dataframe_replaced` anuncia un
  log nuevo. El manager conecta y desconecta ambas señales.
- **Segunda parte, mismo flujo:** `views/candidate_interpretations_window.py::_set_can_ids`
  reconstruía la lista de IDs en cada `can_ids_changed` (o sea, en cada flush) y marcaba
  **todos** los IDs. Así se perdía la selección del usuario, y el siguiente "Recalcular"
  buscaba en todo el log. Ahora cada ID conocido conserva su estado. Un ID nuevo se marca solo
  si antes estaban todos marcados (`merge_checked_can_ids`), y si el conjunto de IDs no
  cambió, la lista no se reconstruye.
- **Regresión:** `tests/test_candidate_interpretations_viewmodel.py::CandidateDataframeUpdateTests`
  (un append conserva los resultados, un reset los borra) y `::MergeCheckedCanIdsTests` (la
  selección sobrevive al refresco). Verificado con un log real (`Test2_MOV_state_DD422i_DM1_BOOM1.log`):
  búsqueda sobre 181/182/183 → 84 candidatos → 100 flushes en vivo. Antes quedaban 0
  candidatos y todos los IDs marcados; ahora siguen los 84 candidatos y solo 181/182/183 marcados.

### B-33 🟡 CONFIRMADO — Cerrar Real-Time deja conexiones vivas a su ViewModel ✅ CORREGIDO
- **Dónde:** `views/realtime_analysis_window.py::__init__` (dos `lambda` y
  `set_live_dataframe` conectados a señales de `RealTimeAnalysisViewModel`).
- **Qué:** la VM vive toda la sesión y la ventana nunca desconectaba sus slots. Al cerrar la
  ventana, cada refresco posterior lanzaba `RuntimeError: Internal C++ object (QLabel)
  already deleted` y el `TableFilterViewModel` de la ventana cerrada seguía vivo y filtrando.
- **Fix aplicado:** la ventana guarda sus conexiones a la VM (sin `lambda`) y las desconecta
  en `closeEvent`. El manager tolera el cierre de la app, cuando los timers de la VM ya no
  existen (F1-03).
- **Verificación:** replay del log de campo `DD422-07/log_5.txt`: abrir, cerrar y reabrir
  Real-Time ya no produce ningún traceback (antes, decenas por segundo).

### B-34 🟡 CONFIRMADO — Los logs candump exportados no se podían volver a cargar ✅ CORREGIDO
- **Dónde:** `services/can_data_parser.py:43` (`_CANDUMP_COMPACT_PATTERN`).
- **Qué:** el writer estándar de python-can agrega el sufijo `R` o `T` a los frames,
  pero el parser de Canlytics solo aceptaba líneas terminadas después del payload.
- **Escenario:** exportar una captura como `.log` y volver a abrirla en Canlytics; el parser
  ignoraba todas las filas del archivo.
- **Fix aplicado:** el parser acepta el sufijo opcional `R`/`T` y prueba ambos casos con
  python-can — `tests/test_can_data_parser.py::ParseCandumpLineTests`.

## Notas de UX (no son bugs, registrar para el roadmap)

- ~~Sensitivity invertido~~ — resuelto de raíz: `sensitivity` se eliminó por completo
  (ver el roadmap archivado (`docs/archive/roadmap-2026-07.md`) § EPIC Candidate Interpretations, CI6). La búsqueda ahora es siempre
  exhaustiva; el filtro de score mínimo (CI2) es un número real 0.0–1.0, sin ambigüedad
  de dirección.

### B-35 🟡 CONFIRMADO — Plot conserva un callback global tras cerrar sus cursores — CORREGIDO
- **Dónde:** `views/plot/cursor_controller.py::__init__` conectaba `QApplication.paletteChanged`; `views/plot/plot_window.py::closeEvent` no lo desconectaba.
- **Qué:** `QApplication` retenía el controlador y, al cambiar el tema después de cerrar Plot, `_apply_cursor_theme()` usaba `InfiniteLine` ya destruido.
- **Escenario:** abrir Plot, cerrar la ventana y cambiar a Light/Dark; aparece `RuntimeError: Internal C++ object (InfiniteLine) already deleted` y el controlador queda retenido.
- **Fix aplicado:** `CursorController.dispose()` desconecta `paletteChanged` y detiene el timer de resnap; `PlotWindow.closeEvent` lo llama antes de cerrar. Cubierto en `tests/test_f5_07_theme_accessibility.py`; verificado cerrando Plot y alternando ambos temas sin traceback.
