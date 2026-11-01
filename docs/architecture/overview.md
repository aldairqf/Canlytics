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

También carga logs offline (candump compacto o espaciado, Kvaser Memorator) y decodifica
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
  ├─> data_vm.append_df ──(QTimer 100 ms)──> merge_frames ──> dataframe_changed(df completo)
  │                                                          ├─> filter_vm ─> table_vm ─> TableModel (tabla principal)
  │                                                          ├─> analyze_data_vm.set_dataframe        [siempre]
  │                                                          ├─> signal_coverage_vm.set_dataframe     [siempre, O(1)]
  │                                                          ├─> range_diff_vm.set_dataframe          [siempre]
  │                                                          ├─> candidate_interpretations_vm         [solo con ventana abierta]
  │                                                          └─> plot_vm.set_dataframe                [por ventana de plot]
  ├─> real_time_analysis_vm.ingest_df      [solo con ventana abierta; timers también]
  ├─> signal_coverage_vm.ingest_df         [siempre]
  ├─> analyze_data_vm.ingest_raw_chunk     [siempre]
  └─> plot_vm.ingest_raw_chunk             [por ventana de plot]
data_vm.dataframe_replaced (recarga/clear) → resetean su estado incremental: coverage, range_diff, …
```

**Invariantes del streaming:**
- Ningún consumidor debe hacer trabajo O(df completo) por flush. Hoy hay violaciones conocidas, y la Fase 2 del plan las elimina (ADR 001).
- Un watermark por cantidad de filas sobre el df acumulado **no es seguro**: `merge_frames` re-ordena todo el df por TS si un chunk llega desordenado. Por eso los consumidores incrementales leen el chunk crudo de `chunk_ready` (patrón de `signal_coverage_vm.ingest_df`).
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

Detección de formato y carga: `services/can_data_parser.py` y `services/can_log.py` (`CANLog`). El merge está en `services/log_data.py::merge_frames`.

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
