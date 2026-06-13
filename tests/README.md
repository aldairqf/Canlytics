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
