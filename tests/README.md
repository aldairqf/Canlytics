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
| `test_can_decoder.py` | `decode_signal` (LE/BE, scale/offset, int/float, MUX) |
| `test_bam_reassembly.py` | `assemble_bam_messages` (reensamblado J1939 BAM) |
| `test_mux_detector.py` | `detect_fast_mux_patterns` (contrato/invariantes) |
| `test_dbc_manager.py` | `load_dbc` + `resolve_message_name` con un DBC mínimo |
| `test_signal_formatting.py` | `format_signal_value`, `normalize_display_text` |
| `test_realtime_analysis.py` | helpers puros del análisis en tiempo real (delta-t, períodos, bytes mux, agregados) |
| `test_candidate_interpretations.py` | `_build_candidate_items` + scoring/bits/mux/endianness |
| `test_kvaser_config.py` | parseo de kwargs, construcción de bus kwargs, validación de canal Kvaser |
| `test_filters.py` | `apply_filter` (Moving Avg, EMA, Median, Gaussian, Savitzky-Golay, Truncate/Round) |
| `test_plot_sampling.py` | `downsample_series` (paso/step, casos borde) |
| `test_bam_decode.py` | `decode_bam_frame` (guards + happy path con DBC stub) y `_find_last_bam_pgn` |
| `test_fixtures_real.py` | invariantes genéricas sobre los DBC/log reales de `fixtures/` (carga, `FRAME_SCHEMA`, IDs hex, normalize) |
| `test_real_bam_decode.py` | decode end-to-end del log real con `j1939_clean.dbc`: sesión BAM + trama normal |
| `test_analyze_data.py` | `sorted_can_ids`, `detect_mux_cases`, `build_summary`, `build_plot_series`, `shannon_entropy`, `update_periods` |

Total actual: **175 tests** (`Ran 175 tests ... OK`).

## Fixtures reales

`fixtures/dbc/` y `fixtures/logs/` contienen DBC y un log candump reales (pequeños) para
los dos últimos módulos. Son opcionales: si faltan, esos tests se **SKIPean**. Ver
[fixtures/README.md](fixtures/README.md).
