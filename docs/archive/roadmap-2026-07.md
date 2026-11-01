> **Archivado (2026-11-01).** Histórico tal cual estaba fuera del repo. No es fuente de verdad: lo vigente está en `AGENTS.md`, `docs/plan.md` y `docs/architecture/`.

# ROADMAP — Canlytics

> **Ubicación:** carpeta contenedora `CAN ANALIZER/`, **fuera** del repo git
> (`CANAnalyzer/`), para no versionarse. Es el backlog de producto y la secuencia de
> trabajo. Los bugs viven en [BUGS.md](BUGS.md); el plan de pruebas en [TESTS.md](TESTS.md);
> el diseño de UI en [UI_DESIGN.md](UI_DESIGN.md); la arquitectura y convenciones en
> [CLAUDE.md](CLAUDE.md).

Leyenda esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto. Capa entre paréntesis.

---

## Orden de ejecución (secuencia maestra)

**Pendiente de aprobación del usuario para empezar.** Una sola lista, de arriba a abajo,
mezclando bugs ([BUGS.md](BUGS.md)) y features por impacto real — no por categoría. Cada
fase es un lote de trabajo relacionado (mismos archivos, límite natural de commit). El
detalle completo de cada ítem está más abajo en este documento; acá solo la secuencia.

### Fase 0 — Confianza en los datos (bugs que corrompen o esconden datos silenciosamente) ✅ COMPLETA
- [x] **B-05** Real-Time: colisión de clave al reconfigurar mux mezcla stats viejas con vivas
  (🔴 el más severo — puro, testeable sin Qt en `services/realtime_analysis.py`)
- [x] **B-26** Analyze Data: panel de stats vacío al reabrir la ventana
- [x] **B-13** Diff Analyzer: filtros desincronizados al reabrir (VM stale vs. UI en defaults)

### Fase 1 — Controles que no hacen lo que prometen visiblemente ✅ COMPLETA
- [x] **B-06** Real-Time: panel de detalles bloqueado tras un clic en la tabla
- [x] **B-07** Real-Time: `highlight_hold` no se aplica independiente de `refresh_interval`
- [x] **B-08** Real-Time: auto-check sobrescribe un desmarcado manual del usuario
- [x] **B-09** Real-Time: orden de columna de la tabla se descarta en cada refresco
- [x] **B-10** Real-Time: texto de bits se desborda sin recorte (`show_bits`)
- [x] **B-27** + **revertir checkboxes** Analyze Data: bytes vuelven a checkboxes visibles
  (no popup); selección no persistía entre aperturas — ambos en el mismo archivo/área

### Fase 2 — Analyze Data: ganancia rápida de percepción ✅ COMPLETA
- [x] Cache de acumulador por CAN ID (barato; instantáneo desde la 2ª visita — **no** arregla
  la 1ª visita a un ID, ver Fase 6)
- [x] **B-29** test de regresión: chunks fuera de orden no deben perder contribución (escribir
  antes de la Fase 6, que multiplica esta lógica en la vista matriz)

### Fase 3 — Candidate Interpretations: filtros de vista, display-time, sin tocar el motor ✅ COMPLETA
- [x] **CI6** quitar `sensitivity` del service/viewmodel/UI (búsqueda siempre fuerza bruta)
- [x] **CI1** ordenar por score ("CAN ID → score" default, o score puro)
- [x] **CI2** filtro de score mínimo (reemplaza a sensitivity, cuantitativo, en vivo)
- [x] **CI3** filtro de endianness (LE/BE)
- [x] **CI4** filtro de longitud/multibyte (ocultar parciales de 8-bit)

### Fase 4 — Diff Analyzer Fase 2 (la feature grande; orden interno por dependencia)
- [x] **B-02** fix de timestamps A/B (hacerlo primero — todo lo demás toca la misma ventana)
- [x] `RangeTimeline` gana eje de tiempo real (ticks + labels por timezone) — hallazgo del
  usuario 2026-07-19: la barra no mostraba hora/fecha en absoluto, solo el histograma sin eje.
- [x] Rename Range Diff → Diff Analyzer (solo texto visible al usuario — título, ribbon, menú,
  export CSV; se decidió **no** renombrar clases/archivos internos por riesgo/beneficio: cero
  ganancia funcional, alto costo mecánico tocando ~10 archivos. `services/range_diff.py`
  se queda como está — es el núcleo Qt-free, su nombre describe el algoritmo, no la feature.)
- [x] `LiveByteAccumulator` + refactor `_diff_bytes` compartido + tests de invariante
  (`tests/test_range_diff_live.py`: feed incremental == `observe_byte` en cada prefijo,
  para constante/oscilación/contador con wrap/toggle/vacío)
- [x] Modo Live en el ViewModel (`capture_live_baseline`/`stop_live`, watermark,
  `QTimer` de 1s vía `_live_tick`; `reset_dataframe`/`run`/`shutdown` detienen el live)
- [x] `QTabWidget`: tab Plot con byte auto-ploteado + bandas A/B resaltadas
  (`extract_byte_series` + 2 `pg.LinearRegionItem`, colores accent/error como el timeline)
- [x] Toggle "Live" en la vista (deshabilita picker manual/Comparar; labels B muestran
  "(live)" y crecen con cada tick; el toggle y el tab Plot se re-sincronizan al reabrir
  la ventana si el VM sigue en live)

**Fase 4 completa** — pendiente de que el usuario la pruebe en vivo (streaming real)
antes de darla por cerrada del todo; ver nota en BUGS.md/sesión.

### Fase 5 — Handoff P1 (simplificado: sin sembrar por byte, solo acotar ID + ranking) — ✅ COMPLETA
- [x] **P1.1** handoff Diff Analyzer → Candidate (acción "Analizar este CAN ID como
  señal..." en el árbol de resultados; `CandidateInterpretationsWindow.
  set_checked_can_ids()` + `WindowManager.open_window_for_can_id()`)
- [x] **P1.2** handoff inverso Candidate → confirmar (plotear ya existía; se agregó
  "Confirmar en Real-Time Analysis..." al menú del plot embebido, misma mecánica
  con `RealTimeAnalysisWindow.set_checked_can_ids()` reusando `CanIdPanelWidget`)
- [x] botón "Comparar desde ahora" en Real-Time como atajo hacia Diff Analyzer Live
  (`RangeDiffWindowManager.open_window_live()`; wiring post-construcción en
  `main_window.py` para romper el ciclo de 3 managers RealTime→RangeDiff→Candidate→RealTime)

Los tres handoffs verificados con smoke scripts end-to-end (fuera de `tests/` por
construir ventanas Qt reales) + suite completa (653 tests) en verde.

### Fase 6 — Trabajo estructural más pesado/riesgoso
- [x] Vectorizar `AnalyzeDataAccumulator.feed()` con Polars/numpy (arregla la 1ª visita a
  un ID, no solo la repetición — ver Fase 2). Delegado a `refactor-architect`; verificado
  con 250 escenarios aleatorios contra la implementación anterior (0 discrepancias) +
  test de invariancia por chunking en `tests/test_analyze_data.py`. ~2-2.4x más rápido
  en un `feed()` único de 200k filas.
- [x] **CI5** agrupar candidatos solapados por región (paso previo a P2). Se evitó el
  cambio `QListWidget`→`QTreeWidget` que el roadmap marcaba como probablemente
  necesario: `group_overlapping_candidates()` (services) + checkbox "Group overlapping"
  (display-time) que colapsa la lista plana a representantes con sufijo "(+N more)",
  reusando selección/plot/detalles tal cual.
- [x] **P2** primitiva de correlación multi-byte: `services/multi_byte_detection.py`
  (P2.1) detecta alineación de acarreo (byte bajo hace wrap → byte alto cambia ±1 en
  la misma transición), validado empíricamente (30 seeds aleatorios, 0 falsos
  positivos + contadores 16-bit reales). P2.2 conectado a Candidate Interpretations:
  cada candidato de 8 bits alineado a byte muestra "Multi-byte Hint" en el detalle si
  se alinea con su vecino. P2.3 ✅ (2026-07-20): Diff Analyzer consume el mismo núcleo
  — `ByteDiff.multi_byte_hint`, calculado en `_diff_bytes` (compartido por batch y
  Live) a partir de `ByteObservation.raw` de ambas ventanas concatenadas; columna
  "Multi-byte" nueva en el árbol + export CSV.
- [x] **AN1** vista matriz de Analyze: grid de mini-plots, uno por CAN ID ya cacheado
  (reusa `_accumulator_cache` del precompute — no hizo falta restructurar a
  `dict[str, Accumulator]` en paralelo aparte, ya existía tras la Fase 6 de precompute),
  cada celda plotea el byte más activo (`most_active_byte()`); click en una celda
  selecciona ese ID y vuelve al tab Signal.
- [x] **AN2** checkbox "Hide signals with no movement" (`has_any_change()` por
  acumulador) — filtra display-time, sin re-scan.
- [x] **AN3** ✅ (2026-07-20) modo Live en la Matriz: checkbox "Live" junto a "Hide flat"
  (`AnalyzeDataViewModel.set_matrix_live`/`_matrix_live_ids`, monotonic set vía
  `services/monotonic_changed_set.py`). Un CAN ID que empieza a moverse se agrega
  reactivamente (`build_matrix_entries_for_id`, chequeo barato por-ID en vez del
  `group_by` completo de `build_matrix_summary`); un rebuild completo resincroniza
  el set vía `compute_changed_set_delta` (loguea si se achica).
- [x] **AN4** (alcance reducido) no hizo falta restructurar `AnalyzeDataViewModel` — el
  precompute de la Fase 6 ya deja `_accumulator_cache: dict[str, Accumulator]` con
  todos los IDs en paralelo; `get_matrix_entries()` solo lee de ahí. DBC-decodificado
  en la matriz sigue sin plomería (fuera de alcance, como ya anotaba el roadmap).
- [x] **PERF1** ✅ (2026-07-20) `B0..B7` fuera del esquema (redundante con `DATA`+`D0..D7`,
  ~493MB de puro desperdicio en el log real). `D0..D7` se conserva residente (lo usan
  mux/stats/signal_coverage) — la virtualización de ventanas con millones de filas sigue
  pendiente, ver "EPIC Performance y memoria en logs grandes" más abajo -- ítems 2, 4, 8
  ✅ hechos 2026-07-20; ítems 6-7 evaluados, sin acción requerida por ahora; ítem 3
  (schema base + bytes lazy más agresivo) no hecho en esa forma, PERF1 cubre lo esencial.

### Fase 7 — Pulido / prioridad baja (no bloquea nada de lo anterior)
- [x] **Modalidad de diálogos: `ApplicationModal` → `WindowModal` en toda la app.** ✅
  (2026-07-20) Los 13 `QDialog` + `EtaProgressDialog` + el `QProgressDialog` de carga
  de log ahora usan `Qt.WindowModal`; `mux_detection_window.py` deliberadamente sin
  tocar (feature deshabilitada). Contexto original del pedido, con 2 ejemplos
  concretos reportados en vivo:
  1. `EtaProgressDialog` (usa `Qt.ApplicationModal` explícito) bloquea TODA la app
     mientras corre — Candidate Interpretations, Diff Analyzer, Signal Coverage y
     Analyze Data precompute no deberían congelar la ventana principal ni otras
     ventanas secundarias abiertas, solo la suya.
  2. `SignalSettingsDialog` (abierta desde `PlotWindow._add_signal`/`_edit_signal`,
     `views/plot/plot_window.py:757,791`) — el usuario reportó: abre Plot, hace
     "Add new signal", y no puede volver a la ventana principal mientras el diálogo
     de configuración está abierto, aunque esté parenteado correctamente al plot.
     Causa raíz: **`QDialog.exec()` es `Qt.ApplicationModal` por defecto** si no se
     llama `setWindowModality(Qt.WindowModal)` antes — no es un bug aislado de este
     diálogo, es el comportamiento por defecto de Qt para cualquier `QDialog` mostrado
     con `.exec()`.
  - **Alcance real (barrido 2026-07-19):** 13 subclases de `QDialog` en `views/`
    (`dbc_manager_dialog.py`, `about_dialog.py`, `candidate_filters_dialog.py`,
    `connection_dialog.py`, `cursor_settings_dialog.py`, `graph_settings_dialog.py`,
    `log_timezone_dialog.py`, `mux_configuration_dialog.py`,
    `signal_coverage_filters_dialog.py`, `time_config_dialog.py`,
    `time_filter_dialog.py`, `derived_signal_dialog.py`, `signal_settings_dialog.py`)
    — todas application-modal por defecto salvo que se demuestre lo contrario. Además,
    `main_window.py:302` (carga de log) y `mux_detection_window.py:461` (deshabilitada,
    no tocar) ya ponen `Qt.ApplicationModal` explícito.
  - **Fix propuesto:** revisar cada uno de los 13 + los 2 explícitos; para cada uno,
    `self.setWindowModality(Qt.WindowModal)` en su `__init__` (o antes de `.exec()`
    en el llamador) salvo que haya una razón real para bloquear toda la app (ninguno
    de los explícitos parece necesitarlo — ni carga de log ni progreso de análisis
    justifican congelar OTRAS ventanas ya abiertas). Para `EtaProgressDialog`, al ser
    compartido, arregla las 4 ventanas que lo usan con una sola línea.
  - **Verificación:** por cada diálogo corregido, smoke test abriendo 2 ventanas (la
    que lo lanza + otra independiente, ej. main window) y confirmando que la segunda
    sigue interactiva mientras el diálogo/progreso está abierto.
- [x] Diff Analyzer: **B-14** (sort por columna, `_SORT_KEY_ROLE` numérico/CAN-ID en
  vez de comparación de texto), **B-15** (`_build_full_tree` solo en reporte nuevo,
  `_apply_visibility` solo hace `setHidden` en cada toggle de filtro), **B-16**
  (tooltips en los 4 checkboxes restantes), **B-17** (`dbc_hint_for_byte` + columna
  "Signal" visible en filas de ID y de byte), **B-18** (try/except + QMessageBox
  éxito/error en export CSV), **B-19** (`cancel_and_wait_batch()` — espera el batch
  sin tocar una sesión Live activa), **B-20** (columna "LEN changed" separada de "Type")
- [x] Real-Time: **B-11** (tooltip explicando que "Reset" limpia stats de todos los
  IDs incluso con detect_changes OFF), **B-12** (`mux_configuration_summary`/
  `_change_summary_text` ahora usan `get_text()`)
- [x] Constraint Search: **B-21** (`services/constraint_search.py` extraído Qt-free +
  `ConstraintSearchWorker`/`ConstraintSearchViewModel`, mismo patrón que Range Diff),
  **B-22** (`clamp_target()` avisa en vez de clampear en silencio), **B-23** (spinner
  "Day" por restricción, `time_to_abs(..., day_offset=)`), **B-24** (`SearchExclusions`
  desglosa por qué se excluyó cada candidato) + cobertura de tests desde cero (21 +
  5 tests nuevos, el archivo no tenía ninguno antes)
- [ ] **ID1** correlación HMI OCR ↔ serie detectada (etapa ④, futuro lejano) — no
  iniciado, fuera de alcance de esta sesión. **Además: todo el feature HMI Video/OCR
  queda congelado ("hasta nuevo aviso", pedido explícito del usuario 2026-07-19) — no
  tocar nada bajo ese path (código, tests, UI) salvo que se levante el freeze.**
- [x] **B-03** (Real-Time "only changes" hide vs. deselect) ✅ (2026-07-20) — decisión
  confirmada con el usuario: atenuar, no ocultar. Ver [BUGS.md](BUGS.md) para el detalle.

## Ideas de UX (pedido del usuario 2026-07-19, "para el futuro" — sin empezar)

Pedido explícito: "quiero más ideas como la que te acabo de dar que mejoren la
experiencia de usuario". Cada una verificada contra el código real antes de anotarla
(no son suposiciones) — barrido 2026-07-19:

- ✅ **Confirmación visible al llegar por un handoff** (2026-07-21, commit `e31cb18`).
  Los 3 handoffs P1 ahora muestran un mensaje de status bar temporal (6s) en la
  ventana destino: "Scoped to ID {id} from {source}" / "Comparing live from
  {source}" — `open_window_for_can_id`/`open_window_live` ganaron un `source=`
  opcional que cada llamador pasa con el nombre de la ventana de origen.
- ✅ **Drag-and-drop para cargar un log** (2026-07-20, commit `38d2c81`).
  `MainWindow.dragEnterEvent`/`dropEvent` aceptan `.log`/`.txt`, reusan
  `_start_log_load()` (mismo camino que `_pick_load_log`) -- drop siempre es
  "Load", no "Append".
- ✅ **DBC restore ya sigue la regla "% + ETA"** -- ya implementado (no en esta
  sesión visible, pero confirmado en el código actual): `_DbcRestoreWorker`
  emite `progress(done, total)` → `dbc_restore_progress` → `EtaProgressDialog`
  en `main_window.py` (`_show_dbc_restore_progress`/`_on_dbc_restore_progress`).
  El hallazgo de abajo (verificado contra `viewmodels/main_window_viewmodel.py:189-227`)
  ya no aplica al código actual.
- **Sin buscador global / salto directo a un CAN ID.** Confirmado: no existe ningún
  `QShortcut`/atajo tipo Ctrl+F a nivel de app — cada ventana (Analyze, Candidate,
  panel de CAN IDs) tiene su propio cuadro de búsqueda **local**, sin forma de saltar
  a un ID desde cualquier lado sin primero cambiar de ventana. Útil sobre todo en un
  log con cientos de IDs.
- ✅ **Convención de color para "esto cambió" unificada** (2026-07-20, commit
  `d0e5184`). Real-Time's byte-highlight ahora lee `theme.accent`/`accent_text`
  directo (antes `QPalette.Highlight`/`HighlightedText`, mismo hex pero un
  token distinto); la Matriz de Analyze gana color por primera vez (borde
  superior 3px, `theme.accent` si `has_movement`, `theme.border` si plano).
  Diff Analyzer's paleta `ChangeType` (más rica, con `warn` para
  NEW_TERRITORY/RANGE_SHIFT) no se tocó -- sigue siendo la fuente de verdad de
  ese matiz, las otras 2 herramientas ahora comparten sus 2 extremos
  (`accent`="cambio real", `text_muted`/`border`="nada nuevo").
- ✅ **Configuración de ventanas secundarias ahora sobrevive a reiniciar la app**
  (2026-07-21, commits `8e22026`/`8b31df3`). `SessionStateStore.get_window_prefs()`/
  `set_window_prefs()` (bolsa genérica por ventana, reusable) + Candidate
  Interpretations (min/max length, granularity, endianness, value type,
  include-constant) y Diff Analyzer (los 5 checkboxes de filtro + min frames)
  restauran su última configuración al abrir una ventana nueva, salvo que la
  sesión actual ya la haya customizado (Diff Analyzer respeta B-13's
  sync-desde-VM para reaperturas dentro de la misma sesión). Constraint Search
  (precisión, tolerancia) queda pendiente -- mismo patrón, no aplicado ahí todavía.

## Prueba integral con log real (2026-07-19) — `candump-2026-07-11_153006.log`

Pedido explícito del usuario: "prueba todas las funcionalidades con este log... y
describe todas las mejoras posibles". Log real: **4,040,230 filas, 118 CAN IDs**,
~195 MB en disco. Medido con un script que abre cada ventana/VM en secuencia contra
el mismo log, con `GetProcessMemoryInfo` (Windows) para el working-set real del
proceso — no estimaciones.

### Resultados medidos

| Paso | Tiempo | Memoria (working set) |
|---|---|---|
| `load_can_dataframe` | 1.35 s | 2,292 MB (ver nota B0..B7 ya documentada arriba) |
| Analyze Data: precompute (118 ids) | 6.38 s | 1,994 MB (bajó — gc de basura de parseo) |
| Analyze Data: 5 switches post-precompute | 11.7 ms/switch | — |
| Analyze Data: Matriz (118 ids, 88 con movimiento) | instantáneo (lee cache) | — |
| **Candidate Interpretations: recalculate, 118 ids, params default** | **no terminó en 180 s** (ver hallazgo abajo) | 6,265 MB |
| Diff Analyzer: batch compare (rango 10%/10%) | 5.17 s, 118 ids en el reporte | 1,868 MB |
| Diff Analyzer: capturar baseline Live | 5.53 s | 2,905 MB |
| Real-Time: `ingest_df` todo el log de una vez | 37.87 s | 2,904 MB |
| Signal Coverage: análisis (sin DBC cargado) | 0.77 s | 5,394 MB |

**Nota sobre Real-Time/Signal Coverage:** estos dos corrieron **después** de la
búsqueda de Candidate Interpretations que no había terminado (ver hallazgo abajo) —
`closeEvent` pide cancelación (`cancel_recalculation()`) pero no espera
(`_thread.wait()`), así que el hilo de esa búsqueda pudo seguir corriendo de fondo
durante estos dos pasos, contaminando sus tiempos/memoria. **No son números limpios**
— recomendado remedir en aislamiento antes de actuar sobre ellos específicamente.

### Hallazgo principal — Candidate Interpretations es demasiado lento en un log real — ✅ mitigado (2026-07-20)

**Re-medido hoy con el mismo log real:** `_build_candidate_items()` sobre los 118
IDs (mismos params default) ahora termina en **91.1 s** (antes: no terminaba en
180s, proyectado ~247s) — **1,456 candidatos** encontrados. El fix de B-30 (ya
aplicado, ver comentario `services/candidate_interpretations.py` "Precompute once
per group instead of once per spec") + la vectorización de `_split_by_mux_case` +
el esquema `UInt8` (todos de hoy) explican la mejora. **Sigue siendo lento** (91s
es una espera real) — no se investigó más a fondo hoy qué queda del costo restante
(`decode_signal`'s extracción de bits/cast/tolist por spec, ya identificado abajo
como "el resto del costo"); queda abierto si se decide seguir optimizando esto
específicamente.

**Sobre virtualizar la lista de resultados (item 7 del EPIC Performance, evaluado
2026-07-20):** con params default, 1,456 candidatos crudos (menos aún tras el
colapso de "Group overlapping" de CI5) es una escala moderada para un
`QListWidget` con un `QListWidgetItem` por fila — no se encontró evidencia de que
justifique hoy una reescritura a `QAbstractItemModel`/vista virtualizada. Si a
futuro un search con rango combinatorio completo (1-64 bits, no acotado a 8 bits
como esta medición) produce un orden de magnitud más candidatos, revisar de nuevo.

### (contexto original, ya resuelto arriba) Candidate Interpretations es demasiado lento en un log real

Con los 118 IDs marcados y parámetros default (`min_length=max_length=8`,
`granularity=8`, `endianness="Try Both"`, `value_type="Try All"` — **no** el rango
combinatorio completo 1-64 bits, ya de por sí acotado a 8 bits), la búsqueda **no
terminó en 180 s**. Aislado y confirmado con un script separado:

- `_build_candidate_items()` sobre **solo 5 IDs** (mismos params): **10.48 s**, 100
  candidatos encontrados correctamente (no es un bug de corrección — sí encuentra
  resultados reales; es puramente de performance).
- Proyección lineal a 118 IDs: **~247 s (más de 4 minutos)** — consistente con que
  el test de 180 s nunca llegó a emitir `candidate_list_changed`.
- **Causa raíz confirmada:** `services/can_decoder.py::with_data_int()` (línea 17)
  reconstruye la columna `DATA_INT` re-parseando el string hex `DATA` byte por byte
  (`.str.slice()` + `.str.to_integer()` × 8) — y `decode_signal()` (línea 118) la
  llama de nuevo **en cada llamada**, o sea una vez **por cada spec** probado
  (~32 specs por grupo `(id, LEN)` con los params default: 8 start-bits × 2
  byte-orders × 2 value-types), no una vez por grupo. Medido en aislado: **5.32 ms
  por llamada** sobre un grupo real de ~47K filas → controlar solo esa
  re-construcción redundante cuesta **~20 s** de los ~247 s proyectados (asumiendo
  1 LEN por id) — el resto es el costo restante de `decode_signal` (extracción de
  bits, cast, listas) repetido igual de innecesariamente por spec.
- **Coincide exactamente** con el "Item 1" ya documentado en CLAUDE.md § Dataframe
  perf optimization ("recomendado primero", más barato/seguro que sacar `B0..B7` —
  eso sí lo difirió el usuario explícitamente, esto es un item **distinto**, no
  tocado por esa decisión). Ahora **confirmado empíricamente** con un log real, no
  solo señalado por lectura de código.
- **Fix propuesto (no implementado, pendiente de decisión del usuario):** en
  `_build_candidate_items` (`services/candidate_interpretations.py`), llamar
  `with_data_int(mux_df)` **una vez por grupo** `(can_id, frame_len, mux_label)`,
  antes del loop de specs, y pasar el resultado ya cacheado a cada `decode_signal()`
  de ese grupo en vez de que cada uno lo recalcule. Requiere que `decode_signal`
  acepte un df que ya tenga `DATA_INT` sin volver a construirlo (hoy siempre lo
  reconstruye, `can_decoder.py:118`) — cambio acotado pero toca una función usada
  en varios lugares (Candidate, y potencialmente el path de decode principal), no
  solo Candidate Interpretations.
- **Regla de verificación sugerida para cuando se haga:** repetir este mismo script
  contra el mismo log real y confirmar que la búsqueda de 118 IDs termina, además de
  los ~250+ tests existentes de `test_candidate_interpretations.py`.

### Otros hallazgos menores de la pasada

- **`CandidateInterpretationsWindow.closeEvent` no espera al hilo cancelado** —
  mismo patrón que B-19 (ya arreglado en Diff Analyzer esta sesión) pero **no
  replicado aquí**: pide cancelación pero no `wait()`. Con una búsqueda de ~4 min
  como la de arriba, cerrar la ventana a mitad de camino deja el hilo corriendo de
  fondo un buen rato, further evidence de por qué las medidas post-Candidate quedaron
  contaminadas. Candidato a un fix idéntico al de B-19 (`cancel_and_wait_batch()`-
  style) una vez que se aborde el punto anterior.
- El resto de la app (Analyze Data completo, Diff Analyzer batch+Live, Signal
  Coverage) responde en segundos incluso sobre las 4M filas reales — la Fase 6 de
  esta sesión (vectorizar + precompute + chunks numpy) queda validada contra datos
  reales, no solo sintéticos.

## Fix de memoria en Analyze Data + Matrix de Candidate Interpretations (2026-07-19) — **COMPLETO**

Pedido explícito del usuario tras ver el consumo real en Task Manager: **"el consumo
de memoria debe ser algo que se debe arreglar antes que todo, si afecta en algo debe
ser hecho"** — prioridad por delante de features nuevas. Además: "el candidate
interpretations debe también tener la vista en matriz". Ambos resueltos en la misma
pasada porque comparten la misma causa raíz.

### Causa raíz confirmada (no solo sospecha)

`AnalyzeDataWindow.__init__` llamaba `self._vm.precompute_all()` **incondicionalmente**
en cada apertura de ventana — calentaba el acumulador completo (8 series por byte,
resolución completa) de **todos** los CAN IDs del log antes de que el usuario pidiera
nada. Además, la pestaña Matrix (`_build_matrix_cell`) creaba un **`pg.PlotWidget`
completo** (su propio `QGraphicsView`+`QGraphicsScene`) por celda — hasta 118
instancias de un widget de gráfico interactivo completo para lo que debía ser un
sparkline decorativo, reconstruidas enteras (`clear()`+rebuild) en cada toggle de
"hide flat" o cada vez que se visitaba la pestaña.

### Fix aplicado

1. **`precompute_all()` ahora es opt-in** — ya no se llama en `__init__`. Al abrir la
   ventana solo se calcula el CAN ID seleccionado (como antes de esta sesión).
2. **Cache acotado con LRU** (`_LAZY_CACHE_CAPACITY = 16` en
   `viewmodels/analyze_data_viewmodel.py`) para el paso "orgánico" (navegar entre
   señales) — scrollear rápido entre muchas señales sigue siendo instantáneo hasta el
   límite, sin crecer sin cota. `precompute_all()` (el botón explícito) sigue
   ignorando el límite a propósito: si el usuario lo pide, quiere todo cargado.
3. **Botones nuevos en el toolbar** (íconos `gauge`/`trash-2`): **"Precompute all"**
   (opt-in, con `EtaProgressDialog` %+ETA) y **"Free memory"** (`free_memory()` —
   libera el cache completo salvo el ID en pantalla, vuelve al pie de página lazy).
4. **Matrix desacoplado del cache de acumuladores** —
   `services/analyze_data.py::build_matrix_summary()` (nuevo) computa, en un solo
   paso vectorizado por `group_by("ID")`, solo el byte más activo + una serie
   **decimada** (~150 puntos, `utils/plot_sampling.downsample_series`, ya existente)
   por CAN ID. Nunca retiene los acumuladores completos — la pestaña Matrix ya no
   depende de (ni implica) precomputar todo. Corre en su propio `QThread`
   (`AnalyzeDataMatrixWorker`) con `EtaProgressDialog`, se dispara solo al abrir la
   pestaña por primera vez (`build_matrix()`, con `force=True` para el botón
   "Refresh").
5. **`SparklineWidget`** (nuevo, `views/widgets/sparkline_widget.py`) — un
   `QWidget` con `paintEvent` propio dibujando una polilínea, reemplaza el
   `pg.PlotWidget` por celda. Técnica estándar de "small multiples"/sparklines
   (la misma que usan paneles de overview en Grafana/Datadog o los sparklines de
   Excel) — un widget decorativo no necesita un motor de gráfico interactivo completo.
6. **`AnalyzeDataWindow.closeEvent`** ahora llama `self._vm.shutdown()` (cancela+espera
   ambos hilos: precompute y matrix) en vez de solo `cancel_precompute()` — mismo
   patrón que B-19, corregido de raíz en este VM antes de que se convirtiera en bug.

### Matrix nueva en Candidate Interpretations (el pedido explícito del usuario)

**`CandidateMatrixViewModel`/`CandidateMatrixWindow`/`CandidateMatrixWindowManager`**
(nuevos) — reusan **exactamente** `build_matrix_summary()`/`AnalyzeDataMatrixWorker`/
`SparklineWidget` tal cual: la misma rejilla de actividad por byte, en una **ventana
separada** (no una pestaña — Candidate Interpretations ya es un layout denso de 3
columnas), abierta desde un botón "Matrix view" (ícono `grid`) en el toolbar de la
ventana principal de Candidate Interpretations. Clic en una celda → dispara el
handoff P1 ya existente (`CandidateInterpretationsWindowManager.open_window_for_can_id`)
que abre/enfoca la ventana real de Candidate Interpretations **ya filtrada a ese CAN
ID y con la búsqueda real corriendo** — nunca ejecuta la búsqueda cara por-spec (B-30)
sobre más de un ID a la vez.

### Bug encontrado *durante* la propia verificación: `build_matrix_summary()` copiaba el df entero

La primera medición mostró que `build_matrix()` (Analyze) agregaba **+1.79 GB** — casi
tanto como el problema que se estaba arreglando. Causa: el paso "rápido" de la función
hacía `df.sort(["ID", "TS"])` sobre el **DataFrame completo de 21 columnas** (`LEN`,
`DATA`, `B0..B7` incluidas) solo para poder agrupar por `ID` con `diff()` correcto —
`sort()` en Polars no es una vista, es una copia física completa. Fix: (1) trabajar
sobre `df.select(["ID","TS"]+byte_cols)` (un `select` sobre columnas existentes es una
referencia, no una copia) y (2) usar `pl.col(c).sort_by("TS").diff()` **dentro** de la
expresión de `agg()` en vez de un `.sort()` global — cada grupo ordena su propia
columna (pequeña), nunca se materializa una copia del DataFrame entero. Confirmado con
el mismo script antes/después: **+1.79 GB → +183 MB**, mismos 118 resultados, misma
suite de tests en verde. Sirve como recordatorio: en Polars, `select()` sobre columnas
existentes es barato; `sort()`/`filter()` sobre el DataFrame completo no lo es — podar
columnas *antes* de esas operaciones cuando el resultado no las necesita.

### Medido contra el log real (`candump-2026-07-11_153006.log`, 4,040,230 filas, 118 IDs)

Medido con `GetProcessMemoryInfo` (Windows), después del fix de `build_matrix_summary()`
de arriba:

| Paso | Antes (sesión previa) | Ahora |
|---|---|---|
| Abrir Analyze Data | precompute automático de 118 IDs sin pedirlo | solo 1 ID (el seleccionado), **+128 MB** sobre el baseline del log |
| 10 cambios de ID lazy (1ª visita) | — | **78.9 ms/cambio** (vectorizado, sin cache) |
| Pestaña Matrix (Analyze) | requería el cache completo ya calentado | **1.65 s**, **+183 MB** — 118 entradas, independiente del cache |
| "Precompute all" (opt-in) | automático, sin control del usuario | **8.35 s**, **+383 MB** — el usuario elige pagar este costo |
| "Free memory" | no existía | cache 118→1 (confirmado por conteo de objetos; la caída de working-set en Windows puede demorar por el propio allocator) |
| Candidate Interpretations Matrix (nuevo) | N/A (no existía; la búsqueda real no terminaba en 180s+, B-30) | **1.27 s**, **+242 MB**, 118 entradas, ventana separada |

Script de verificación (no en el repo, en el scratchpad de la sesión):
`memory_fix_verification.py`. Suite completa: **761 tests OK** (18 nuevos:
`tests/test_candidate_matrix_viewmodel.py` + extensiones en
`tests/test_analyze_data.py`/`tests/test_analyze_data_viewmodel.py`), sin
regresiones.

### Código muerto retirado en el mismo pase

`AnalyzeDataAccumulator.has_any_change()`/`.most_active_byte()` y
`build_matrix_entry()` (viejo camino, uno por acumulador completo) quedaron sin
ningún llamador tras el desacople y se eliminaron junto con sus tests — reemplazados
por `build_matrix_summary()`.

## Auditoría de "tiempos muertos" de UI (2026-07-20) — ✅ hallazgos reales corregidos

Pedido explícito del usuario tras ver el freeze de la Matrix de Candidate Interpretations
("si hay lugares donde necesite una ventana de diálogo de carga ponla para que no genere
esos tiempos muertos lentos"). Auditoría vía agente + verificación contra el log real
(`candump-2026-07-11_153006.log`, 4 040 230 filas, 118 IDs) antes de dar cada fix por bueno.

- **Matrix de Candidate Interpretations**: el fix de la sesión anterior (chunking por
  cantidad de items) no alcanzaba con datos reales — un candidato real puede tener hasta
  483 584 muestras, otro 500; un lote de 400 items podía caer en varios "grandes" seguidos
  y trabar igual (~5.3s medido). Corregido: chunking por **presupuesto de frames** + tope
  de items, y separar en ticks de event-loop distintos la última tanda de entries y la
  primera tanda de celdas (estaban encadenadas sin ceder el loop). Verificado con los 3540
  candidatos reales del log: peor salto de tick bajó de 5.3s a ~250ms.
- **Matrix de Analyze Data**: mismo bug, nunca corregido — construía sus ~944 celdas
  (118 IDs × 8 bytes) en un solo loop síncrono. Mismo patrón de chunking aplicado
  (sin necesitar presupuesto por frames, sus entries ya vienen decimadas a 150 puntos).
  Verificado: máximo salto de tick ~19ms con datos reales.
- **`services/pgn_scanner.py::available_bam_pgns` + `decode_tab.py`'s `_filter_bam_sources`/
  `_payload_len`**: escaneaban el log completo fila por fila en Python (`iter_rows()`) solo
  para probar un byte de formato PDU — sin ni siquiera un spinner. Vectorizado con un
  filtro Polars antes del loop Python (que ya queda sobre un subconjunto mínimo). Medido:
  4 040 230 filas en 27ms (antes: scan Python completo). Sin tests antes; se agregaron
  (`tests/test_pgn_scanner.py`).
- **Restore de DBCs al abrir la app**: solo actualizaba texto en la status bar, sin %+ETA,
  inconsistente con la regla que el propio usuario pidió para el resto de la app. Agregado
  `progress(done, total)` al worker + `EtaProgressDialog`.
- **Reevaluado y deprioritizado**: el loader del log principal (`LogLoaderWorker`) usa un
  spinner indeterminado en vez de %+ETA, pero medido contra el log real de 195MB carga en
  **1.31s** — no amerita el riesgo de tocar el parser para agregar progreso real por una
  espera que ya es casi instantánea. Queda documentado, no implementado.

## Limpieza de historial git — ✅ **HECHA** (2026-07-19)

Pedido original (2026-07-19): reducir los commits de `feature/range-diff` y renombrar
la rama, porque arrancó siendo literalmente Range Diff pero terminó incluyendo
Candidate Interpretations, Analyze Data, Real-Time, tabla y Constraint Search — el
nombre ya no describía su contenido. **Decisión final** (revirtiendo el plan de 3
ramas de más abajo, dejado tal cual para historial): reorganizar **en una sola rama**,
renombrada, no repartir en varias.

**Ejecutado:** `feature/range-diff` (39 commits desde `dev`) → **`feature/detection-suite`**
(5 commits), mismo árbol final (verificado con `git diff` — sin pérdida de contenido).
La rama vieja se conservó como **`archive/range-diff-pre-squash`** (no se borró, por
si hace falta consultar el historial commit-a-commit original).

Técnica (sin `git rebase -i`, prohibido por las reglas de la sesión): rama nueva desde
el merge-base con `dev`, `git cherry-pick <rango>` de cada grupo cronológico de
commits originales (aplican limpio porque es el mismo orden en que ya se aplicaron una
vez), `git reset --soft <punto-anterior> && git commit` para colapsar cada grupo en
uno. El commit de merge intermedio (`55540b0`, sync de `dev`) se saltó — su contenido
ya es la base, al arrancar la rama nueva desde la punta actual de `dev`.

**Los 5 commits finales:**
1. `feat(diff-analyzer): add core service, viewmodel, window`
2. `feat(candidate-interpretations): rework scoring, layout`
3. `fix: stabilize Real-Time/Table/Diff Analyzer/Analyze Data`
4. `feat(diff-analyzer): Live mode, Plot tab, handoffs`
5. `feat: Analyze Data perf, Matrix views, memory fix` (incluye todo el trabajo de
   memoria/Matrix/UX de esta sesión que estaba sin commitear al momento de reorganizar)

**Verificación post-reorganización:** suite completa (761 tests) OK, las 7 ventanas
secundarias + plot window abren sin error headless, y `git diff` entre la punta nueva
y la vieja rama solo difiere en los archivos de esta sesión (nada se perdió).

### Backlog — sin fecha, no tocar salvo pedido explícito
- Consolidación con Mux Detector (no bien implementado, deshabilitado en UI)
- Performance/memoria en logs grandes (`D0..D7`/`B0..B7`, ventanas pesadas; ver
  "EPIC Performance y memoria en logs grandes"). **Medido 2026-07-19** con el log real
  del usuario (`candump-2026-07-11_153006.log`, 4,040,230 filas, 118 CAN IDs): proceso a
  2.27 GB solo tras cargar el log (antes de abrir cualquier ventana). Desglose:
  `df.estimated_size()` de Polars = ~909 MB (de eso, `B0..B7` solas = ~493 MB, 100%
  redundantes con `D0..D7`+`DATA`); el resto (~1.36 GB) es overhead de parseo que no se
  libera al OS. Usuario decidió explícitamente **diferir** la migración de schema (saca
  `B0..B7`, toca tabla/decodificación/Diff Analyzer/Candidate/Real-Time/Mux) — no
  iniciar sin pedido explícito. La sesión que la haga: medir con el mismo log real antes/
  después para cuantificar la ganancia real, no solo `df.estimated_size()`.
- Higiene de merges (`feature/detection-suite` → `dev`)

---

## Norte del producto: **detectar señales, offline y online**

> **Caso de aceptación (el usuario lo definió así):** "pulsa este botón físico de un
> equipo y que se pueda saber qué señal o señales han cambiado" — funcionando tanto sobre
> un log ya grabado como sobre streaming en vivo.

Todo el toolset de reverse-engineering debe leerse como **un pipeline de detección de 4
etapas**, no como features sueltas:

| Etapa | Pregunta | Herramientas hoy |
|---|---|---|
| **① Localizar** | ¿Qué ID + qué byte/bits llevan señal (vs. constante/contador/checksum/ruido)? | Candidate Interpretations (scan ciego + score), Mux Detector (entropía, deshabilitado en UI), **Diff Analyzer** (qué bytes reaccionan A→B), Real-Time (cambios en vivo), Signal Coverage (qué señales DBC varían) |
| **② Decodificar** | ¿Longitud, LE/BE, signo, escala/offset? | `can_decoder` (ejecuta un spec), Candidate Interp. (enumera specs), Mux Detector (enumera encodings) |
| **③ Confirmar** | ¿Es real o artefacto/ruido? | scoring (autocorrelación lag-1 × tamaño de muestra), Mann-Whitney (Diff Analyzer) |
| **④ Identificar** | ¿Qué magnitud física es? | DBC hint, HMI OCR + `signal_aligner` |

### Los dos huecos estructurales (verificados en código, 2026-07-18)

- **Hueco A — No hay orquestación entre etapas.** Cada tool arranca de cero sobre el
  DataFrame completo. Un byte que Diff Analyzer / Signal Coverage / Real-Time marca como
  interesante **no se puede pasar** a Candidate Interpretations; el único punto compartido
  es el Plot (un *sumidero*, no un alimentador). Peor: Candidate Interpretations solo se
  acota por CAN ID, **no por byte** — no hay forma de decir "analizá solo el byte 3 del ID
  X". El humano es la capa de integración.
- **Hueco B — No hay razonamiento entre bytes.** Las señales multi-byte (16/24/32 bits) se
  encuentran solo por fuerza bruta enumerando ventanas fijas, cada una puntuada en
  aislamiento. No hay primitiva que detecte que el byte N y el N+1 forman un valor de 16
  bits por su comportamiento conjunto (acarreo/rollover, correlación).

Cerrar estos dos huecos es el mayor lever para "detectar mejor una señal" — más que
cualquier estadístico nuevo sobre un byte suelto (varios de scipy ya se probaron y
descartaron con evidencia, ver [CLAUDE.md](CLAUDE.md) § Candidate Interpretations).

### Dos puntos de entrada al pipeline (no es una calle de un solo sentido)

Cada herramienta es un **punto de entrada completo por sí mismo**; no siempre se arranca en
el mismo lado. Según lo que tengas en la mano:

- **Entrada dirigida (con una acción):** tenés un evento físico ("pulso el botón") → arrancás
  en **Diff Analyzer**, que localiza el byte que reaccionó → lo pasás a **Candidate** para
  decodificar. Aquí el lever es **P1 (handoff)**.
- **Entrada exploratoria (sin acción, a ciegas):** solo tenés un log y querés "¿qué señales
  hay acá?". Arrancás **directo en Candidate Interpretations**, que hace su búsqueda a ciegas
  — su trabajo nativo, funciona solo, sin depender de nadie. Aquí P1 no aplica (no hay nada
  aguas arriba); el lever es **P2** (mejor detección intrínseca de ancho multi-byte) + la
  calidad del scoring. P2 importa *más* en esta entrada que en la dirigida.

**El handoff es bidireccional:** cualquier tool puede pasar un hallazgo (ID + byte/región) a
cualquier otra, y la dirección la decide con qué empezaste:
- Diff Analyzer → Candidate: "reaccionó este byte, ¿cuál es su codificación?"
- Candidate → Diff Analyzer / Real-Time / plot: "encontré este candidato, ¿es real? ¿reacciona?
  ¿se ve bien en vivo?" (etapa ③ confirmar).

Por eso las herramientas quedan **separadas**: cada una entra por su lado, los puentes son
opcionales y en cualquier sentido.

---

## Prioridades (ordenadas por valor de detección)

### P1 — Capa de orquestación / handoff bidireccional  ⭐ mayor lever (solo entrada dirigida)

**Revisado (2026-07-18): sin filtro de byte explícito — el ranking ya hace ese trabajo.**
Se consideró un filtro "solo candidatos que tocan el byte N" (seedear/filtrar por región) y
se **descartó**: con **CI1** (orden por score) + **CI2** (filtro por score mínimo, reemplaza
sensitivity) ya activos, los candidatos que realmente varían en el byte que reaccionó **ya
suben solos** al tope de la lista — un filtro de byte encima aporta poco y agrega ambigüedad
(¿"toca" el byte, "empieza" en el byte, para una señal de 16/24 bits que cruza varios bytes?).

- **P1.1** Handoff hacia Candidate: acción **"Analizar este ID como señal"** desde Diff
  Analyzer (y Signal Coverage / Real-Time) que abre Candidate ya acotado a ese CAN ID (usa
  `checked_ids`, el único filtro real que existe hoy) — no hace falta sembrar por byte, el
  orden por score ya resuelve encontrarlo. Opcional: al abrir, saltar/resaltar el candidato
  cuyo rango de bits incluye el byte que reaccionó (gesto de conveniencia una sola vez, no un
  filtro persistente). 🟢 (views+composition root) — más liviano de lo planeado originalmente.
- **P1.2** Handoff desde Candidate (sentido inverso): acción **"Confirmar este candidato"** →
  plotearlo (ya existe), verlo en Real-Time, o comprobar con Diff Analyzer que reacciona.
  Etapa ③. 🟡 (views)
- **P1.3** Flujo dirigido end-to-end: *actúo → Diff Analyzer encuentra el ID que reaccionó →
  un clic → Candidate abre ya acotado, el candidato correcto ya está arriba por score →
  confirmo en plot*. Ésta es la "super funcionalidad" bien hecha: **encadenar ventanas, no
  fusionarlas** (siguen separadas; solo viaja la evidencia, en cualquier sentido, con un
  botón). NB: solo aplica a la **entrada dirigida**; en la exploratoria (arranque directo en
  Candidate) el lever es P2, no P1.

> **Ganancia real de P1 (no es comodidad, y no es velocidad de búsqueda):** hoy la evidencia
> dura de Diff Analyzer ("el ID X reaccionó") se **descarta** en el borde entre
> herramientas — tenés que ir a Candidate y volver a elegir el ID a mano entre docenas. El
> handoff no acelera la búsqueda (sigue siendo exhaustiva, ver P1 más arriba: eso ya no
> cambia con CI6) — la ganancia es de **navegación**: llegás con el ID correcto ya
> seleccionado y, gracias a CI1+CI2, el candidato correcto **ya está arriba** de la lista en
> vez de perdido sin orden entre cientos de filas. Es "abrí el libro ya en el capítulo
> correcto y con lo relevante subrayado arriba" vs. "buscá el capítulo y después subrayá vos
> mismo": misma herramienta, una te ahorra los dos pasos de navegación.

### P2 — Detección de ancho multi-byte (Hueco B) — primitiva compartida — ✅ COMPLETA (P2.1-P2.3)
- **P2.1** ✅ Primitiva pura en `services/` de comportamiento conjunto entre bytes vecinos
  (alineación de acarreo/rollover, o correlación) que, dado un byte que varía/reacciona,
  proponga si es parte de una señal más ancha (16/24/32 bits). 🔴 (services) — Qt-free,
  testeable.
- **P2.2** ✅ La consume **Candidate Interpretations**: mejora la etapa ② dándole una
  hipótesis de ancho en vez de enumerar a ciegas.
- **P2.3** ✅ (2026-07-20) La consume **Diff Analyzer**: `ByteDiff.multi_byte_hint`,
  calculado en `_diff_bytes` (compartido por batch/`_diff_for_id` y Live/
  `build_live_diff_report`, así que ambos modos lo reciben gratis) a partir de
  `ByteObservation.raw` de las ventanas A y B concatenadas. Columna "Multi-byte" nueva
  en el árbol (visible + tooltip, mismo patrón que `dbc_hint`/B-17) y en el export CSV.
  Mismo núcleo, dos consumidores — coherente con "una sola fuente de verdad".

### P4 — Diff Analyzer (rename de Range Diff + modo Live + tab plot A/B)
Es la etapa ①-por-reacción y el **frente del pipeline** que alimenta el handoff de P1.
Detalle completo en la sección siguiente.

---

## EPIC Diff Analyzer (antes "Range Diff") — Fase 1 ✅ · Fase 2 plan

**Decisión (2026-07-18):** Range Diff se **renombra a "Diff Analyzer"** (ya no es solo
offline) y gana modo **Live**. NO absorbe Real-Time Analysis (otro trabajo: ver valores en
vivo). Una ventana, un motor (`classify_byte`), dos formas de alimentar A/B (manual vs.
baseline-congelado/B-creciendo). Se descartaron: (a) mantener el nombre, (b) fusión total
absorbiendo Real-Time (sería mega-ventana mezclando "ver valores" con "comparar").

**Fase 1 — offline/manual, ✅ COMPLETE** (rama `feature/range-diff`, pendiente mergear a `dev`):
núcleo `services/range_diff.py` (taxonomía UNCHANGED/SAME_OSCILLATION/CONST_SHIFT/
NEW_TERRITORY/RANGE_SHIFT + Mann-Whitney opcional), viewmodel+worker, `range_timeline.py`,
ventana + manager, cableado, scipy. 36 tests. Ver [CLAUDE.md](CLAUDE.md) para el detalle
de tipos/funciones ya implementados.

**Fase 2 — rename + Live + tab plot** (rama `feature/diff-analyzer` desde `dev`):

| # | Commit | Qué | Esf. |
|---|--------|-----|------|
| 1 | `fix(range-diff)` | **B-02**: timestamps A/B por timezone + read-only (bug de precisión `:g`) | 🟡 |
| 2 | `feat(diff-analyzer)` | rename Range Diff → Diff Analyzer (i18n, título, ribbon, menú, clases) | 🟢 |
| 3 | `feat(diff-analyzer)` | `LiveByteAccumulator` (puro) + refactor `_diff_bytes` compartido + `tests/test_range_diff_live.py` (invariante `feed==observe_byte`) | 🟡 |
| 4 | `feat(diff-analyzer)` | modo Live en el ViewModel (baseline worker + watermark + `QTimer` ~1s, reusa `report_changed`/`visible_changed`) | 🟡 |
| 5 | `feat(diff-analyzer)` | `QTabWidget`: tab **Plot** con el byte auto-ploteado + bandas A/B resaltadas (colores de `RangeTimeline`, respeta timezone vía `TimeAxisItem`); en Live la banda B crece sola | 🟡 |
| 6 | `feat(diff-analyzer)` | toggle "Live" en la vista (ON congela A, deshabilita picker manual, "capturado a HH:MM:SS → creciendo") | 🟢 |
| 7 | `feat(diff-analyzer)` | **P1**: acción "Analizar este byte como señal" → siembra Candidate Interpretations | 🟡 |
| 8 | `feat(realtime)` | (opcional) botón "Comparar desde ahora" como atajo hacia Diff Analyzer en Live | 🟢 |

**Modo Live (análogo honesto del diff en streaming, forward-only):** A = snapshot congelado
al capturar baseline (todo lo acumulado hasta ese instante), B = lo que llega después,
creciendo. `LiveByteAccumulator` mantiene incrementalmente los mismos campos que
`ByteObservation` (invariante `acc.feed(seq); acc.snapshot() == observe_byte(seq)`). En
`set_dataframe` solo se alimenta el slice nuevo `df[watermark:]` (no re-escanear todo el df
por tick). Mann-Whitney aplica igual (mismo `.visible(opts)`), barato porque
`_mann_whitney_p` ya evita scipy sobre bytes sin cambio de set (`len(set(a)|set(b)) < 2`).

## EPIC Candidate Interpretations — ranking y filtros de vista (display-time, sin recomputar)

Sirve a la **entrada exploratoria** (arranque directo desde un log). Todo es display-time
sobre los `CandidateItem` ya calculados (que ya llevan `score`), con `setHidden`/reorden —
**cero recálculo**, mismo patrón que `RangeDiffReport.visible(opts)` y los filtros actuales
(amplitud/frames/tag/tipo).

Diagnóstico que lo motiva (verificado en código 2026-07-18): hoy la lista **no se ordena por
score** (sale en orden de enumeración; el score solo se muestra como dato — ver
`_set_candidate_list`, `window:604`) y **no agrupa candidatos solapados** (cada
`(start_bit,longitud,endianness,tipo)` es una fila suelta; una señal 16-bit real produce el
candidato correcto + sus parciales/misalineadas como filas sin relación).

### Decisión (2026-07-18): eliminar `sensitivity` como parámetro de recómputo

El usuario objetó `sensitivity` con razón: es un slider 0-100 **cualitativo**, sin
significado cuantitativo (saltar 10%/50%/80% no dice nada), y **mover el slider re-corre
toda la búsqueda** para algo que podría ser instantáneo. Verificado en código
(`services/candidate_interpretations.py:195`): el gate de sensitivity corre **después** de
`decode_signal` (línea 170) y de calcular el score (línea 194) — es decir, **el costo de
decodificar ya se pagó** antes de que sensitivity actúe. Sensitivity hoy no ahorra cómputo:
solo decide cuántas filas se guardan. Es, de hecho, ya un filtro de vista, solo que
implementado como si fuera de búsqueda.

**Consecuencia de diseño:**
- La búsqueda **siempre corre en modo fuerza bruta** (permisiva): decodifica todo el espacio
  de parámetros y guarda **todos** los resultados (el único gate que sobrevive es
  `include_constant`, porque descartar constantes es una decisión real sobre qué es
  "señal", no un umbral arbitrario de score). No cuesta más CPU que hoy — el decode ya se
  paga por spec, con o sin sensitivity.
- El trabajo que hacía sensitivity lo hace **CI2**: un filtro de score mínimo real,
  cuantitativo (0.0–1.0), en vivo, sin recalcular, con contador "mostrando X de Y".
- **"Fuerza bruta, mostrar todo" queda siempre disponible por diseño**: poner CI2 en 0 (o
  desactivarlo) muestra literalmente todo lo decodificado.
- Los parámetros que SÍ siguen siendo de cómputo (cambian qué se decodifica, no si se
  muestra): `min_length`/`max_length`/`granularity`/`endianness`/`value_type`.
- **Riesgo a vigilar, no escondido:** un espacio de búsqueda muy grande (mucho `max_length`,
  granularidad fina, muchos IDs) con el filtro de score en 0 puede producir miles de filas;
  `QListWidget`+`setHidden` sigue creando cada ítem aunque esté oculto, lo que puede volverse
  lento de renderizar a esa escala. Si aparece en la práctica, resolver con paginación o
  virtualización — no es motivo para reintroducir un gate de cómputo disfrazado.

- **CI1** Selector de **orden**: "CAN ID → score" (default: respeta el orden por CAN ID y
  dentro de cada ID ordena por score) · "Score" (ranking global puro) · (opc.) "CAN ID →
  start bit". Reordena los `CandidateItem` ya emitidos. 🟢 (view)
- **CI2** Filtro **score mínimo** (slider/spinbox 0.0–1.0, con contador "X de Y"): reemplaza
  a `sensitivity`; oculta score bajo sin recomputar. 🟢 (view)
- **CI3** Filtro **endianness** (LE / BE / ambos): oculta el duplicado que solo cambia por
  big/little. 🟢 (view)
- **CI4** Filtro **longitud / multibyte** (ej. "solo ≥16 bits", "ocultar 8-bit parciales"):
  esconde las parciales redundantes de una señal ancha. 🟢 (view)
- **CI5** (paliativo → fondo) **Agrupar candidatos solapados** por región y quedarse con el
  mejor representante (colapsar "todas las interpretaciones de los bytes 2-3" en una). Paso
  previo natural a **P2**; los filtros CI1–CI4 son el paliativo visual mientras tanto. 🟡
  (services+view) — probablemente requiere pasar el `QListWidget` a `QTreeWidget` para
  subgrupos por CAN ID.
- **CI6** Quitar `sensitivity` de `services/candidate_interpretations.py`
  (`_passes_sensitivity`, parámetro `sensitivity`) y del viewmodel/UI; el service siempre
  filtra solo por `include_constant`. Migración: verificar que no quede nada persistido en
  `.conf`/`session_state` referenciando el viejo slider. 🟡 (services+viewmodel+view)

> Nota: CI1 (ordenar por score) es casi un bug — el motor computa un ranking y no lo aplica
> a la lista. Registrable en [BUGS.md](BUGS.md) si se prefiere tratarlo como defecto.

## EPIC Analyze — vista matriz de señales
- **AN1** ✅ **COMPLETO** — matriz cuadriculada de mini-plots (small multiples), pestaña
  "Matrix" en `AnalyzeDataWindow`. Rehecha 2026-07-19: al principio dependía del cache
  completo de acumuladores (`build_matrix_entry` + `_accumulator_cache`); ahora es un
  rollup independiente y liviano (`build_matrix_summary()`, un paso vectorizado +
  series decimadas, ver sección "Fix de memoria..." arriba) — no requiere ni implica
  precomputar todo. Celdas migradas de `pg.PlotWidget` a `SparklineWidget` (mismo
  motivo: 100+ widgets de gráfico completo era el cuello de botella real de "muy
  lento").
- **AN2** ✅ **COMPLETO** — checkbox "Hide signals with no movement" en la pestaña Matrix
  (`has_movement` en cada `MatrixEntry`). El modo Live (auto-agregar señales que
  empiezan a moverse) queda como **AN3**, sin empezar.
- **AN3** ⏳ pendiente — reusa la primitiva única "conjunto de cambiados monotónico" (ver
  abajo) para el modo Live de la matriz — misma semántica que "only changes" de
  Real-Time y el modo Live del Diff Analyzer. No implementado.
- **AN4** parcial: `AnalyzeDataViewModel` sigue sosteniendo un solo `_selected_id`/
  `_accumulator` para la pestaña Signal (correcto, sin cambios) — la matriz NO
  necesitó `dict[str, AnalyzeDataAccumulator]` en paralelo como se pensaba
  originalmente, porque `build_matrix_summary()` calcula directo sobre el DataFrame
  crudo por `group_by("ID")`, sin pasar por acumuladores. Sigue sin existir noción de
  señal DBC decodificada en la matriz (opera sobre bytes crudos); si se necesita a
  futuro, es plomería nueva.
- **Nuevo (2026-07-19, pedido explícito del usuario):** Candidate Interpretations
  **también** tiene ahora una vista de matriz — `CandidateMatrixWindow` (ventana
  separada, no pestaña), reusando `build_matrix_summary()`/`SparklineWidget` tal cual.
  Ver sección "Fix de memoria..." arriba para el detalle completo.

### Revertir: checkboxes de bytes visibles (no escondidos en popup)

**Decisión (2026-07-18):** el usuario pidió volver los 8 checkboxes de bytes (B0-B7) a
visibles directamente en la ventana, no detrás del botón "Bytes ▾" del toolbar (cambio hecho
esta sesión). El Mux sí se queda en el toolbar. Revertir solo la parte de bytes de
`_setup_toolbar()` en `views/analyze_data_window.py`. 🟢 (view)

### Bug de performance: cambiar de CAN ID es lento — ✅ **RESUELTO** (Fase 6, esta sesión)

`AnalyzeDataAccumulator.feed()` era un loop en Python puro fila por fila; corregido con
expresiones vectorizadas de Polars (`n_unique()`, `.shift()`+comparación, diffs de `TS`,
agregaciones condicionadas por byte) — commit `0d577d5`. El cache por-ID (ahora acotado
con LRU, ver sección "Fix de memoria..." arriba) cubre la repetición: un cambio de ID ya
visitado es prácticamente instantáneo (lectura de cache). La **primera** visita a un ID
(sin cache, el caso que de verdad importaba) ya es razonablemente rápida gracias al
vectorizado — medido tras el fix de memoria: **78.9 ms/cambio** promedio sobre 10 IDs
distintos del log real de 4M filas (antes del vectorizado era un loop Python fila-por-fila
sin cota clara, la razón original del bug). El threading del rebuild (mejora de
percepción) no se hizo — no resultó necesario una vez vectorizado. Distinto del
"Dataframe perf optimization" documentado más abajo (ese es sobre `D0..D7`/`B0..B7`
redundancia de esquema, todavía sin hacer).

## Primitiva transversal: "conjunto de cambiados monotónico" — ✅ extraída (2026-07-20)
Las tres cosas —Real-Time "only changes", vista matriz de Analyze, modo Live del Diff
Analyzer— comparten UNA semántica: **mantener un conjunto de señales-que-han-cambiado que
crece con el tiempo y nunca descarta** (una vez que algo se movió, queda en el set). Cada
tool lo renderiza distinto (selección de tabla / grilla de mini-plots / clasificación
A→B).

`services/monotonic_changed_set.py` (`ChangedSetDelta`/`compute_changed_set_delta`)
es ahora esa única definición — extraída de `services/realtime_analysis.py` (donde
vivía como `ChangedIdsDelta`/`compute_changed_ids_delta`, atado al nombre "ids"). Sin
consumidor activo hoy (el fix de B-03 usa un hook de atenuado por fila que no necesita
distinguir "creció vs. reset"), pero lista para AN3 (Matrix Live de Analyze) cuando se
implemente — ahí sí hace falta esa distinción para decidir "agregar celdas nuevas" vs.
"reconstruir todo".

- **B-03** ([BUGS.md](BUGS.md)) ✅ resuelto: "only changes" ahora atenúa (no oculta) los
  IDs no cambiados vía `TableModel.set_row_foreground_provider` — un hook genérico de
  color por fila, no específico de Real-Time. Los IDs siguen todos visibles en la
  tabla; el checkbox del panel de CAN IDs dejó de usarse para este propósito.

## EPIC Identificar (etapa ④) — futuro
- **ID1** Correlación puntuada serie-detectada ↔ lectura HMI OCR (hoy es a ojo vía
  `signal_aligner.align`). 🔴 (services)

## Backlog — no tocar por ahora
- **Consolidar búsqueda de encoding con Mux Detector.** `services/mux_detector.py` hace una
  búsqueda de encoding sin-DBC (entropía + decodabilidad) que se solapa con Candidate
  Interpretations, pero **el Mux Detector no está bien implementado / está deshabilitado en
  UI** — queda **fuera del alcance activo**. Revisar solo si en el futuro se decide reactivarlo.
  (Ver regla en memoria: no tocar la lógica de mux detection salvo estrictamente necesario.)

---

## v0.4.0 — CAN Send, DBC⇄CSV round-trip, metadata, build/CI (fuera del hilo de detección)

### CAN Send — ✅ **COMPLETO**, mergeado (`dev`→`master`, tag `v0.4.0`)

Primera feature de transmisión: hasta ahora Canlytics era de solo lectura. Soporta frames
únicos y periódicos, construidos desde hex crudo o asistidos por DBC (elegir un mensaje
cargado, llenar valores de señal, `cantools.Message.encode(...)`), sobre **ambos** backends
(SSH vía `cansend` remoto, Kvaser vía `bus.send()`) — replay rechaza el envío (no hay bus
real). Detalle completo de arquitectura/threading en [CLAUDE.md](CLAUDE.md) § "CAN Send".
Nuevos: `models/can_send.py`, `services/can_send.py`, `viewmodels/can_send_viewmodel.py`,
`views/can_send_window.py`+`can_send_entry_dialog.py`+`widgets/hex_byte_row.py`,
`views/can_send_window_manager.py`. Persistencia vía `session_state.py` (lista de entradas sí,
estado "estaba transmitiendo" deliberadamente no). Tests: `tests/test_can_send.py`,
`tests/test_connection_stream_viewmodel.py`.

### Signal Scan: export CSV + `hide_pdu1` por defecto — ✅ **COMPLETO**

Botón de exportación CSV en Signal Coverage (`views/signal_coverage_window.py`) que agrega, en
el CSV (no en la tabla visible, decisión explícita del usuario), las columnas de geometría de
decode que el CSV necesita para poder reimportarse como DBC: `Start Bit`, `Length (bits)`,
`Byte Order`, `Value Type`, `Scale`, `Offset`, `MUX Start`, `MUX bytes`, `MUX value`. El filtro
`hide_pdu1` pasó a `True` por defecto — que la misma señal PDU1 aparezca bajo varios CAN ID
(mismo PGN, distinta dirección origen/destino) es comportamiento J1939 correcto, no un bug, y
ocultarlo por defecto reduce ruido en el caso común.

### DBC ⇄ CSV round-trip: "CAI Order" / "DBC Order" auto-detectados — ✅ **COMPLETO**

`services/pgn_csv_to_dbc.py` (antes solo entendía el CSV propietario de CAI, una empresa)
ahora acepta **dos** esquemas CSV nombrados y auto-detectados por columnas (no por posición):
**CAI Order** (el propietario original) y **DBC Order** (el export de Signal Scan de arriba —
sí puede reimportarse como DBC, incluyendo señales mux reconstruidas con la API real de
multiplexado de cantools). Si el formato no se reconoce, un picker manual estilo SavvyCAN dejar
elegir "CAI Order"/"DBC Order" a mano (`views/dbc/dbc_manager_dialog.py::
_on_unrecognized_format`). Detalle completo (tipos, funciones, tests) en
[CLAUDE.md](CLAUDE.md) § "DBC ⇄ CSV round-trip".

### Metadata de log: bitrate Kvaser — ✅ **COMPLETO**

Al guardar un log grabado vía Kvaser (no SSH/replay), se antepone una línea de comentario
`# Recorded via Kvaser @ {bitrate} bps` — metadata pura, nunca interpretada al cargar. Detalle
en [CLAUDE.md](CLAUDE.md) § "Kvaser bitrate log metadata".

### CI: `cache-warm.yml` acotado a cambios de `requirements.txt` — ✅ **COMPLETO**

Corría en cada push a `master` sin importar si había cambio de dependencias — ahora tiene
`paths: [requirements.txt]`. Detalle en [CLAUDE.md](CLAUDE.md) § "CI".

### Regresión de peso del build Linux — ✅ **causa raíz encontrada + fix implementado**, pendiente mergear

v0.4.0 pesaba ~18MB más que v0.3.1 en Linux (onefile y onedir) — causa: el switch de
`python:3.11-slim-bullseye` a `ubuntu-latest` en el CI (hecho antes para arreglar la cache de
pip rota en Linux) trajo dos cosas nuevas sin querer: `libpython3.11.so.1.0` con símbolos de
debug (23.05MB vs 5.38MB) y el plugin de tema nativo GTK3 de Qt (`libqgtk3.so`, arrastra
~11.4MB de `libgtk-3`/`libcairo`/`libpango`/etc. vía descubrimiento automático de
dependencias). Confirmado empíricamente (descargando y diffando los binarios reales de los
releases v0.3.1/v0.4.0 vía WSL): stripear + excluir ese plugin recupera **~46.6MB+**, más que
toda la regresión — el bundle stripeado queda *por debajo* del baseline de v0.3.1. Fix en
`Canlytics.spec`/`_build_common.py` (`strip=` condicional por plataforma +
`GTK_PLATFORM_THEME_BINARY_EXCLUDES`), rama `feature/linux-build-size` desde `dev`. Detalle
completo en [CLAUDE.md](CLAUDE.md) § "Linux build size regression". **Pendiente:** correr el
build de Linux en CI para confirmar que el binario stripeado/filtrado sigue funcionando antes
de mergear.

---

## Otros pendientes (fuera del hilo de detección)

### EPIC Modo Debug / Logging — ✅ **COMPLETO** (Fases 1-3, 2026-07-20)

Pedido explícito: **"modo debug... logs de lo que se esté haciendo, pulsaciones,
transacciones etc. que sirva para detectar errores, parecido a un logcat -v time...
cada módulo debe tener su tag... utiliza la librería logging para ello."**

Implementado con 2 desviaciones respecto al plan original de abajo, ambas pedidas
en vivo tras ver la primera versión: (a) el toggle vive **dentro** de la ventana
Debug Log como uno de 4 checkboxes de nivel (Debug/Info/Warning/Error, no un combo
"nivel mínimo" ni un botón separado en el ribbon — la ventana es un solo botón,
sin dropdown); (b) el nivel base pasó de `WARNING` a `INFO` (Info/Warning/Error
siempre se capturan; Debug es el único que requiere el checkbox). La ventana
también backfillea desde `canlytics.log` al abrir (no solo lo que llega en vivo
después), y "Clear" borra el archivo en disco (con confirmación), no solo la vista.
`main.py` loguea un INFO al iniciar. Fase 4 (event filter global de clicks) —
evaluada y descartada, no hizo falta.

Plan original (para contexto/archivo, ya ejecutado):

**Base: el módulo `logging` estándar de Python, no un framework propio.** Encaja
perfecto con el pedido: un logger por módulo vía `logging.getLogger(__name__)` ya da
el "tag por módulo" gratis (p.ej. `viewmodels.candidate_interpretations_viewmodel`,
`services.range_diff`), sin inventar un sistema de tags paralelo.

- **Formato estilo `logcat -v time`:** `MM-DD HH:MM:SS.mmm LEVEL/tag: mensaje` vía
  `logging.Formatter(fmt="%(asctime)s.%(msecs)03d %(levelname)s/%(name)s: %(message)s",
  datefmt="%m-%d %H:%M:%S")`.
- **Niveles estándar** (igual que V/D/I/W/E de logcat): `DEBUG` (detalle interno),
  `INFO` (transacciones — cargar log, recalcular, abrir ventana), `WARNING` (algo raro
  pero recuperable — **cada módulo logueando sus propios warnings puntuales**, tal
  como pidió el usuario), `ERROR`/`logger.exception(...)` (fallas reales).

**Componentes nuevos (Fase 1 — núcleo, sin UI):**
1. `services/app_logging.py` (Qt-free) — configura el root logger una sola vez en
   `main.py`: handler de consola + `logging.handlers.RotatingFileHandler` (a
   `.canlytics_state/logs/canlytics.log`, rotación por tamaño) + un `QtLogHandler`
   custom que **emite un Qt `Signal` por cada log record** — necesario porque los
   workers en `QThread` (Range Diff, Candidate Interpretations, Analyze Data, Signal
   Coverage, Constraint Search...) no pueden tocar un `QWidget` directo desde su
   hilo; el logging tiene que cruzar a la UI por signal/slot igual que todo lo demás
   en esta app (patrón ya establecido, no es nuevo).
   Con solo esta fase ya es útil: "mandame `.canlytics_state/logs/canlytics.log`" en
   el próximo bug reportado, sin ventana ni toggle todavía.

**Fase 2 — ventana en vivo + toggle:**
2. `views/debug_log_window.py` — `QPlainTextEdit` de solo lectura llenado en vivo
   desde el `QtLogHandler`, con filtro por nivel mínimo (combo All/Info/Warning/Error,
   igual que logcat), filtro por tag/módulo (substring sobre el nombre del logger),
   auto-scroll (con pausa si el usuario está revisando algo arriba), y botón
   "Copiar"/"Exportar" para que el usuario te mande el log sin buscar el archivo.
3. Toggle **"Debug mode"** en Settings — sube el root logger de `WARNING` (default,
   silencioso) a `DEBUG` (todo) y habilita abrir la ventana; persistir en
   `SessionStateStore` (mismo patrón que el tema).

**Fase 3 — instrumentación real (el trabajo grande, hacerlo dirigido, no a ciegas):**
4. Reemplazar los `except Exception: pass/continue` ya conocidos (auditoría
   2026-07-18: DBC restore y otros) por `logger.exception(...)` como mínimo — esto
   solo ya destapa fallas hoy completamente silenciosas.
5. Loguear "transacciones" (no cada pixel) en los puntos que ya son la entrada
   pública de cada ViewModel (`start_load`, `recalculate`, `open_window`,
   `set_selected_id`...) y en los signals `started/finished/canceled/failed` que YA
   existen en cada worker — son puntos naturales, agregarles un log de una línea no
   es instrumentación nueva, es aprovechar cableado que ya está ahí.

**Fase 4 (opcional, evaluar después de usar 1-3):** clicks de UI genéricos vía
`QApplication.installEventFilter()` global detectando `clicked`/`triggered`/`toggled`
en widgets con `objectName()` no vacío (la app ya nombra casi todo widget interactivo
para QSS) — riesgo de volverse ruidoso si se hace antes de tiempo; el logcat real
tampoco loguea cada evento de bajo nivel por defecto, el usuario filtra por tag/nivel.
No hacer esta fase salvo que 1-3 resulten insuficientes.

### EPIC Performance y memoria en logs grandes — items 2, 4, 8 ✅ hechos (2026-07-20); 6-7 evaluados

Diagnostico original 2026-07-19 con `candump-2026-07-11_153006.log` en Downloads:
archivo de `204,804,096` bytes (~195 MB), `4,040,230` lineas. El DataFrame final quedaba en
~`908.6 MB` estimados (21 columnas: `TS`, `Bus`, `ID`, `DATA`, `LEN`, `B0..B7`, `D0..D7`).

**Estado real hoy (2026-07-20), tras PERF1 + este EPIC:** con el mismo log real, el
DataFrame final mide **172 MB** (`B0..B7` fuera del esquema -- PERF1, commit
`8bfe2a8` -- y `LEN`/`D0..D7` en `UInt8` en vez de `Int64` -- commit `5a34cf8`).
`load_can_dataframe()` ya no construye ambas variantes candump (compact/spaced) por
carga -- solo la detectada (commit `b19c101`), eliminando ~223MB transitorios por carga.

Contrato real vs. derivado:
- Base necesaria para casi todo el aplicativo: `TS`, `Bus`, `ID`, `LEN`, `DATA`.
- Derivable desde `DATA`: `B0..B7` (hex por byte) y `D0..D7` (byte entero).
- Hoy `B0..B7`/`D0..D7` son contrato practico porque los usan Table, Real-Time,
  Analyze Data, Diff Analyzer, Signal Coverage, decode mux y tests. Quitarlas del esquema
  requiere una migracion coordinada, no un parche local en `can_data_parser.py`.

Hallazgos por ruta/ventana:
- **Carga de log**: `_load_candump_df()` lee todo a `raw`, construye rutas compact/spaced y
  despues deriva 16 columnas de bytes. Es el primer pico de memoria antes de ver la tabla.
- **Tabla principal + filtros**: el DataFrame global se guarda en `data_vm`; el filtro
  incremental conserva `cached_filtered`; `TableModel` guarda otro DataFrame seleccionado.
  Qt virtualiza celdas, pero no evita DataFrames grandes retenidos.
- **Analyze Data**: `precompute_all()` calienta un acumulador por CAN ID. Cada acumulador
  conserva `TS` y hasta 8 series `D` completas para plot/matriz; es rapido al cambiar de ID,
  pero puede ser una segunda copia numerica grande.
- **Diff Analyzer**: el analisis offline usa `slice_window()` + `partition_by("ID")`; Live
  conserva baseline y `LiveByteAccumulator._raw` por byte, lo que crece mientras llega data.
- **Candidate Interpretations**: cada candidato aceptado conserva `timestamps` y `values`;
  `_split_by_mux_case()` materializa grupos por indice; la lista UI tambien puede crecer mucho.
- **Signal Coverage / DBC decode**: escanea todo el log, agrega `_ID_INT`, `_PGN`, `DATA_INT`,
  particiona por PGN/ID y convierte raw/value arrays para estadisticas.
- **Plot / derived signals**: `DecodedSignalCache` retiene arrays por señal; `extend()` usa
  `np.concatenate`, copiando arrays completos en cada append; las formulas crean contextos
  con series decodificadas.
- **Normalizar timestamps**: `data_viewmodel.set_normalize()` re-lee/re-parsea el log completo
  en el hilo principal; es riesgo de congelamiento con logs grandes.

Plan recomendado:
1. **Medicion primero**: ✅ hecho de facto -- cada fix de abajo se midió contra el
   log real antes/después (`df.estimated_size()`, tiempos por fase) en vez de un
   harness separado; no se construyó el harness genérico multi-ruta, no hizo falta.
2. ✅ **Parser sin pico doble** (2026-07-20, commit `b19c101`): `_load_candump_df`
   sniffea el sub-formato candump (compact/spaced) de las primeras líneas y solo
   construye ESA variante -- antes construía ambas regex-extract completas
   siempre, descartando la que no matcheaba (~223MB transitorios + ~0.17s de CPU
   puro desperdiciados por carga, medido en el log real).
3. **Schema base + bytes lazy** -- no hecho en esta forma más agresiva (D0..D7
   sigue residente siempre, no "bajo demanda por ruta"). Lo que SÍ se hizo:
   PERF1 (B0..B7 fuera del esquema por completo, ver arriba) cubre la mitad más
   valiosa de este ítem sin la complejidad de un esquema base + helpers lazy.
4. ✅ **Tipos compactos controlados** (2026-07-20, commit `5a34cf8`): `LEN`/
   `D0..D7` son `UInt8` (antes `Int64`). Auditado exhaustivamente antes de aplicar
   (agente de exploración sobre `services/`/`viewmodels/`/`utils/`/`tests/`):
   todo sitio que reconstruye un valor multibyte desde bytes ya castea
   explícitamente a `UInt64`/`Int64` antes de la operación riesgosa
   (`with_data_int`, `observe_byte`, `detect_carry_alignment`,
   `LiveByteAccumulator`, `mux_detector.py`'s extractors) -- se encontró y
   endureció un solo hueco (`can_decoder.py::extract_signal_raw`'s `mux_expr`,
   dependía de auto-promoción implícita de Polars en vez de un cast explícito).
   Medido: **415MB → 172MB** (-58%) en el DataFrame del log real.
5. **Caches con presupuesto**: ✅ hecho para Analyze precompute (2026-07-19,
   ver sección "Fix de memoria..." arriba) y para `DecodedSignalCache`
   (2026-07-20, ver ítem 8 abajo -- lazy-concat en vez de copiar todo el
   historial). Pendiente: Signal Coverage partitions y Candidate results
   todavía sin el patrón lazy/acotado + botón de liberar.
6. **Ventanas pesadas con contrato explicito** -- no hecho como documentación
   formal por ventana; de facto cada ventana ya sigue alguno de los 4 patrones
   (completo/subconjunto/resumen incremental/downsample) pero no está declarado
   explícitamente en ningún sitio central.
7. **UI virtual/paginada** -- evaluado 2026-07-20 con el log real: una búsqueda
   "Try All" default sobre los 118 IDs produce **1,456 candidatos** (ver hallazgo
   de Candidate Interpretations arriba) -- escala moderada para `QListWidget`
   con un `QListWidgetItem` por fila (y CI5 ya colapsa overlapping antes de
   mostrar). **No se encontró evidencia de que justifique hoy** una reescritura
   a `QAbstractItemModel`/vista virtualizada; revisar si un futuro search de
   rango completo (1-64 bits) produce un orden de magnitud más candidatos.
8. ✅ **Streaming sin copias repetidas** (2026-07-20, commit `0b341ac`):
   `DecodedSignalCache.extend()` hacía `np.concatenate([old, new])` (copia del
   historial completo) en cada chunk entrante -- ahora guarda chunks sin
   concatenar y solo mergea en `get()`, cacheado hasta el próximo `extend()`.
   `TableModel`'s tail-insert `pl.concat(..., rechunk=True)` (otro full-copy por
   tick) throttleado a cada 20 appends, mismo patrón que
   `data_viewmodel.py::_RECHUNK_EVERY_N_FLUSHES` ya usaba para el merge del
   dataframe acumulado.

### Higiene / merges pendientes
- Mergear `feature/range-diff` (Fase 1 + fixes B-01/B-04 de esta sesión) a `dev`.
- Migración de tokens de tema: varios views con colores hardcodeados (ver [UI_DESIGN.md](UI_DESIGN.md)).
- Pase de accesibilidad: tooltips en controles con jerga, mnemónicos, validación inline.

### Arquitectura: interfaz explícita para backends de conexión (no migrar a hexagonal/clean)
Evaluado 2026-07-18: no migrar toda la arquitectura a hexagonal/clean (costo alto, beneficio
marginal — el dominio ya es Qt-free y testeable). Único ítem quirúrgico pendiente: un
`Protocol` `CanSource` común para SSH/Kvaser/replay, hoy sin contrato compartido. Detalle
completo y sketch de código en [CLAUDE.md](CLAUDE.md) § "Interfaz explícita para backends
de conexión". 🟡 (services+viewmodel) — no urgente, no bloquea el pipeline de detección.

### Auditoría de arquitectura (2026-07-18) — hallazgos pendientes de verificar, sin registrar aún
Revisión exhaustiva de 5 agentes en paralelo (capas MVVM, composition root/wiring,
contrato de dataframe, cobertura de tests, salud de código). Encontró 3 posibles bugs
funcionales nuevos no documentados (UI bloqueada al normalizar timestamps, posible fuga
de thread de Candidate Interpretations al cerrar la app, `_full_refresh()` síncrono con
más disparadores de los conocidos), un archivo de ~984 líneas posiblemente muerto
(`pipeline_builder.py`, Basic Mode ya cancelado), dos violaciones de "services Qt-free"
(`dbc_manager.py`, `hmi_video_processor.py`), y `tests/README.md` desactualizado (dice
418 tests, corren 613). **Por pedido explícito del usuario, nada de esto se registró en
BUGS.md todavía** — detalle completo, con archivo:línea y tabla de priorización, en
[CLAUDE.md](CLAUDE.md) § "Auditoría de arquitectura (2026-07-18) — hallazgos pendientes
de verificación". Verificar (vía `/nuevo-bug` + `code-reviewer`) antes de actuar.
