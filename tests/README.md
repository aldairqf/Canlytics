# Tests de caracterización (red de seguridad del refactor)

Estos tests **capturan el comportamiento actual** del código para que la reestructuración
no pueda romper funcionalidad de forma silenciosa. No buscan ser una especificación ideal:
documentan lo que el código hace *hoy*. La mayoría cubre la capa `services/`/`utils/`
(lógica pura, sin Qt), pero también hay un grupo de tests sobre `viewmodels/*` que
verifican el cableado Qt (señales, timers, wiring hacia los services ya testeados) —
esos instancian `QApplication`/`QCoreApplication` y son un tipo de test distinto,
complementario, no redundante con los de `services/`.

## Cómo correrlos

Desde la carpeta `CANAnalyzer/` (la que contiene `main.py`):

```bash
python -m unittest discover -s tests -t . -v
```

`-t .` pone la raíz del proyecto en `sys.path` para que `import services.…` resuelva.

Sin dependencia de pytest: usan solo `unittest` de la stdlib. Requieren los paquetes ya
presentes en el entorno: `polars`, `numpy`, `cantools`, `PySide6`. `test_remote_connection.py`,
`test_connection_stream_bitrate_probe.py` y `test_connection_stream_disconnect.py` además
requieren `paramiko` — si no está instalado, esos 3 archivos fallan al importar en vez de
correr (no son un fallo real de la suite, es una dependencia opcional del entorno).

## Qué cubren

### `services/` y `utils/` (lógica pura, sin Qt)

| Archivo | Servicio caracterizado |
|---|---|
| `test_utils.py` | `utils/can_bytes`, `utils/can_id`, `utils/dbc_payload`, `utils/j1939`, `utils/timezone_format` |
| `test_can_data_parser.py` | parseo candump/Kvaser, `frame_dict`, `normalize_can_id`, `load_can_dataframe`, detección de variante |
| `test_log_data.py` | `merge_frames` (orden/sort/normalize) |
| `test_can_decoder.py` | `decode_signal` (LE/BE, scale/offset, int/float, MUX); j1939 PGN matching excluye ids de rango estándar (11 bits) |
| `test_can_send.py` | `services/can_send.py`: resolución de transmit entries, construcción del comando `cansend`, encode de payload DBC |
| `test_analyze_data.py` | `sorted_can_ids`, `detect_mux_cases`, `build_summary`, `build_plot_series`, `shannon_entropy`, `update_periods`, `IncrementalAccumulator` (batch == incremental) |
| `test_bam_reassembly.py` | `assemble_bam_messages` (reensamblado J1939 BAM) |
| `test_bam_decode.py` | `decode_bam_frame` (guards + happy path con DBC stub) y `_find_last_bam_pgn` |
| `test_mux_detector.py` | `detect_fast_mux_patterns`, `build_config_from_options` |
| `test_multi_byte_detection.py` | detección de carry-alineado + formato de hints multi-byte |
| `test_monotonic_changed_set.py` | `compute_changed_set_delta` (usado hoy solo por `analyze_data_viewmodel.py`, ver nota abajo) |
| `test_dbc_manager.py` | `load_dbc` + `resolve_message_name` con un DBC mínimo; detección de encoding utf-8/cp1252; ids de rango estándar nunca resuelven a un mensaje j1939 |
| `test_signal_formatting.py` | `format_signal_value`, `normalize_display_text`, líneas de display del decode |
| `test_realtime_analysis.py` | helpers puros del análisis en tiempo real (delta-t, períodos, bytes mux, agregados); `compute_changed_ids_delta` |
| `test_candidate_interpretations.py` | `_build_candidate_items` + scoring/autocorrelación/bits/mux/endianness/tipo |
| `test_constraint_search.py` | normalize/clamp/tiempo-a-absoluto + `search_candidates` (BUGS.md B-21..B-24) |
| `test_kvaser_config.py` | parseo de kwargs, construcción de bus kwargs (incl. `receive_own_messages`), orden de prueba de bitrate, validación de canal Kvaser |
| `test_filters.py` | `apply_filter` (Moving Avg, EMA, Median, Gaussian, Savitzky-Golay, Truncate/Round) |
| `test_plot_sampling.py` | `downsample_series`/`minmax_downsample` (paso/step, casos borde) |
| `test_plot_config.py` | parseo de `.conf` v1/v2, construcción de dict de selector/signal/derived-signal |
| `test_signal_aligner.py` | `align()` (vacío, forward-fill) |
| `test_formula_evaluator.py` | evaluación de fórmulas en sandbox, errores, helpers de señal, `decode_bytes` |
| `test_formula_generator.py` | generación de string de fórmula desde config del pipeline builder |
| `test_decoded_signal_cache.py` | `DecodedSignalCache` (chunks sin concatenar, materialización cacheada) |
| `test_range_diff.py` | `services/range_diff.py`: observe/classify por byte, slicing de ventana, build de reporte, export CSV, dbc hint, significancia Mann-Whitney |
| `test_range_diff_live.py` | `LiveByteAccumulator`/`build_live_diff_report` — invariante incremental == batch |
| `test_signal_coverage.py` | `build_signal_coverage_report` (stats_all/stats_real por señal, PDU1/PDU2, multi-DBC, j1939, cancelación, progreso); `refresh_last_values` incremental |
| `test_pgn_csv_to_dbc.py` | PGN-CSV → DBC (un mensaje por PGN, scale/offset, LE default, dedup de identificadores, round-trip de PGN); regresión contra `fixtures/csv/j1939_generic_map.csv` |
| `test_pgn_scanner.py` | `available_bam_pgns`/`available_j1939_pgns` |
| `test_app_logging.py` | configuración de logging en modo debug |
| `test_debug_log_filter.py` | extracción de nivel de log y filtrado de visibilidad |
| `test_session_state.py` | persistencia de modo debug y de `window_prefs` |
| `test_remote_connection.py` | `RemoteConnection.is_alive()`/`.ping()` (SSH) — requiere `paramiko` |
| `test_table_filter.py` | equivalencia filtro incremental vs. de una sola pasada |
| `test_hmi_video_processor.py` | `build_plot_series` de la extracción de video HMI (feature congelada, ver nota abajo) |
| `test_fixtures_real.py` | invariantes genéricas sobre los DBC/log reales de `fixtures/` (carga, `FRAME_SCHEMA`, IDs hex, normalize) |
| `test_real_bam_decode.py` | decode end-to-end del log real con `j1939_test.dbc`: sesión BAM + trama normal |

### `viewmodels/` (adaptador Qt sobre los services de arriba — timers, señales, wiring)

| Archivo | Qué verifica |
|---|---|
| `test_analyze_data_viewmodel.py` | cache del accumulator, precompute, modo Matrix Live |
| `test_can_send_viewmodel.py` | CRUD de transmit entries, ciclo de vida del `QTimer` por envío periódico, tx log, persistencia vía `SessionStateStore`, reacción a `running_changed`/`send_succeeded`/`send_failed` |
| `test_candidate_interpretations_viewmodel.py` | `_ProgressThrottle` |
| `test_constraint_search_viewmodel.py` | adaptador delgado sobre `constraint_search` |
| `test_data_viewmodel.py` | cadencia de rechunk en el streaming-flush (`_RECHUNK_EVERY_N_FLUSHES`) vía `append_df` |
| `test_connection_stream_bitrate_probe.py` | lógica de prueba de bitrate Kvaser del `_ConnectionStreamWorker` — requiere `paramiko` |
| `test_connection_stream_disconnect.py` | detección de desconexión en `_stream_lines` (exit-status, EOF, watchdog de idle-ping) — requiere `paramiko` |
| `test_plot_colors.py` | asignación de color de señal (próximo color, señal duplicada) |
| `test_plot_incremental.py` | cache de decode incremental (`set_dataframe`, `ingest_raw_chunk`) |
| `test_range_diff_viewmodel.py` | adaptador delgado sobre `range_diff` |
| `test_real_time_analysis_viewmodel.py` | mantenimiento de índice por CAN id, timer de highlight-expiry, independencia del lookup de detalles |
| `test_signal_coverage_viewmodel.py` | mantenimiento de índice por CAN id |
| `test_table_model.py` | persistencia de sort activo al refrescar (BUGS.md B-09), throttle de rechunk en tail-append |

### `config/`

| Archivo | Qué verifica |
|---|---|
| `test_theme.py` | registro de temas, estructura QSS, paleta, `apply_theme` |
| `test_timezone_format.py` | `format_timestamp`/`format_timezone_label` en los distintos modos de tz |

Total actual: **879 tests** en **52 archivos** (`Ran 879 tests ... OK`, o 865 si falta
`paramiko` en el entorno — los 3 archivos que lo requieren no se coleccionan, no fallan).

## Notas de arquitectura relevantes al leer estos tests

- **`monotonic_changed_set.py` no es (todavía) el primitivo compartido que su docstring
  sugiere.** Solo lo usa `analyze_data_viewmodel.py` hoy — `realtime_analysis.py` y
  `range_diff.py` mantienen su propia lógica de "qué cambió" por separado, sin unificar.
  `test_monotonic_changed_set.py` testea correctamente solo esa función pura; no asumas
  que cubre las otras dos rutas.
- **`test_hmi_video_processor.py`** es el único test del pipeline HMI/OCR — el resto
  (`services/hmi_roi_tracker.py`, `hmi_numeric_reader.py`, `hmi_frame_stabilizer.py`,
  `hmi_ocr.py`, `hmi_video_loader.py`, `viewmodels/hmi_video_extractor_viewmodel.py`) no
  tiene tests. La feature está congelada desde 2026-07-19 y excluida del build desde
  2026-07-21 (ver CLAUDE.md), así que el gap es real pero de baja prioridad.

## Fixtures reales

`fixtures/dbc/` y `fixtures/logs/` contienen DBC y un log candump reales (pequeños) para
varios de los tests de arriba. Son opcionales: si faltan, esos tests se **SKIPean**. Ver
[fixtures/README.md](fixtures/README.md).
