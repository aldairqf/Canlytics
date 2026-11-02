# TESTS — Plan de pruebas para Canlytics

> Describe qué tests
> existen y cuáles deberían existir en **`tests/`**. Los tests de regresión
> referencian los bugs de [bugs.md](bugs.md). El mapa de cobertura vivo, por archivo, está
> en **[`tests/README.md`](../tests/README.md)** — este documento no
> lo duplica; se enfoca en el *plan* (setup, prioridades, regresiones pendientes).

## Setup

- **Framework:** `unittest` de la stdlib (**pytest NO está instalado**). Sin `pytest-qt`.
- **Correr todo** (desde la raíz del repo):
  ```bash
  .venv/Scripts/python.exe -m unittest discover -s tests -t . -v
  ```
  `-t .` pone la raíz en `sys.path` para que `import services.…` resuelva.
- **Un módulo / un caso:**
  ```bash
  .venv/Scripts/python.exe -m unittest tests.test_range_diff_viewmodel
  .venv/Scripts/python.exe -m unittest tests.test_kvaser_config.ValidateChannelTests.test_no_devices_raises
  ```
- **Prioridad:** la capa `services/` + `utils/` es **pura y testeable sin correr la app**
  → cúbrela primero. Los tests que tocan Qt (`QApplication` en `setUpModule`, ver
  `test_range_diff_viewmodel.py`) van después y solo cuando el valor lo justifica.
- **Regla de la casa:** al extraer lógica de un ViewModel a un `services/`, **agregar un
  test de caracterización** (así se carvaron `realtime_analysis`, `candidate_interpretations`,
  `kvaser_config`, `signal_formatting`, `analyze_data`, `signal_coverage`, `range_diff`).
- **⚠️ No construir un `QWidget`/`QMainWindow` real dentro de `tests/`** (descubierto y
  confirmado dos veces, 2026-07-18, ver B-13 y B-08): un test con 2 `RangeDiffWindow`
  (`QMainWindow`) y, por separado, uno con un solo `CanIdPanelWidget` (`QWidget` liviano, sin
  ventana) **ambos colgaron bajo `unittest discover -s tests -t .`** — no es acumulación de
  handles de tantos tests previos (el segundo caso colgó siendo de los primeros en
  alfabetizarse, con casi nada corrido antes). En ambos casos, el mismo archivo corrido
  **fuera** de `discover` (`python -m unittest <módulo>` apuntando el módulo directo, o un
  script suelto) pasa rápido y sin problemas. Causa exacta no confirmada — algo en cómo
  `TestLoader.discover()` importa paquetes interactúa mal con cualquier construcción de
  widget real, no solo con `QMainWindow`. Ningún otro test en el repo construye un widget
  real — todos se quedan en ViewModel/servicio (Qt-free o `QObject`+señales sin widgets).
  Para verificar el nivel de vista, usar un smoke test manual de un solo uso (patrón
  `QTimer.singleShot`+`app.exec()`, corrido con `python archivo.py`, **nunca** dentro de
  `tests/`) o `/verify-ui`. Si hace falta un test automatizado de un widget, puede vivir como
  módulo suelto fuera de `tests/` invocado por nombre directo — no confirmado si eso escala,
  usar con cautela.

Total actual: **937 tests** en **56 archivos** (`Ran 937 tests ... OK`) — creció desde 612 con el trabajo de
v0.4.0 (CAN Send, round-trip DBC⇄CSV, metadata de log Kvaser; ver [CLAUDE.md archivado](archive/claude-md-2026-07.md) y
[roadmap archivado](archive/roadmap-2026-07.md) § "v0.4.0").

---

## Regresiones pendientes (1 test por bug abierto de [bugs.md](bugs.md))

Agrupadas por herramienta; orden de ataque sugerido en
[roadmap archivado § Orden de ejecución](archive/roadmap-2026-07.md).

**Diff Analyzer:**
- **B-02** — timestamps A/B: con `tz_mode` seteado, el texto sale por `format_timestamp` (no
  `:g`), y una selección fina del timeline no se degrada al re-aplicarse.
- **B-19** — cerrar con un "Comparar" en curso: `closeEvent` debe esperar/cancelar
  limpiamente; reabrir mientras el job viejo termina no debe ignorar el próximo clic en
  "Comparar" en silencio.

**Real-Time Analysis:**
- **F1-03** — `test_real_time_analysis_viewmodel.py::EnabledLifecycleTests` verifica timers detenidos y chunks ignorados al cerrar, inicio limpio al abrir y que cambiar el intervalo no active una VM deshabilitada.
- **B-03** — "only changes": semántica decidida (hide vs. deselect); un ID que cambia por
  primera vez se agrega sin descartar previos (`compute_changed_ids_delta` ya cubierto en
  `test_realtime_analysis.py`; falta el comportamiento de visibilidad de la vista).
- **B-07** — `highlight_hold` debe expirar en su propio intervalo independientemente del
  valor de `refresh_interval` (actualmente acoplados por compartir timer).
- **B-08** — un ID desmarcado manualmente **antes** de cambiar por primera vez no debe
  re-marcarse automáticamente al empezar a cambiar.

**Candidate Interpretations / Constraint Search:**
- **Cobertura cero confirmada**: `views/candidate_constraint_search.py` (ambas ventanas +
  helpers puros `_time_to_abs`, `_normalize`) no tiene ningún test, ni siquiera los helpers
  fácilmente testeables a nivel de módulo. Empezar por esos antes de B-22/B-23/B-24.
- **B-22** — clamping de input fuera de rango: debe reportarse/avisarse, no solo clampear.
- **B-23** — `_time_to_abs` en modo reloj con un log que cruza medianoche.
- **B-24** — recuento de exclusiones (constraint fuera de ventana de precisión, candidato con
  <2 muestras/varianza cero) debe ser visible, no silencioso.

**Analyze Data:**
- **B-29** — chunks fuera de orden (timestamp skew entre buses) no deben perder contribución
  silenciosa en `AnalyzeDataAccumulator.feed()` — escribir ANTES de multiplicar esta lógica
  en la vista matriz (AN1-AN4).
- Cache de acumulador por ID: revisitar un ID ya visitado en la sesión debe ser instantáneo
  (sin recomputar) — regresión de que la invalidación (nuevos datos / cambio de filtro-tiempo
  / cambio de mux) funciona correctamente, no solo el caso feliz.

## Regresiones ya cerradas esta sesión

- **F1-05** — `tests/test_range_diff_viewmodel.py` cubre el consumo de chunks crudos
  por Diff Live y evita el watermark vulnerable al reordenamiento de `merge_frames`.

- **F1-07** — `tests/test_realtime_analysis_window_manager.py` verifica que el manager
  pasa el modo horario inicial y `TimeConfigViewModel` a Real-Time. Plot actualiza el eje
  de ventanas abiertas mediante la señal de Time Config.

- **F1-06** - `test_can_send_viewmodel.py` bloquea el envío inmediato y la activación periódica durante replay; `test_connection_stream_viewmodel.py` caracteriza `is_replay` en replay, SSH, Kvaser y detenido.
- **F1-04** — tests/test_analyze_data_window_manager.py: el análisis se conecta solo
  con la ventana abierta, libera su estado al cerrarla y no duplica conexiones si falla
  la construcción y se vuelve a abrir.

- **B-01** — `tests/test_range_diff_viewmodel.py::test_emit_current_state_repushes_density_and_ranges`
  (la ventana abierta después de cargar el log recibe densidad + rangos; si no, el timeline
  queda vacío y los cursores A/B no se pueden arrastrar).
- **B-04** — sin test unitario (es UI pura: barra de menú oculta + acciones en toolbar);
  verificado headless con un smoke test de la ventana.
- **B-05** — `tests/test_realtime_analysis.py::RekeyLiveEntriesTests` (5 tests): sin colisión,
  colisión 2-way y 3-way, no contamina `_aggregate_unique_counts`, IDs no relacionados no se
  afectan. Extraída como función pura `rekey_live_entries()` en `services/realtime_analysis.py`.
- **B-13** — `tests/test_range_diff_viewmodel.py::test_options_property_reflects_set_options`
  (el getter `vm.options`); el escenario completo de reabrir la ventana se verificó con un
  smoke test manual, no automatizado (ver la nota de ⚠️ arriba, en Setup).
- **B-26** — `tests/test_analyze_data_viewmodel.py` (nuevo archivo, 2 tests): reabrir debe
  re-emitir `summary_changed` además de `plot_changed`.
- **B-32** — `tests/test_candidate_interpretations_viewmodel.py::CandidateDataframeUpdateTests` + `::MergeCheckedCanIdsTests`
  (2 tests, solo `QObject`): `set_dataframe` conserva resultados durante append y
  `reset_dataframe` los limpia al reemplazar el log.
- **CI6** — `tests/test_candidate_interpretations.py` (`_passes_minimum_requirements`, sin
  `sensitivity`); **CI1/CI2/CI3/CI4** verificados con smoke tests manuales (construyen una
  ventana real, ver la nota ⚠️ de arriba) — orden por score, filtro de score con contador
  en vivo, filtro de endianness, filtro de longitud mínima, y que la selección sigue al
  candidato (por label) al reordenar, no a la fila.

## Tests planeados para features del [roadmap archivado](archive/roadmap-2026-07.md)

- **`tests/test_range_diff_live.py`** (Diff Analyzer Fase 2): invariante del
  `LiveByteAccumulator` (`acc.feed(seq); acc.snapshot() == observe_byte(seq)`) para
  constante, oscilación, contador con wrap 255→0, toggle, ventana vacía; y que
  `build_live_diff_report` produce el mismo `IdDiff` que `build_range_diff_report` para
  rangos A/B equivalentes. Los 36 tests de `test_range_diff.py` deben seguir pasando igual
  (regresión de que el refactor `_diff_bytes` no cambió el modo batch).
- **P1 (handoff simplificado)**: ya no siembra por byte (decisión revisada) — test de que
  abrir Candidate desde el handoff llega con el CAN ID correcto pre-seleccionado; el "saltar
  al candidato más cercano" es opcional y no bloqueante.
- **P2 (multi-byte)**: caracterización de la primitiva de correlación entre bytes vecinos
  (detecta un 16-bit LE sintético por su acarreo; no marca dos bytes independientes).
- **Vectorización de `AnalyzeDataAccumulator.feed()`**: mismo patrón "incremental ==
  recompute" ya usado en el repo — el resultado vectorizado debe ser bit-a-bit idéntico al
  loop Python actual antes de reemplazarlo (los 604 tests existentes de `test_analyze_data.py`
  ya pinnean el comportamiento actual; usarlos como referencia, no reescribirlos).

## Tests nuevos — v0.4.0 (CAN Send, DBC⇄CSV, metadata)

- **`tests/test_can_send.py`** (nuevo) — `resolve_transmit_entry` (DLC válido/inválido, hex
  malformado, id estándar vs. extendido), `encode_dbc_payload` (contra un DBC fixture),
  `build_cansend_command` (padding de dígitos hex estándar vs. extendido).
- **`tests/test_connection_stream_viewmodel.py`** (nuevo) — `LastKvaserBitrateTests`: inicial
  `None`, seteado vía la señal `kvaser_bitrate_resolved`, reseteado en cada `_start_worker()`
  sin importar el modo (evita que un bitrate viejo de Kvaser se filtre a un log SSH/replay).
- **`tests/test_pgn_csv_to_dbc.py`** (extendido) — `DetectCsvOrderTests`,
  `BuildDatabaseFromDbcOrderRowsTests` (señal simple, ID estándar/extendido, signo,
  big-endian, PDU1 con dos CAN ID del mismo PGN quedan separados, mux de 2 casos, selector
  faltante sintetizado, CAN ID vacío se salta, nombre duplicado desambiguado, round-trip
  completo por archivo DBC temporal real), `ManualOrderOverrideTests` (formato no reconocido
  lanza `UnrecognizedCsvOrderError`, `order=` explícito coincide con auto-detección, forzar el
  orden equivocado da cero mensajes en vez de adivinar bien por accidente).
- **`tests/test_can_data_parser.py`** (extendido) — `MetadataCommentLineTests`: una línea
  `#`-prefijada al inicio del log no rompe `load_can_dataframe` (metadata de bitrate Kvaser).
- **`tests/test_signal_coverage.py`** (extendido) — export CSV con las columnas nuevas
  (scale/offset/geometría mux), respetando saltos de línea universales al releer el archivo.

## Fixtures reales

`tests/fixtures/dbc/` y `fixtures/logs/` traen DBC y un log candump reales (pequeños);
los tests que los usan se **SKIPean** si faltan. Ver `tests/fixtures/README.md`.
