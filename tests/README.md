# Tests de caracterización (red de seguridad del refactor)

Estos tests **capturan el comportamiento actual** de la capa `services/` (lógica pura,
sin Qt) para que la reestructuración no pueda romper funcionalidad de forma silenciosa.
No buscan ser una especificación ideal: documentan lo que el código hace *hoy*.

## Cómo correrlos

Desde la carpeta `CANAnalyzer/` (la que contiene `main.py`):

```bash
python -m unittest discover -s tests -t . -v
```

`-t .` pone la raíz del proyecto en `sys.path` para que `import services.…` resuelva.

Sin dependencia de pytest: usan solo `unittest` de la stdlib. Requieren los paquetes ya
presentes en el entorno: `polars`, `numpy`, `cantools`, `PySide6`.

## Qué cubren

| Archivo | Servicio caracterizado |
|---|---|
| `test_utils.py` | `utils/can_bytes`, `utils/can_id`, `utils/timezone_format` |
| `test_can_data_parser.py` | parseo candump/Kvaser, `frame_dict`, `normalize_can_id`, `load_can_dataframe` |
| `test_log_data.py` | `merge_frames` (orden/sort/normalize) |
| `test_can_decoder.py` | `decode_signal` (LE/BE, scale/offset, int/float, MUX); j1939 PGN matching excludes 11-bit standard-range ids |
| `test_bam_reassembly.py` | `assemble_bam_messages` (reensamblado J1939 BAM) |
| `test_mux_detector.py` | `detect_fast_mux_patterns` (contrato/invariantes) |
| `test_dbc_manager.py` | `load_dbc` + `resolve_message_name` con un DBC mínimo; ids de rango estándar (11 bits) nunca resuelven a un mensaje j1939 |
| `test_signal_formatting.py` | `format_signal_value`, `normalize_display_text` |
| `test_realtime_analysis.py` | helpers puros del análisis en tiempo real (delta-t, períodos, bytes mux, agregados); `compute_changed_ids_delta` (grew vs. reset para la selección "Changes Only" del panel de CAN IDs) |
| `test_candidate_interpretations.py` | `_build_candidate_items` + scoring/bits/mux/endianness |
| `test_kvaser_config.py` | parseo de kwargs, construcción de bus kwargs, validación de canal Kvaser |
| `test_filters.py` | `apply_filter` (Moving Avg, EMA, Median, Gaussian, Savitzky-Golay, Truncate/Round) |
| `test_plot_sampling.py` | `downsample_series` (paso/step, casos borde) |
| `test_bam_decode.py` | `decode_bam_frame` (guards + happy path con DBC stub) y `_find_last_bam_pgn` |
| `test_fixtures_real.py` | invariantes genéricas sobre los DBC/log reales de `fixtures/` (carga, `FRAME_SCHEMA`, IDs hex, normalize) |
| `test_real_bam_decode.py` | decode end-to-end del log real con `j1939_clean.dbc`: sesión BAM + trama normal |
| `test_analyze_data.py` | `sorted_can_ids`, `detect_mux_cases`, `build_summary`, `build_plot_series`, `shannon_entropy`, `update_periods` |
| `test_signal_coverage.py` | `build_signal_coverage_report` (parallel stats_all/stats_real per signal, sentinel scales to bit width, byte_aligned property, PDU1/PDU2 classification, one item per CAN ID when a PGN has multiple sources, cancellation, multiple active DBCs, j1939 mode, progress reporting); `refresh_last_values` (incremental last-value-only refresh from a new frame slice, exact/j1939/muxed signals, stats_real never promoted from None by the incremental path) |
| `test_pgn_csv_to_dbc.py` | `services/pgn_csv_to_dbc.py`: PGN-CSV → DBC conversion (one message per PGN, scale/offset, LE default when no "Byte order" column, identifier sanitizing/dedup, PGN round-trips through the generated frame id); multi-row regression against `fixtures/csv/j1939_generic_map.csv` |

Total actual: **418 tests** (`Ran 418 tests ... OK`).

## Fixtures reales

`fixtures/dbc/` y `fixtures/logs/` contienen DBC y un log candump reales (pequeños) para
los dos últimos módulos. Son opcionales: si faltan, esos tests se **SKIPean**. Ver
[fixtures/README.md](fixtures/README.md).
