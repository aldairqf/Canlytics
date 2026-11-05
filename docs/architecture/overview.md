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
| `viewmodels/` | `QObject` con `Signal`s; dueños de los `QThread`/workers | Adaptadores delgados: la lógica no trivial va a `services/` |
| `views/` | widgets y diálogos | Se suscriben a ViewModels; nunca llaman a `services/` directamente |
| `config/` | defaults, env, i18n (`get_option`/`get_text`), tema | Constantes ajustables en `config/defaults.py` / `DEFAULT_OPTIONS` |

Deuda conocida contra estas reglas (Fase 5 de [../plan.md](../plan.md)):
- `viewmodels/ssh_time_poll_viewmodel.py` posee el worker que consulta la hora del dispositivo por SSH; la vista solo presenta las marcas de tiempo.
- `viewmodels/plot_viewmodel.py` delega el FFT y las exportaciones en servicios; `PlotWindow` conserva la interacción y presenta los resultados.
- `viewmodels/connection_stream_viewmodel.py` conserva el ciclo de vida Qt del worker y adapta estado, chunks y envíos.

`services/can_source.py` define el protocolo Qt-free `CanSource`; `services/can_sources.py`
implementa SSH, Kvaser y replay. `services/can_stream.py` aplica timestamps, batching y flushes
comunes. Los servicios reciben callbacks para cancelar, emitir estado y procesar envíos pendientes;
no importan Qt ni cargan los backends de hardware durante el import.

## Composition root y flujo de datos

`main.py` construye el splash, después `MainWindowViewModel`, después `MainWindow`.
`viewmodels/main_window_viewmodel.py` instancia todos los ViewModels hijos y cablea el
grafo de señales.

`AnalysisContextViewModel` conserva la evidencia compartida entre herramientas. Los menús
«Enviar a…» publican el destino y el contexto; Candidate, Diff, Analyze y Real-Time abren
con el CAN ID o rango disponible, y el envío al plot adjunta bytes, bits y ventana de origen.
Analyze Data, Constraint Search y Plot usan el mismo menú para continuar el análisis desde
los bytes seleccionados, un candidato o una señal ya graficada.
Working DBC está disponible como destino de análisis; abre un diálogo prellenado desde el contexto compartido y guarda a través de `MainWindowViewModel`. La ventana Working DBC permite administrar mensajes y señales mediante operaciones del ViewModel y exportar una copia `.dbc`.
Al enviar desde una fila de byte del Diff, Candidate busca solo en ese byte y en la unión de
las ventanas A/B, excluyendo los frames que quedan entre ambas.
Candidate construye un perfil F6-01 por grupo CAN ID/LEN/MUX en el worker, poda antes del decode los campos sin flips cuando no se incluyen constantes y ajusta la puntuación por clases, límites, evidencia de carry y la heurística CAN-D de signo/endian. Contadores y CRC se mantienen en resultados, pero la vista los oculta por defecto y permite mostrarlos. Reference Correlation alinea candidatos con CSV, señales DBC, otros candidatos o marcadores por ventanas temporales; el worker busca el lag con Spearman/Pearson, evita interpolar huecos mayores a tres intervalos típicos de la referencia y propone escala/offset editables al flujo Working DBC.
`services/range_diff.py` concentra `observe_values` para contar transiciones y valores distintos; `observe_byte` y `ChangeType` añaden la clasificación específica entre ventanas CAN. Analyze, Real-Time, Coverage y Candidate reutilizan la observación con sus tolerancias propias.
`EventMarkersViewModel` persiste eventos ON/OFF por conjunto de fuentes en `SessionStateStore`; su heurística empareja cada ON con el siguiente OFF del mismo nombre y propone rangos inclusivos para Diff. Los cambios de normalización desplazan las marcas junto con los timestamps del log.
`TimeRangeViewModel` conserva el rango escalar inclusivo y el texto del filtro. El composition root lo distribuye a la tabla, Analyze, Candidate y Mux Detection; los rangos A/B propios de Diff y el override puntual de Candidate permanecen separados.
`CanIdPanelWidget` comparte la búsqueda y selección de IDs entre Main, Real-Time, Analyze y Candidate. Main ofrece Ctrl+F para buscar un ID cargado y navegar a su primer frame.
`MuxConfigurationViewModel` conserva las reglas MUX compartidas en `SessionStateStore`; Real-Time,
Analyze y Candidate reciben los cambios para su análisis, y las cuatro ventanas abren el mismo
editor desde ese estado persistido. Para un mismo CAN ID y LEN, una regla exacta tiene prioridad
sobre la regla wildcard; Analyze aplica las reglas según el LEN de cada frame.

El servidor opcional `mcp_server` expone los servicios Qt-free por MCP stdio (`python -m mcp_server`). Cada proceso conserva un log cargado; los artefactos y exportaciones se limitan a `~/.canlytics/mcp`, separado de los logs fuente. `send_frame` solo se registra al arrancar con `--allow-can-send` y cada intento habilitado se añade al TX log.

La app publica la sesión abierta en un canal local autenticado (named pipe en Windows, socket Unix en otros sistemas), descubierto mediante `~/.canlytics/mcp/session-endpoint.json`. Un worker de `MainWindowViewModel` sirve snapshots de estado, contexto y un anillo acotado de frames recientes actualizado por deltas; las consultas devuelven hasta 500 frames y distinguen captura en vivo, replay y modo offline. MCP puede añadir marcadores en memoria, decodificar con los DBC activos y guardar señales validadas en Working DBC mientras la app está abierta. Las dos operaciones DBC se encolan al hilo GUI; guardar actualiza el archivo persistido, la caché y la precedencia de Working DBC. El puente no cambia contexto, carga, exporta ni borra logs ni envía CAN.

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
data_vm.rows_appended → bit_activity_vm (acumula tasas de flip e histogramas solo para los IDs del delta)
data_vm.dataframe_replaced (recarga/clear/reordenamiento) → reconstruye filter_vm y resetea coverage, range_diff, …
```

Analyze Data recibe el chunk crudo para mantener sus acumuladores y Matrix Live; un tracker Qt-free
conserva el último timestamp y los bytes por ID. La matriz solo filtra el historial cuando aparece
un ID nuevo o el tracker detecta que uno plano empezó a moverse.

`dataframe_changed(df_completo)` se conserva por compatibilidad. `rows_appended(delta_df, new_ids)`
evita que los nuevos consumidores recorran la historia completa; si un append altera el orden
temporal, `dataframe_replaced` anuncia el DataFrame completo ya ordenado. El índice de IDs se
actualiza desde cada chunk y solo se vuelve a construir al reemplazar el DataFrame.
Bit Activity resume los pares de tramas consecutivas por ID en un acumulador incremental. Al abrirse
o reemplazarse el DataFrame, reconstruye el acumulador en un worker y después aplica los deltas
pendientes; al cerrar, deja de actualizar la vista. No conserva la secuencia de tramas. Los segmentos
sugeridos pasan su CAN ID y geometría a `AnalysisContext` y pueden seguir el menú común de destinos,
incluido Working DBC para completar y guardar la señal.

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
- La ventana XY es hija de una ventana Plot: selecciona sus series crudas/DBC, BAM/J1939, candidatas o derivadas, y solo las recalcula al aplicar el rango; no recorre el historial en cada chunk.

Inventario y estado real de cada ventana: [../review/2026-11-functional-review.md](../review/2026-11-functional-review.md).

**Inalcanzables hoy, no tocar:**
- **Mux Detection.** Se crea su ViewModel, pero sin manager ni cableado. Regla: no tocar su lógica.
- **HMI Video OCR.** El manager nunca se construye y está congelado. Regla: no tocar.

## DBC

`services/dbc_manager.py` es Qt-free y maneja el catálogo ordenado de DBCs (vía `cantools`). `viewmodels/dbc_manager_viewmodel.py` adapta los cambios con la señal `entries_changed`.
- Matching: `exact`, `j1939` y `bam` (`services/bam_reassembly.py`, `services/bam_decode.py`).
- Import CSV con dos esquemas autodetectados (CAI Order / DBC Order): `services/pgn_csv_to_dbc.py`.
- `DbcManager` gestiona DBCs cargados en modo de solo lectura; la edición vive en el servicio de DBC de trabajo descrito abajo.

`services/working_dbc.py` mantiene un `cantools.Database` editable sin Qt ni escritura sobre los DBC de origen. Valida IDs, longitudes, rangos de bits, conversiones y solapes considerando el endianness y los casos MUX; exporta a un `.dbc` mediante reemplazo atómico. `MainWindowViewModel` lo persiste en `.canlytics_state/working.dbc`, lo registra activo en `DbcManager` y limpia las cachés de decode al guardar. Si tiene mensajes, Working DBC precede a los DBC externos al decodificar; para los IDs que no contiene, se mantiene el orden previo de los externos. El restore carga el DBC de trabajo en el worker existente y conserva esa precedencia.

## Persistencia

`services/session_state.py` (`SessionStateStore`) guarda en `.canlytics_state/` (ignorado por git):
- logs y DBCs recientes;
- copia de los DBCs;
- tema;
- preferencias por ventana (`get_window_prefs`/`set_window_prefs`);
- configuración MUX compartida entre Real-Time, Analyze, Candidate y Diff.

La restauración de DBCs corre en `_DbcRestoreWorker`. Las reglas MUX se validan y se restauran
desde `session.json` al construir `MuxConfigurationViewModel`.

`MainWindowViewModel.shutdown()` detiene los workers de sus consumidores, incluido Candidate
Interpretations. La normalización de un log se parsea en `_NormalizeWorker`; el resultado se aplica
en el hilo UI solo si la fuente y la revisión de los datos siguen vigentes.

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

`BusStatisticsViewModel` consume directamente cada chunk crudo de `chunk_ready`; el servicio
`services/bus_statistics.py` mantiene contadores O(chunk), períodos por CAN ID y detección de
IDs sin actividad durante el umbral configurable. La ventana Bus Statistics muestra el detalle;
la barra resume fps, carga estimada e IDs. La carga usa bitrate Kvaser conocido y una estimación
de bits clásicos CAN, y queda vacía si no hay bitrate o se detecta más de un bus.
Las tasas usan intervalos transcurridos entre la primera y última trama. El servicio no retiene
el historial de timestamps: si detecta un chunk tardío, conserva contadores y fps, pero marca
como no confiables los períodos y jitter de ese CAN ID y la ventana los deja en blanco.

## Plugins

`services/plugin_manager.py` descubre plugins instalados en carpetas o mediante el grupo de
entry points `canlytics.plugins`. Es Qt-free; `PluginViewModel` lo adapta a la pantalla Plugins
del ribbon. Los plugins empiezan desactivados, el usuario guarda la preferencia en
`.canlytics_state/plugins.json`, y cada error de metadata, importación o registro queda asociado
a ese plugin. El SDK `canlytics_sdk` publica el contrato de frames, snapshots de DBC, servicios
Qt-free de análisis y exportación protegida contra sobrescribir fuentes. El código del plugin
se ejecuta dentro del proceso y con permisos del usuario; no hay sandbox. Las extensiones
`PluginAPI` registra ventanas para el grupo Plugins del ribbon, acciones «Enviar a…» y
acciones contextuales que reciben `AnalysisContext`. Las suscripciones entregan chunks crudos
en el hilo GUI y se desconectan al destruir el widget o desactivar el plugin. El contexto permite
leer marcadores de sesión y enviar frames clásicos únicamente por una conexión real activa; cada
intento se refleja en TX Log y replay queda bloqueado.

El servidor MCP también descubre los plugins habilitados y publica sus herramientas registradas
como `p<longitud>_<plugin_id>_<tool_name>`. El prefijo hace inequívoco el espacio de nombres y
mantiene el nombre dentro de 128 caracteres. Las anotaciones del callback generan el esquema de argumentos
validado por el SDK MCP. En el proceso headless, los plugins reciben contexto de lectura y análisis;
las funciones de UI, streaming y envío CAN no están disponibles.

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
