# Arquitectura — Canlytics

Fuente de verdad de cómo está construida la app **hoy**. Si cambias algo de lo que se
describe aquí, actualiza este archivo en el mismo commit. Las decisiones con su porqué
están en [decisions/](decisions/README.md). El histórico completo de la etapa anterior
está en [../archive/claude-md-2026-07.md](../archive/claude-md-2026-07.md).

## Qué es

Canlytics es una app de escritorio PySide6 (Qt) para **ingeniería inversa de señales CAN**.
El flujo típico es:

1. Conectarse a un equipo (Kvaser / SSH candump / replay de un log).
2. Mover el equipo y ver qué bytes reaccionan.
3. Proponer interpretaciones (bits, orden, escala).
4. Confirmarlas en un plot.

También carga logs offline (candump compacto o espaciado, Kvaser Memorator, ASC, BLF, TRC y CSV) y decodifica
con DBC. El DBC cargado es **solo de ayuda**: la detección no depende de él.

Perfil de tráfico real (logs de campo, Fase 02): 680–910 fps, 29–43 IDs, 1 bus. Diez
minutos son ≈500K frames. Úsalo para benchmarks, no supuestos sintéticos.

## Capas (MVVM estricto, flujo de datos en un sentido)

| Capa | Contiene | Regla |
|---|---|---|
| `models/` | dataclasses de dominio (`Signal`, `MuxConfigEntry`, `TransmitEntry`, …) | Sin Qt, sin I/O |
| `utils/` | funciones puras (`can_id`, `can_bytes`, `timezone_format`, `filters`) | Sin Qt, sin I/O, sin estado. Úsalas antes de reimplementar |
| `services/` | toda la lógica e I/O: parseo, DBC, decodificación, análisis, conexiones | Sin widgets. Importable sin hardware (`can`/`paramiko` con import perezoso). Testeable con `unittest` |
| `viewmodels/` | `QObject` con `Signal`s; dueños de los `QThread`/workers | Adaptador delgado: la lógica no trivial va a `services/` |
| `views/` | widgets y diálogos | Se suscriben a ViewModels; nunca llaman a `services/` directamente |
| `config/` | defaults, env, i18n (`get_option`/`get_text`), tema | Constantes ajustables en `config/defaults.py` / `DEFAULT_OPTIONS` |

Deuda conocida contra estas reglas (Fase 5 de [../plan.md](../plan.md)):
- `services/dbc_manager.py` es un `QObject`.
- `views/settings/connection_dialog.py` define un `QThread` que abre SSH.
- `views/plot/plot_window.py` llama a FFT y export directamente.
- `viewmodels/connection_stream_viewmodel.py` contiene lógica de hardware.

## Composition root y flujo de datos

`main.py` construye el splash, después `MainWindowViewModel`, después `MainWindow`.
`viewmodels/main_window_viewmodel.py` instancia todos los ViewModels hijos y cablea el
grafo de señales.

```
ConnectionStreamViewModel.chunk_ready (chunk crudo, pre-merge)
  ├─> data_vm.append_df ──(QTimer 100 ms)──> merge_frames
  │                                             ├─> rows_appended(delta) ─> filter_vm ─> table_vm.append_rows ─> TableModel
  │                                             └─> dataframe_changed(df completo) [compatibilidad y consumidores existentes]
  │                                                          ├─> analyze_data_vm.set_dataframe        [solo con ventana abierta]
  │                                                          ├─> signal_coverage_vm.set_dataframe     [siempre, O(1)]
  │                                                          ├─> range_diff_vm.set_dataframe          [siempre]
  │                                                          ├─> candidate_interpretations_vm         [solo con ventana abierta]
  │                                                          └─> plot_vm.set_dataframe                [por ventana de plot]
  ├─> range_diff_vm.ingest_live_chunk     [siempre; acumula solo si Live está activo]
  ├─> real_time_analysis_vm.ingest_df      [solo con ventana abierta; timers también]
  ├─> signal_coverage_vm.ingest_df         [siempre]
  ├─> analyze_data_vm.ingest_raw_chunk     [solo con ventana abierta]
  └─> plot_vm.ingest_raw_chunk             [por ventana de plot]
data_vm.rows_appended (delta, IDs nuevos; solo append ordenado) → filter_vm → TableModel.append_rows
data_vm.dataframe_replaced (recarga/clear/reordenamiento) → reconstruye filter_vm y resetea coverage, range_diff, …
```

Analyze Data recibe el chunk crudo para mantener sus acumuladores y Matrix Live; un tracker Qt-free
conserva el último timestamp y los bytes por ID. La matriz solo filtra el historial cuando aparece
un ID nuevo o el tracker detecta que uno plano empezó a moverse.

`dataframe_changed(df_completo)` se conserva por compatibilidad. `rows_appended(delta_df, new_ids)`
evita que los nuevos consumidores recorran la historia completa; si un append altera el orden
temporal, `dataframe_replaced` anuncia el DataFrame completo ya ordenado. El índice de IDs se
actualiza desde cada chunk y solo se vuelve a construir al reemplazar el DataFrame.

Plot conserva los decodes crudos por chunks y agrega incrementalmente las fórmulas derivadas con
operaciones puntuales sobre señales, bytes o frames nuevos. Las fórmulas con `align()` retienen el
último valor conocido por entrada y alinean el eje temporal del chunk; las fórmulas que dependen de
la historia (como reducciones y acumulaciones) se evalúan completas. `dataframe_replaced` limpia
los caches para reconstruir el estado desde la nueva fuente.
El filtro de la tabla conserva el DataFrame fuente para cambios de criterios, pero en una captura
normal filtra solo cada delta. `TableModel.append_rows` notifica inserciones de filas; los filtros
completos siguen usando `set_dataframe`.

**Invariantes del streaming:**
- Ningún consumidor debe hacer trabajo O(df completo) por flush. Hoy hay violaciones conocidas, y la Fase 2 del plan las elimina (ADR 001).
- Un watermark por cantidad de filas sobre el df acumulado **no es seguro**: si un chunk llega desordenado, `merge_frames` reordena desde el primer timestamp afectado; esa cola puede incluir toda la base cuando el chunk llega antes que ella. Por eso los consumidores incrementales leen el chunk crudo de `chunk_ready` (patrón de `signal_coverage_vm.ingest_df` y `range_diff_vm.ingest_live_chunk`).
- Sin tope de RAM: la historia completa se conserva (ADR 002).

Cada ViewModel expone `shutdown()`, encadenado desde `MainWindowViewModel.shutdown()`.

## El DataFrame es el contrato

Los frames viajan como **Polars DataFrame** con `FRAME_SCHEMA` (`services/can_data_parser.py`):

| Columna | Tipo |
|---|---|
| `TS` | Float64, epoch en segundos |
| `Bus`, `ID` | Utf8; ID en hex normalizado |
| `DATA` | Utf8, hex |
| `LEN` | UInt8 |
| `D0..D7` | UInt8 |

El orden de columnas para mostrar está en `config/defaults.py` (`DEFAULT_COLUMNS`, `REAL_TIME_ANALYSIS_COLUMNS`). `B0..B7` ya **no existen**: las etiquetas hex se derivan con `utils.can_bytes.byte_value_to_hex()`. Leer un byte más allá de `LEN` es un bug, no padding. Antes de hacer aritmética fuera de 0–255, castea a un tipo más ancho.

Carga de logs: `services/can_data_parser.py` y `services/can_log.py` (`CANLog`). El parser soporta candump/Kvaser y ASC/BLF/TRC/CSV.
Los readers de `python-can` se importan de forma perezosa y producen `FRAME_SCHEMA`.
Los frames CAN FD, error y remotos se rechazan porque el esquema actual no los representa.
El merge se realiza en `services/log_data.py::merge_frames`.

## Ventanas secundarias

Cada herramienta tiene un `*WindowManager` en `MainWindow`.
- Ventana de instancia única: hereda `views/base_window_manager.py::BaseWindowManager` e implementa `_create_window()`.
- Varias ventanas a la vez: lleva su propio dict (`PlotWindowManager`).
- Toda ventana secundaria usa `Qt.WA_DeleteOnClose`. Sin eso, la ventana y sus timers y curvas viven para siempre.
- Las ventanas que procesan datos en vivo se conectan al abrirse y se desconectan al destruirse (patrón de `CandidateInterpretationsWindowManager`).

Inventario y estado real de cada ventana: [../review/2026-11-functional-review.md](../review/2026-11-functional-review.md).

**Inalcanzables hoy, no tocar:**
- **Mux Detection.** Se crea su ViewModel, pero sin manager ni cableado. Regla: no tocar su lógica.
- **HMI Video OCR.** El manager nunca se construye y está congelado. Regla: no tocar.

## DBC

`services/dbc_manager.py` maneja un conjunto ordenado de DBCs (vía `cantools`) que se activan uno por uno.
- Matching: `exact`, `j1939` y `bam` (`services/bam_reassembly.py`, `services/bam_decode.py`).
- Import CSV con dos esquemas autodetectados (CAI Order / DBC Order): `services/pgn_csv_to_dbc.py`.
- No hay escritura ni edición de señales. Eso llega en la Fase 4 del plan: DBC de trabajo (ADR 003).

## Persistencia

`services/session_state.py` (`SessionStateStore`) guarda en `.canlytics_state/` (ignorado por git):
- logs y DBCs recientes;
- copia de los DBCs;
- tema;
- preferencias por ventana (`get_window_prefs`/`set_window_prefs`).

La restauración de DBCs corre en `_DbcRestoreWorker`. La configuración de mux **no** se persiste (Fase 3).

La exportación usa `services/log_export.py` (Qt-free) y `LogExportViewModel`, que posee el
worker de `QThread`. Los formatos salen por `python-can`; el writer termina en un archivo
temporal antes de reemplazar el destino. Un snapshot exportado solo limpia el estado de
captura sin guardar si no hubo cambios durante el worker.

La captura activa conecta sus chunks crudos directamente a la cola de `ContinuousRecorderViewModel`
(sin pasar por la cola de eventos de la UI); este los escribe en un candump incremental en otro
`QThread` y fuerza el flush por chunk. Un marcador en la
carpeta configurable (`continuous_recording_directory`) identifica sesiones interrumpidas;
al abrir, la vista ofrece cargar el archivo en la sesión actual. El aviso de datos sin guardar
incluye la ruta de la grabación activa.

`MeasurementStatusViewModel` consume chunks y deltas de filas, y publica el conteo, los fps y el
working set del proceso a la barra de estado; el cálculo del umbral y las lecturas del sistema
operativo viven en `services/measurement_status.py`. La barra también presenta conexión, DBC
activos, filtro temporal y zona horaria. El guardián compara el working set con el menor entre el
límite absoluto y la fracción de RAM física configurados en `DEFAULT_OPTIONS`. Al superarlo,
ofrece guardar el snapshot y limpiar; la captura se detiene y drena antes del snapshot, y la
memoria solo se limpia si la exportación tuvo éxito.

## Configuración, i18n, tema, íconos, ribbon

- `config/app_config.py` mezcla `DEFAULT_OPTIONS` + `UI_STRINGS` con un JSON externo indicado por `CANLYTICS_CONFIG`. Lee opciones y textos con `get_option(...)`/`get_text(...)`, nunca hardcodeados.
- Tema: `config/theme.py` (`Theme` con tokens, `apply_theme`). Después de cambiar de tema, llama a `views/icons.py::clear_icon_cache()`.
- Íconos: Lucide (MIT) en `assets/icons/`. Para usar uno, se pone el SVG en esa carpeta y se llama `icon("slug")`. `PySide6.QtSvg` debe seguir en `hiddenimports`.
- Ribbon: `views/widgets/ribbon_bar.py` (main) y `views/plot/plot_ribbon.py`, montados con `setMenuWidget`. El `menuBar()` queda oculto pero vivo para mantener los atajos. Detalle visual en [../ui-design.md](../ui-design.md).

## Hilos

Todo trabajo largo (carga, restore, análisis, streaming) corre en un `QThread` propiedad de un ViewModel y se comunica por señales. Patrón: `started→run`, después `finished/canceled/failed→quit→cleanup`. Los diálogos de espera muestran **% y ETA** (`EtaProgressDialog`).

El worker de conexión es un loop bloqueante. Llama a `QCoreApplication.processEvents()` en cada iteración para recibir los envíos de CAN Send en cola.

## Build

`Canlytics.spec` + `_build_common.py` generan un onefile y un onedir en un solo `Analysis()`. Si agregas una dependencia o un import dinámico, actualiza `collect_app_hiddenimports()` y los excludes. La versión vive solo en `config/version.py` y se propaga a la ventana, al About y al spec.
