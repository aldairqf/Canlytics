# CAN Analyzer MS4M

Desktop application (PySide6 / Qt) for loading, decoding, visualizing, and analyzing CAN bus logs.

## Features

- Load offline log files (candump compact/spaced and Kvaser Memorator formats)
- Stream live frames over SSH, Kvaser hardware, or replay
- Decode signals against DBC files with `exact` and `j1939` matching modes
- Plot signals with configurable filters (Moving Avg, EMA, Gaussian, Savitzky-Golay, …)
- Real-time analysis: period stats, byte-change heatmap, candidate signal interpretations
- J1939 multi-packet (BAM) reassembly and decoding
- HMI screen recording OCR: extract numeric readings and correlate with CAN signals

## Setup

Requires Python 3.11+. Run all commands from the `CANAnalyzer/` subfolder.

```bash
cd CANAnalyzer

# Create and activate venv (Windows)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

External dependency: the HMI OCR feature requires **Tesseract** installed and on `PATH`
(reachable by `pytesseract`). CAN bus streaming over Kvaser hardware requires the Kvaser
drivers and `python-can[kvaser]`.

## Running

```bash
.venv\Scripts\activate
python main.py
```

## Developer quick-start

`dev_launch.py` starts the app pre-loaded with a DBC and a log file — no clicking through
the UI on every test run. The fixture files under `tests/fixtures/` are ready to use:

```bash
# J1939 mode (default) — candump log + J1939 DBC
python dev_launch.py --dbc tests/fixtures/dbc/j1939_clean.dbc --log tests/fixtures/logs/candump-sample.log

# Exact mode with a custom DBC
python dev_launch.py --dbc path/to/your.dbc --log path/to/your.log --dbc-mode exact
```

## Tests

Characterization tests (stdlib `unittest`, no pytest) cover the `services/` and `utils/`
layers — 175 tests, no hardware required.

```bash
# Run the full suite
python -m unittest discover -s tests -t . -v

# Run a single module
python -m unittest tests.test_kvaser_config

# Run a single test case
python -m unittest tests.test_kvaser_config.ValidateChannelTests.test_no_devices_raises
```

See [tests/README.md](tests/README.md) for the per-module coverage map and
[tests/fixtures/README.md](tests/fixtures/README.md) for the fixture files used in
end-to-end tests.

## Build (Windows executable)

```bash
.venv\Scripts\pyinstaller.exe --clean --noconfirm --distpath "dist\Windows" --workpath "build\Windows" CAN_Analyzer_MS4M.spec
```

Output lands in `dist\Windows\`.

## Architecture

Strict MVVM with one-way data flow. See [../CLAUDE.md](../CLAUDE.md) for the full
architecture reference (layer responsibilities, composition root, DataFrame schema,
threading rules, session persistence, WindowManager pattern).

```
log / connection source
        │
        ▼
  DataViewModel  (dataframe_changed)
        ├──► FilterViewModel ──► TableViewModel ──► table view
        ├──► AnalyzeDataViewModel
        ├──► CandidateInterpretationsViewModel
        └──► MuxDetectionViewModel
```

Key layers:

| Layer | Purpose |
|---|---|
| `models/` | Plain dataclasses — no Qt, no I/O |
| `utils/` | Stateless pure helpers (hex↔bytes, ID parsing, filters, …) |
| `services/` | All logic and I/O: parsing, DBC management, decoding, analysis, OCR |
| `viewmodels/` | Qt `QObject` adapters — own background threads, emit signals |
| `views/` | Qt widgets — subscribe to VM signals, forward user intent back |
| `config/` | Defaults, env vars, JSON-overridable config/i18n |

Session state (recent logs, DBCs) is persisted in `.canalyzer_state/` in the working
directory (git-ignored).
