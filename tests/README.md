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
| `test_log_data.py` | `merge_frames` y `is_append_in_order` (append, reordenamiento de cola, normalize) |
| `test_log_export.py` | selección por alcance y exportación candump/ASC/BLF/TRC/CSV con round-trip, cancelación, errores y protección de archivos fuente |
| `test_log_import.py` | importación ASC/BLF/TRC/CSV, timestamps, canales y rechazo de frames no representables |
| `test_continuous_recorder.py` | flush por chunk, recuperación tras fallo, seguridad del marcador y round-trip app/python-can |
| `test_measurement_status.py` | tasa de frames por ventana y umbral de aviso de RAM |
| `test_bus_statistics.py` | fps y periodos globales/por ID, jitter, carga estimada, IDs nuevos/desaparecidos |
| `test_can_decoder.py` | `decode_signal` (LE/BE, scale/offset, int/float, MUX); j1939 PGN matching excluye ids de rango estándar (11 bits) |
| `test_can_send.py` | `services/can_send.py`: resolución de transmit entries, construcción del comando `cansend`, encode de payload DBC |
| `test_analyze_data.py` | `sorted_can_ids`, `detect_mux_cases`, `build_summary`, `build_plot_series`, `shannon_entropy`, `update_periods`, `IncrementalAccumulator` (batch == incremental), `MatrixLiveTracker` |
| `test_bam_reassembly.py` | `assemble_bam_messages` (reensamblado J1939 BAM) |
| `test_bam_decode.py` | `decode_bam_frame` (guards + happy path con DBC stub) y `_find_last_bam_pgn` |
| `test_mux_detector.py` | `detect_fast_mux_patterns`, `build_config_from_options` |
| `test_multi_byte_detection.py` | detección de carry-alineado + formato de hints multi-byte |
| `test_monotonic_changed_set.py` | `compute_changed_set_delta` (usado hoy solo por `analyze_data_viewmodel.py`, ver nota abajo) |
| `test_dbc_manager.py` | `load_dbc` + `resolve_message_name` con un DBC mínimo; detección de encoding utf-8/cp1252; ids de rango estándar nunca resuelven a un mensaje j1939 |
| `test_signal_formatting.py` | `format_signal_value`, `normalize_display_text`, líneas de display del decode |
| `test_realtime_analysis.py` | helpers puros del análisis en tiempo real (delta-t, períodos, bytes mux, agregados); `compute_changed_ids_delta` |
| `test_candidate_interpretations.py` | `_build_candidate_items` + scoring/autocorrelación/bits/mux/endianness/tipo y filtro por bytes |
| `test_constraint_search.py` | normalize/clamp/tiempo-a-absoluto + `search_candidates` (BUGS.md B-21..B-24) |
| `test_kvaser_config.py` | parseo de kwargs, construcción de bus kwargs (incl. `receive_own_messages`), orden de prueba de bitrate, validación de canal Kvaser |
| `test_filters.py` | `apply_filter` (Moving Avg, EMA, Median, Gaussian, Savitzky-Golay, Truncate/Round) |
| `test_plot_sampling.py` | `downsample_series`/`minmax_downsample` (paso/step, casos borde) |
| `test_plot_config.py` | parseo de `.conf` v1/v2, construcción de dict de selector/signal/derived-signal |
| `test_signal_aligner.py` | `align()` y `align_incremental()` (forward-fill, límites de chunk, igualdad con el resultado completo) |
| `test_formula_evaluator.py` | evaluación de fórmulas en sandbox, errores, helpers de señal, `decode_bytes` |
| `test_formula_generator.py` | generación de string de fórmula desde config del pipeline builder |
| `test_decoded_signal_cache.py` | `DecodedSignalCache` (chunks sin concatenar, materialización cacheada) |
| `test_range_diff.py` | `services/range_diff.py`: observe/classify por byte, slicing de ventana, build de reporte, export CSV, dbc hint, significancia Mann-Whitney |
| `test_range_diff_live.py` | `LiveByteAccumulator`/`build_live_diff_report` — invariante incremental == batch |
| `test_xy_plot.py` | alineación temporal as-of, filtro por rango y export CSV de XY |
| `test_mcp_server.py` | sesión headless, herramientas de análisis, límites de escritura, envío CAN opt-in y transporte stdio real |
| `test_signal_coverage.py` | `build_signal_coverage_report` (stats_all/stats_real por señal, PDU1/PDU2, multi-DBC, j1939, cancelación, progreso); `refresh_last_values` incremental |
| `test_pgn_csv_to_dbc.py` | PGN-CSV → DBC (un mensaje por PGN, scale/offset, LE default, dedup de identificadores, round-trip de PGN); regresión contra `fixtures/csv/j1939_generic_map.csv` |
| `test_pgn_scanner.py` | `available_bam_pgns`/`available_j1939_pgns` |
| `test_app_logging.py` | configuración de logging en modo debug |
| `test_debug_log_filter.py` | extracción de nivel de log y filtrado de visibilidad |
| `test_session_state.py` | persistencia de modo debug, `window_prefs` y configuración MUX |
| `test_remote_connection.py` | `RemoteConnection.is_alive()`/`.ping()` (SSH) — requiere `paramiko` |
| `test_table_filter.py` | filtro incremental y append por delta; equivalencia con filtro completo |
| `test_hmi_video_processor.py` | `build_plot_series` de la extracción de video HMI (feature congelada, ver nota abajo) |
| `test_fixtures_real.py` | invariantes genéricas sobre los DBC/log reales de `fixtures/` (carga, `FRAME_SCHEMA`, IDs hex, normalize) |
| `test_real_bam_decode.py` | decode end-to-end del log real con `j1939_test.dbc`: sesión BAM + trama normal |

### `views/` (delegados y formato)

| Archivo | Qué verifica |
|---|---|
| `test_ts_display_delegate.py` | seis decimales para timestamps epoch y fecha/hora con zona |
| `test_frame_context_menu.py` | texto copiado del frame y señal de byte con selector exacto |

### `viewmodels/` (adaptador Qt sobre los services de arriba — timers, señales, wiring)

| Archivo | Qué verifica |
|---|---|
| `test_analyze_data_window_manager.py` | cableado perezoso de Analyze Data, desconexión y liberación al cerrar, recuperación tras fallo de construcción |
| `test_realtime_analysis_window_manager.py` | el manager pasa la zona inicial y Time Config a Real-Time |
| `test_analyze_data_viewmodel.py` | cache del accumulator, precompute, modo Matrix Live |
| `test_can_send_viewmodel.py` | CRUD de transmit entries, ciclo de vida del `QTimer` periódico, tx log, persistencia, señales de conexión y bloqueo de envíos y periódicos durante replay |
| `test_candidate_interpretations_viewmodel.py` | `_ProgressThrottle`, límites de tiempo/bytes y descarte de resultados obsoletos |
| `test_constraint_search_viewmodel.py` | adaptador delgado sobre `constraint_search` |
| `test_data_viewmodel.py` | cadencia de rechunk; `rows_appended`/`dataframe_replaced`; IDs incrementales |
| `test_log_export_viewmodel.py` | progreso y cancelación del worker; revisión de datos evita marcar frames nuevos como guardados |
| `test_continuous_recorder_viewmodel.py` | vaciado de chunks, cierre limpio y protección de todas las rutas de grabación |
| `test_unsaved_capture.py` | estado de captura sin guardar y clasificación de avisos para datos vacíos, guardados o pendientes |
| `test_connection_stream_viewmodel.py` | `is_replay` en replay, SSH, Kvaser y detenido; `last_kvaser_bitrate` (metadata de log): `None` inicial, seteado vía `kvaser_bitrate_resolved`, reseteado en cada `_start_worker()` sin importar el modo |
| `test_measurement_status_viewmodel.py` | conteo incremental y aviso único por cruce del umbral |
| `test_connection_stream_bitrate_probe.py` | lógica de prueba de bitrate Kvaser del `_ConnectionStreamWorker` — requiere `paramiko` |
| `test_connection_stream_disconnect.py` | detección de desconexión en `_stream_lines` (exit-status, EOF, watchdog de idle-ping) — requiere `paramiko` |
| `test_plot_colors.py` | asignación de color de señal (próximo color, señal duplicada) |
| `test_plot_incremental.py` | cache de decode y derivados incrementales (`set_dataframe`, `ingest_raw_chunk`, `align`) |
| `test_plot_xy_series.py` | el ViewModel entrega series decodificadas crudas y derivadas completas para XY |
| `test_analysis_context.py` | validación del contexto, estado compartido y dispatch del menú «Enviar a…» |
| `test_mux_configuration_viewmodel.py` | restauración, validación, persistencia y propagación compartida desde el composition root |
| `test_range_diff_viewmodel.py` | adaptador sobre `range_diff`; Diff Live consume chunks crudos (F1-05); recibe la configuración MUX compartida |
| `test_real_time_analysis_viewmodel.py` | mantenimiento de índice por CAN id, timer de highlight-expiry, independencia del lookup de detalles, activación solo con ventana abierta (`set_enabled`) |
| `test_signal_coverage_viewmodel.py` | mantenimiento de índice por CAN id |
| `test_table_model.py` | persistencia de sort (BUGS.md B-09), inserción por delta y rechunk periódico |

### `config/`

| Archivo | Qué verifica |
|---|---|
| `test_theme.py` | registro de temas, estructura QSS, paleta, `apply_theme` |
| `test_timezone_format.py` | `format_timestamp`/`format_timezone_label` en los distintos modos de tz |

Total actual: **1079 tests** en **72 archivos** (`Ran 1079 tests ... OK`, o menos si falta
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
