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
| `test_dbc_manager.py` | servicio Qt-free: carga, `resolve_message_name`, encoding utf-8/cp1252 e IDs estándar frente a J1939 |
| `test_dbc_manager_viewmodel.py` | servicio importable sin cargar PySide6 y adaptador que emite al mutar el catálogo |
| `test_working_dbc.py` | CRUD Qt-free, rangos LE/BE, solapes y MUX, validación de mensajes/señales y exportación `.dbc` con round-trip de decodificación |
| `test_working_dbc_persistence.py` | registro activo, guardado en session state, administración CRUD transaccional por ViewModel, protección de fuentes al exportar, defaults del diálogo de señal y restauración en el worker con decode disponible tras reiniciar |
| `test_signal_formatting.py` | `format_signal_value`, formatos hex/dec/bits de payload, `normalize_display_text`, líneas de display del decode |
| `test_realtime_analysis.py` | helpers puros del análisis en tiempo real (delta-t, períodos, bytes mux, agregados); `compute_changed_ids_delta` |
| `test_offline_realtime.py` | índice offline por CAN ID, selección temporal, timestamps empatados, Delta T y posiciones temporales |
| `test_offline_realtime_viewmodel.py` | worker de indexación, snapshots sincronizados, controles live-only y cambio de modo |
| `test_candidate_interpretations.py` | `_build_candidate_items` + scoring, actividad F6-01, poda de campos constantes, signo/endian, CRC, bits/mux/tipo y filtro por bytes |
| `test_constraint_search.py` | normalize/clamp/tiempo-a-absoluto + `search_candidates` (BUGS.md B-21..B-24) |
| `test_kvaser_config.py` | parseo de kwargs, construcción de bus kwargs (incl. `receive_own_messages`), orden de prueba de bitrate, validación de canal Kvaser |
| `test_filters.py` | `apply_filter` (Moving Avg, EMA, Median, Gaussian, Savitzky-Golay, Truncate/Round) |
| `test_plot_sampling.py` | `downsample_series`/`minmax_downsample` (paso/step, casos borde) |
| `test_plot_config.py` | parseo de `.conf` v1/v2, construcción de dict de selector/signal/derived-signal |
| `test_signal_aligner.py` | `align()` y `align_incremental()` (forward-fill, límites de chunk, igualdad con el resultado completo) |
| `test_formula_evaluator.py` | evaluación de fórmulas en sandbox, errores, helpers de señal, `decode_bytes` |
| `test_formula_generator.py` | generación de string de fórmula desde config del pipeline builder |
| `test_decoded_signal_cache.py` | `DecodedSignalCache` (chunks sin concatenar, materialización cacheada) |
| `test_trace_columns.py` | preferencias persistidas de trace, validación y cálculo de Δt por ID completo e incremental |
| `test_range_diff.py` | `services/range_diff.py`: observación compartida de secuencias, clasificación por byte, slicing de ventana, comparación de logs independientes, reporte, export CSV, dbc hint y significancia Mann-Whitney |
| `test_range_diff_live.py` | `LiveByteAccumulator`/`build_live_diff_report` — invariante incremental == batch |
| `test_xy_plot.py` | alineación temporal as-of, filtro por rango y export CSV de XY |
| `test_plot_statistics.py` | estadísticas inclusivas entre cursores, rango invertido, muestras no finitas y rango vacío |
| `test_mcp_server.py` | sesión headless, herramientas de análisis, límites de escritura, envío CAN opt-in y transporte stdio real |
| `test_mcp_session.py` | snapshot Qt-free, anillo acotado, filtros, contexto, marcadores, límites y estado de conexión |
| `test_mcp_session_ipc.py` | autenticación, ciclo de vida del IPC, acciones en hilo GUI, herramientas MCP stdio de DBC, persistencia con rollback y composición de MainWindowViewModel |
| `test_signal_coverage.py` | `build_signal_coverage_report` (stats_all/stats_real por señal, PDU1/PDU2, multi-DBC, j1939, cancelación, progreso); `refresh_last_values` incremental |
| `test_pgn_csv_to_dbc.py` | PGN-CSV → DBC (un mensaje por PGN, scale/offset, LE default, dedup de identificadores, round-trip de PGN); regresión contra `fixtures/csv/j1939_generic_map.csv` |
| `test_pgn_scanner.py` | `available_bam_pgns`/`available_j1939_pgns` |
| `test_app_logging.py` | configuración de logging en modo debug |
| `test_debug_log_filter.py` | extracción de nivel de log y filtrado de visibilidad |
| `test_event_markers.py` | validación, pairing ON/OFF, rangos Diff, aislamiento por fuente y persistencia de marcas |
| `test_session_state.py` | persistencia de modo debug, marcadores de evento, `window_prefs` y configuración MUX |
| `test_remote_connection.py` | `RemoteConnection.is_alive()`/`.ping()` (SSH) — requiere `paramiko` |
| `test_table_filter.py` | filtro incremental y append por delta; equivalencia con filtro completo |
| `test_frame_trace.py` | comparacion de bytes por ID y filtros de contenido/mascara/DLC |
| `test_hmi_video_processor.py` | `build_plot_series` de la extracción de video HMI (feature congelada, ver nota abajo) |
| `test_fixtures_real.py` | invariantes genéricas sobre los DBC/log reales de `fixtures/` (carga, `FRAME_SCHEMA`, IDs hex, normalize) |
| `test_real_bam_decode.py` | decode end-to-end del log real con `j1939_test.dbc`: sesión BAM + trama normal |
| `test_plugin_manager.py` | importación de carpetas y ZIPs, validación de tamaño y rutas, descubrimiento, registro de extensiones y limpieza |
| `test_reference_correlation.py` | correlación temporal Pearson/Spearman por ventanas, lags, referencias CSV/DBC/candidato/marcadores, huecos, ajuste lineal, progreso y cancelación |
| `test_bit_activity.py` | acumulador incremental de tasas de flip, límites y clases sugeridos e histogramas por byte |
| `test_state_tracker.py` | transiciones por bit, bytes no disponibles, timestamps empatados, equivalencia batch/chunks y reemplazo de fuente |

### `views/` (delegados y formato)

| Archivo | Qué verifica |
|---|---|
| `test_ts_display_delegate.py` | seis decimales para timestamps epoch y fecha/hora con zona |
| `test_frame_context_menu.py` | texto copiado del frame y señal de byte con selector exacto |
| `test_can_id_jump_dialog.py` | búsqueda global de CAN ID, prefijo `0x`, resultados inexistentes y comportamiento compartido del panel |
| `test_plugins_dialog.py` | estado visible de plugins, error de carga y toggle conectado al ViewModel |

### `viewmodels/` (adaptador Qt sobre los services de arriba — timers, señales, wiring)

| Archivo | Qué verifica |
|---|---|
| `test_analyze_data_window_manager.py` | cableado perezoso de Analyze Data, desconexión y liberación al cerrar, recuperación tras fallo de construcción |
| `test_realtime_analysis_window_manager.py` | el manager pasa la zona inicial y Time Config a Real-Time |
| `test_analyze_data_viewmodel.py` | cache del accumulator, precompute, modo Matrix Live |
| `test_can_send_viewmodel.py` | CRUD de transmit entries, ciclo de vida del `QTimer` periódico, tx log, persistencia, señales de conexión y bloqueo de envíos y periódicos durante replay |
| `test_candidate_interpretations_viewmodel.py` | `_ProgressThrottle`, límites de tiempo/bytes y descarte de resultados obsoletos |
| `test_constraint_search_viewmodel.py` | adaptador delgado sobre `constraint_search` |
| `test_data_viewmodel.py` | cadencia de rechunk; `rows_appended`/`dataframe_replaced`; IDs incrementales y fuentes de sesión |
| `test_table_trace_filter_viewmodel.py` | anotación incremental de cambios y Δt por ID antes de filtros de rango/contenido; reuso del historial anotado |
| `test_log_export_viewmodel.py` | progreso y cancelación del worker; revisión de datos evita marcar frames nuevos como guardados |
| `test_continuous_recorder_viewmodel.py` | vaciado de chunks, cierre limpio y protección de todas las rutas de grabación |
| `test_unsaved_capture.py` | estado de captura sin guardar, prompts y normalización asíncrona; error, Clear y cambios concurrentes preservan el estado |
| `test_time_range_viewmodel.py` | propagación del rango, shutdown de Candidate y rollback/cancelación de normalización conservan timezone |
| `test_connection_stream_viewmodel.py` | `is_replay` en replay, SSH, Kvaser y detenido; bitrate Kvaser, streaming replay y envío encolado durante RX |
| `test_can_source.py` | imports Qt-free, fuentes SSH/Kvaser/replay, probing, cierre concurrente, timestamps y batching compartido |
| `test_ssh_time_poll.py` | imports Qt-free, parsing y cierre SSH; lifecycle de worker, terminación inmediata y reemplazo del poller |
| `test_plot_viewmodel_services.py` | cálculo FFT y delegación de exportación CSV/imagen desde `PlotViewModel` |
| `test_measurement_status_viewmodel.py` | conteo incremental y aviso único por cruce del umbral |
| `test_connection_stream_bitrate_probe.py` | probing Kvaser en `KvaserCanSource` con buses falsos, cancelación y fallos de apertura |
| `test_connection_stream_disconnect.py` | detección de exit-status, EOF y pérdida de SSH en `SshCanSource`, sin Qt ni hardware |
| `test_plot_colors.py` | asignación de color de señal (próximo color, señal duplicada) |
| `test_plot_incremental.py` | cache de decode, derivados incrementales y origen de tiempo normalizado de las series (`set_dataframe`, `ingest_raw_chunk`, `align`) |
| `test_plot_xy_series.py` | el ViewModel entrega series decodificadas crudas y derivadas completas para XY |
| `test_analysis_context.py` | validación y geometría sugerida del contexto, estado compartido y dispatch de Working DBC en el menú «Enviar a…» |
| `test_mux_configuration_viewmodel.py` | restauración, validación, persistencia y propagación compartida desde el composition root |
| `test_range_diff_viewmodel.py` | adaptador sobre `range_diff`; Diff Live consume chunks crudos (F1-05); compara logs en worker sin reemplazar el log actual; recibe la configuración MUX compartida |
| `test_real_time_analysis_viewmodel.py` | mantenimiento de índice por CAN id, timer de highlight-expiry, independencia del lookup de detalles, activación solo con ventana abierta (`set_enabled`) |
| `test_signal_coverage_viewmodel.py` | mantenimiento de índice por CAN id |
| `test_table_model.py` | persistencia de sort (BUGS.md B-09), inserción por delta/rechunk, formato de DATA, Δt incremental y Name DBC |
| `test_plugin_viewmodel.py` | carga de plugins habilitados, resumen por CAN ID y desconexión de listeners O(chunk) al cerrar |

### `config/`

| Archivo | Qué verifica |
|---|---|
| `test_theme.py` | registro de temas, estructura QSS, paleta, `apply_theme` |
| `test_f5_06_i18n.py` | localización de etiquetas y valores internos estables de los combos del constructor |
| `test_timezone_format.py` | `format_timestamp`/`format_timezone_label` en los distintos modos de tz |

Total actual: **1307 tests** en **99 archivos** (`Ran 1307 tests ... OK`, o menos si falta
`paramiko` en el entorno — los 3 archivos que lo requieren no se coleccionan, no fallan).

## Notas de arquitectura relevantes al leer estos tests

- **`monotonic_changed_set.py`** mide deltas de membresía de IDs en Analyze Matrix Live. La observación de valores de bytes y señales se comparte desde `range_diff.py`; la clasificación de ventanas sigue cubierta por `ChangeType`.
- **`test_hmi_video_processor.py`** es el único test del pipeline HMI/OCR — el resto
  (`services/hmi_roi_tracker.py`, `hmi_numeric_reader.py`, `hmi_frame_stabilizer.py`,
  `hmi_ocr.py`, `hmi_video_loader.py`, `viewmodels/hmi_video_extractor_viewmodel.py`) no
  tiene tests. La feature está congelada desde 2026-07-19 y excluida del build desde
  2026-07-21 (ver CLAUDE.md), así que el gap es real pero de baja prioridad.

## Verificaciones de interfaz fuera de `tests/`

- `scripts/verify_can_id_jump.py`: shortcut Ctrl+F y salto a la primera fila.
- `scripts/verify_f307_outputs.py`: envíos de Analyze, Constraint Search y Plot con sus contextos; guarda capturas en `%TEMP%\canlytics-f3-07-verify`.


## Fixtures reales

- `test_mcp_server.py` cubre registro dinámico de herramientas MCP de plugins habilitados y ocultamiento de las herramientas de plugins desactivados.

`fixtures/dbc/` y `fixtures/logs/` contienen DBC y un log candump reales (pequeños) para
varios de los tests de arriba. Son opcionales: si faltan, esos tests se **SKIPean**. Ver
[fixtures/README.md](fixtures/README.md).
