> **Archivado (2026-11-01).** Histórico tal cual estaba fuera del repo. No es fuente de verdad: lo vigente está en `AGENTS.md`, `docs/plan.md` y `docs/architecture/`.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentación del proyecto

Los docs viven en la **carpeta contenedora** `CAN ANALIZER/` (fuera del repo git
`CANAnalyzer/`), separados por tema. Este CLAUDE.md guarda **arquitectura + convenciones +
detalle de implementación**; para producto/bugs/pruebas/UI, la fuente de verdad es:

| Doc | Contenido |
|-----|-----------|
| **[ROADMAP.md](ROADMAP.md)** | Backlog de producto y secuencia de trabajo. Norte: **detectar señales offline y online** (pipeline de 4 etapas, prioridades P1–P4, EPIC Diff Analyzer, vista matriz de Analyze) |
| **[BUGS.md](BUGS.md)** | Bugs reales verificados (id, severidad, `archivo:línea`, escenario, estado). Flujo: `/nuevo-bug`, `/fix-bug` |
| **[TESTS.md](TESTS.md)** | Plan de pruebas (setup unittest, regresiones pendientes); el mapa de cobertura vivo está en `CANAnalyzer/tests/README.md` |
| **[UI_DESIGN.md](UI_DESIGN.md)** | Sistema de tema/iconos/ribbon, estado del audit de UI, reglas de interacción |
| **[README_ROADMAP.md](README_ROADMAP.md)** | Plan de contenido para el README público: catálogo de herramientas a nivel usuario (no dev) con estado real — funciona / congelado / deshabilitado |

Las secciones extensas de plan más abajo en este archivo se están migrando a esos docs;
ante conflicto, mandan ROADMAP/BUGS/TESTS/UI_DESIGN.

## What this is

A PySide6 (Qt) desktop application for loading, decoding, visualizing, and analyzing
CAN bus logs. It loads offline log files (candump / Kvaser Memorator formats), streams
live frames over SSH / Kvaser / replay, decodes signals against DBC files, plots
signals, and includes an OCR-based tool that extracts numeric readings from HMI screen
recordings to correlate them with CAN data.

## Commands

The project root (git repo, code, venv) is the **`CANAnalyzer/`** subfolder — run all
commands from there.

```bash
cd CANAnalyzer

# Run the app (Windows venv shown; activate the venv first)
.venv\Scripts\activate
python main.py

# Install dependencies
pip install -r requirements.txt

# Run the characterization test suite (stdlib unittest — pytest is NOT installed)
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v

# Run a single test module / case
.venv/Scripts/python.exe -m unittest tests.test_kvaser_config
.venv/Scripts/python.exe -m unittest tests.test_kvaser_config.ValidateChannelTests.test_no_devices_raises

# Build a standalone Windows executable -- produces BOTH a onefile .exe and a
# onedir folder (Canlytics-X.Y.Z-win-x64-dir/) under dist\Windows, from one Analysis() pass
.venv\Scripts\pyinstaller.exe --clean --noconfirm --distpath "dist\Windows" --workpath "build\Windows" Canlytics.spec

# Build a labeled test/alpha exe without touching config/version.py
# (produces Canlytics-<version>-<label>-Windows.exe; unset the var for a normal release build)
$env:CANLYTICS_BUILD_SUFFIX = "alpha"
.venv\Scripts\pyinstaller.exe --clean --noconfirm --distpath "dist\Windows" --workpath "build\Windows" Canlytics.spec
Remove-Item Env:\CANLYTICS_BUILD_SUFFIX
```

No linter is configured. External runtime dependency: the HMI OCR feature needs
**Tesseract** installed and reachable by `pytesseract`.

### Git workflow

Active branches: `dev` (integration) → feature branches (e.g. `feature/derived-signals`).
All work on feature branches; merge into `dev` with `--no-ff` when the feature is done.
**No push** — remote has SSL issues; push manually when needed.

#### Estado de `master` (revisado 2026-07-16)

`master` **ya no está atrasado** — el commit `7ec7d73` ("release: merge dev into
master, bump version to 0.2.0") es un **squash merge** (un solo padre, no un merge
commit real) que trajo el árbol completo de `dev` a esa fecha. Si vas a comparar
`master` vs `dev`, `git log master..dev` **no sirve** para saber si el contenido ya
está — compara con `git diff master dev --stat` (contenido), no con el historial de
ancestros, porque un squash no deja ancestría aunque el contenido sí haya llegado.

Sigue pendiente el próximo ciclo normal de `/merge-dev` + `/release` para todo lo
acumulado en `dev`/ramas feature desde ese squash (incluida la rama
`feature/range-diff`, ver más abajo). Push manual (SSL issues):

```bash
git config push.followTags true   # configurar una sola vez
git checkout master
git merge --no-ff dev -m "release: merge dev into master"
git push origin master
```

**Project slash commands** (defined in `.claude/commands/`):

| Command | What it does |
|---------|-------------|
| `/test [module]` | Run the full test suite (or a single module) with the project venv |
| `/commit [hint]` | Stage and create atomic commits following Conventional Commits |
| `/merge-dev` | Merge current feature branch into `dev` with `--no-ff` |
| `/build` | Build `dist\Windows\Canlytics-X.Y.Z.exe` via PyInstaller (clears lock on `localpycs` if needed) |
| `/release [patch\|minor\|major]` | Bump version in `config/version.py`, commit `chore(release): bump version to X.Y.Z`, and create git tag `vX.Y.Z` |
| `/verify-ui [flow]` | Launch Canlytics and drive a specific flow (load a fixture log, open a window, click a control) to confirm a change actually works — not just that it imports |
| `/nuevo-bug [síntoma]` | Verify a bug (via `code-reviewer`) and register it in `BUGS.md` with the house format (id, severity, file:line, scenario) |
| `/fix-bug B-NN` | Regression-first fix: red test → minimal fix → green → full suite → update `BUGS.md` |

**Commit rules** (enforced by `/commit`):
- Format: `type(scope): summary` in English, imperative, ≤ 60 chars subject.
- Body: max 3 bullets, only if it adds context. Never list files one by one.
- **NEVER** add `Co-Authored-By` or any AI signature lines — hard rule from the user.
- No push (remote has SSL issues).

### Versioning

Single source of truth: **[`config/version.py`](CANAnalyzer/config/version.py)** — edit only this file to change the version.

```python
APP_VERSION = "0.1.0"   # SemVer: MAJOR.MINOR.PATCH
```

Propagation (all read from `config/version.py`, never hardcoded):

| Where | What changes |
|-------|-------------|
| `main.py` | `app.setApplicationVersion(APP_VERSION)` |
| `views/main_window.py` | Window title `"Canlytics  vX.Y.Z"` |
| `views/settings/about_dialog.py` | About dialog body |
| `Canlytics.spec` | Onefile/onedir filenames `Canlytics-X.Y.Z-<platform>(.exe/-dir)` + Windows PE metadata |

**SemVer policy:**

| Bump | When |
|------|------|
| `PATCH` (0.1.**x**) | Bugfixes, UI tweaks, refactors |
| `MINOR` (0.**x**.0) | New complete feature (e.g. CAN Send tool) |
| `MAJOR` (**x**.0.0) | Breaking change to `.conf` / `.canlytics_state` schema |

**Release workflow:**
```
/release patch    # or minor / major
/build            # produces dist\Windows\Canlytics-X.Y.Z.exe
```
`/release` bumps `config/version.py`, commits `chore(release): bump version to X.Y.Z`,
and creates git tag `vX.Y.Z`. No push (SSL).

### Useful agents (`.claude/agents/`)

Spawn these after or during implementation to catch problems early:

| Agent | When to use |
|-------|-------------|
| `qa-verifier` | After any code change — runs the full characterization test suite and reports failures with tracebacks |
| `qt-mvvm-reviewer` | After a feature lands — checks MVVM layering, signal wiring correctness, and convention adherence |
| `ui-ux-auditor` | Before starting a window redesign — produces a prioritized findings report per window |
| `ui-ux-designer` | For layout, theming, iconography, or component styling tasks inside the Qt/PySide6 app |
| `code-reviewer` | Rigorous bug-hunt on a diff — finds real defects (file:line + failure scenario), separates CONFIRMED from PLAUSIBLE |
| `test-engineer` | Writing/extending characterization tests, especially after carving logic out of a ViewModel into a service |
| `refactor-architect` | Structural moves that must not change behavior (extracting a service, executing a documented perf plan) |
| `Explore` | Quick targeted symbol/file lookups ("where is X defined?") without burning main-context budget |

Typical review pipeline after a feature commit: `ui-ux-designer` → `qt-mvvm-reviewer` → `qa-verifier`. For a
plain bug-fix or refactor, `code-reviewer` → `qa-verifier` is usually enough.

### Tests

`tests/` holds **characterization tests** (stdlib `unittest`, no pytest) that pin the
*current* behavior of the Qt-free `services/` + `utils/` layers — they are the safety net
for refactors, not an ideal spec. Run them from the `CANAnalyzer/` root (the `-t .` flag
puts the project root on `sys.path` so `import services.…` resolves). They need only the
packages already in the env (`polars`, `numpy`, `cantools`, `PySide6`) — no hardware
backends. See [tests/README.md](CANAnalyzer/tests/README.md) for the per-file coverage map.
**When you extract logic out of a ViewModel into a service, add a characterization test
for it** (this is how `realtime_analysis`, `candidate_interpretations`, `kvaser_config`,
`signal_formatting`, and `analyze_data` were carved out safely).

## Architecture

Strict **MVVM** with a one-way data flow. Keep these layers separate — Views never touch
services or domain logic directly; they go through a ViewModel.

- **`models/`** — plain dataclasses / domain objects (`Signal`, `FrameSelector`,
  `HmiRoi`, `MuxConfigEntry`, …). No Qt, no I/O.
- **`utils/`** — small, stateless pure functions shared across layers (`can_bytes`
  hex↔bytes, `can_id` parse/sort keys, `timezone_format` labels, `filters`,
  `plot_sampling`). No Qt, no I/O, no domain state. Reach here before re-implementing a
  primitive — e.g. parse a CAN id with `utils.can_id.can_id_to_int`, not a local helper.
- **`services/`** — all logic and I/O: log parsing, DBC management, decoding, OCR,
  remote connections, persistence. No Qt widgets; heavy work runs on `QThread` workers
  owned by ViewModels. Pure algorithmic logic that has no Qt/threading dependency lives
  here too (e.g. `realtime_analysis`, `candidate_interpretations`, `signal_formatting`,
  `kvaser_config`, `analyze_data`) so it can be unit-tested without a running app — keep
  these importable without hardware backends (lazy-import `can`/`paramiko` inside the
  functions that need them, as `kvaser_config` does).
- **`viewmodels/`** — `QObject` subclasses exposing Qt `Signal`s. Bridge services to
  views; own background threads/workers and emit results as signals. A ViewModel should
  stay a thin Qt adapter — push non-trivial computation down into a `services/` helper.
- **`views/`** — Qt widgets/dialogs. Subscribe to ViewModel signals, render, forward
  user intent back to the ViewModel.
- **`config/`** — defaults, env, and a JSON-overridable config/i18n layer.

### Composition root and signal wiring

[main.py](CANAnalyzer/main.py) builds a splash screen, then `MainWindowViewModel` → `MainWindow`.
**[viewmodels/main_window_viewmodel.py](CANAnalyzer/viewmodels/main_window_viewmodel.py) is the central
composition root**: it instantiates every child ViewModel and wires the cross-VM signal
graph in `__init__`. The core pipeline is:

```
log/connection source ──> data_vm (dataframe_changed) ──┬──> filter_vm ──> table_vm ──> TableModel ──> table view
                                                         ├──> analyze_data_vm
                                                         ├──> candidate_interpretations_vm
                                                         └──> mux_detection_vm
```

When changing how loaded data propagates, start here — most features hang off
`data_vm.dataframe_changed`. ViewModels expose a `shutdown()` that
`MainWindowViewModel.shutdown()` chains to stop background threads cleanly.

### The dataframe is the contract

CAN frames flow through the app as **Polars DataFrames** with a fixed schema defined in
[services/can_data_parser.py](CANAnalyzer/services/can_data_parser.py) (`FRAME_SCHEMA`) and column
order in [config/defaults.py](CANAnalyzer/config/defaults.py) (`DEFAULT_COLUMNS`,
`REAL_TIME_ANALYSIS_COLUMNS`). Columns: `TS, Bus, ID, LEN, DATA, B0..B7` (hex strings)
plus `D0..D7` (int byte values). Preserve this schema when touching parsing, merging
([services/log_data.py](CANAnalyzer/services/log_data.py) `merge_frames`), or table rendering.

Log format detection (candump compact/spaced, Kvaser Memorator) lives in
`can_data_parser.py` via regex; `CANLog` ([services/can_log.py](CANAnalyzer/services/can_log.py)) is
the loader entry point.

### Secondary windows: the WindowManager pattern

Each auxiliary feature (plots, real-time analysis, analyze-data, candidate
interpretations, mux detection, HMI video) is owned by a `*WindowManager` held on
`MainWindow`. A manager lazily creates its window + per-window ViewModel, tracks open
instances (e.g. `PlotWindowManager` keeps a `dict[PlotWindow, PlotViewModel]` so multiple
plot windows can coexist), and fans out cross-cutting state like timezone changes to all
open windows. Follow this pattern when adding a new top-level window.

For the common single-instance case, subclass
[views/base_window_manager.py](CANAnalyzer/views/base_window_manager.py) (`BaseWindowManager`):
implement `_create_window()` and the base handles the create-once / show / raise /
activate cycle and clears its reference on `destroyed`. Managers that need multiple
coexisting windows (plots) keep their own dict instead.

### DBC decoding and matching

[services/dbc_manager.py](CANAnalyzer/services/dbc_manager.py) manages an ordered, individually
activatable set of loaded DBCs (via `cantools`). Matching supports multiple modes —
`exact`, `j1939`, and `bam` — and J1939 multi-packet (BAM) reassembly is handled by
[services/bam_reassembly.py](CANAnalyzer/services/bam_reassembly.py) and
[services/bam_decode.py](CANAnalyzer/services/bam_decode.py). Decoded output is produced by
`InterpretationViewModel` + the `can_decoder` / `can_frame_formatter` services.

### Session persistence

[services/session_state.py](CANAnalyzer/services/session_state.py) (`SessionStateStore`) persists
recent logs/DBCs and a snapshot of loaded DBCs into a **`.canlytics_state/`** directory
in the current working directory (git-ignored). It copies DBC files into
`.canlytics_state/dbcs/` so sessions can be restored even if originals move; restoration
runs on a background `_DbcRestoreWorker` thread.

### Configuration / i18n

[config/app_config.py](CANAnalyzer/config/app_config.py) merges `DEFAULT_OPTIONS` +
`UI_STRINGS` with an optional external JSON file pointed to by the
`CANLYTICS_CONFIG` env var ([config/env.py](CANAnalyzer/config/env.py)). Read tunables and
user-facing strings via `get_option(...)` / `get_text(...)` rather than hardcoding.

### Theme system

[config/theme.py](CANAnalyzer/config/theme.py) defines a `Theme` frozen dataclass with
design tokens (colors, radius, padding). `THEMES` holds `"Dark"` and `"Light"` entries.
`apply_theme(app, name)` builds a `QPalette` + QSS string and applies them globally.
The active theme is persisted in `SessionStateStore` (`get_theme()`/`set_theme()`) and
restored before the splash screen so the app starts in the user's last theme.
The Settings menu exposes a `QActionGroup`-backed radio submenu for switching themes.

Call `clear_icon_cache()` from `views/icons.py` after applying a new theme so cached
icon pixmaps (keyed on color) are regenerated with the new palette.

### Icon system

[views/icons.py](CANAnalyzer/views/icons.py) is the single icon entry point. It loads
SVGs from `assets/icons/` (Lucide MIT set), substitutes `currentColor` with the active
theme's foreground color, and caches rendered `QPixmap`s via `@lru_cache`.

```python
from views.icons import icon, app_icon, clear_icon_cache

icon("plus")            # QIcon, default 20 px, theme fg color
icon("save", size=16)  # override size
app_icon()             # multi-resolution QIcon from assets/canlytics.svg
clear_icon_cache()     # call after theme switch
```

`PySide6.QtSvg` must **not** be in the PyInstaller excludes list (it is in
`hiddenimports`). If you add a new SVG to `assets/icons/`, no code change is needed —
just drop the file and call `icon("name")`.

**Icon source:** All icons come from the **Lucide** open-source set (MIT license).
Browse and download at **https://lucide.dev/icons/** — search by name, download the
SVG, and drop it into `assets/icons/` using the Lucide slug as the filename
(e.g. `circle-help.svg` → `icon("circle-help")`). Stroke width is 2, size 24×24,
`currentColor` — the icon system substitutes the theme foreground automatically.

### Ribbon bar

The main window and plot window both use an Excel/SolidWorks-style ribbon bar placed
via `QMainWindow.setMenuWidget(ribbon)` — this puts the widget in the menu-bar slot
without an extra container.  The hidden `menuBar()` (`setVisible(False)`) keeps all
`QAction` shortcuts alive because `Qt::WindowShortcut` context fires even when the menu
bar widget is invisible.

| File | Role |
|------|------|
| [views/widgets/ribbon_button.py](CANAnalyzer/views/widgets/ribbon_button.py) | `RibbonButton` (QToolButton, icon+label, 60×60), `RibbonGroup` (label at bottom), `RibbonTabButton` (checkable tab pill) |
| [views/widgets/ribbon_bar.py](CANAnalyzer/views/widgets/ribbon_bar.py) | `RibbonBar` + `RibbonCallbacks` for the main window (Home / Analysis / Settings) |
| [views/plot/plot_ribbon.py](CANAnalyzer/views/plot/plot_ribbon.py) | `PlotRibbonBar` + `PlotRibbonActions` for plot windows (Signals / View / Cursor / Tools) |

**Tab activation** — `btn.setProperty("active", bool)` + `unpolish/polish/update()` is
required to trigger the `[active="true"]` QSS selector repaint.

**Checkable toggle buttons** — use `blockSignals` in the `action.toggled` handler to
prevent the double-toggle loop:
```python
action.toggled.connect(lambda v: (btn.blockSignals(True), btn.setChecked(v), btn.blockSignals(False)))
```

**Theme icon refresh in secondary windows** — `PlotRibbonBar` connects
`QGuiApplication.instance().paletteChanged` → `reload_icons()` so plot windows auto-
update icons after a theme switch without needing a callback from the main window.

**Collapse / auto-hide** — Both `RibbonBar` and `PlotRibbonBar` support an
Excel-style "Show Tabs only" mode:
- `_TAB_H = 24` px (tab row), `_CONTENT_H = 80` px (stack). `setFixedHeight(TAB_H + CONTENT_H)`
  is called explicitly so Qt's `QMainWindowLayout` reserves the correct space and the
  central widget never overlaps the ribbon.
- A `▲/▼` `QToolButton` (24×24) at the right of the tab row toggles anchored ↔ collapsed.
  F10 (`QShortcut`, `WindowShortcut` context) does the same.
- When collapsed, `enterEvent` shows the stack temporarily (expands to 104 px);
  `leaveEvent` hides it again. The stack is only made invisible — it is never destroyed.
- `reload_icons()` also updates the collapse button icon after a theme switch.

### HMI video OCR pipeline

[viewmodels/hmi_video_extractor_viewmodel.py](CANAnalyzer/viewmodels/hmi_video_extractor_viewmodel.py)
orchestrates a service chain over OpenCV/Tesseract: `HmiVideoLoader` →
`HmiRoiTracker` (region tracking) → `HmiFrameStabilizer` → `HmiNumericReader` (OCR) with
processing on `HmiVideoProcessingWorker`. The user defines ROIs over the video; results
export to CSV/JSON for correlation with CAN signals.

## Conventions

- All modules use `from __future__ import annotations`; target a modern Python with full
  type hints. Match the existing typed style.
- Threading: long-running work (loading, restore, mux detection, video processing,
  streaming) always runs on a `QThread`/worker owned by a ViewModel, communicating via
  signals — never block the Qt event loop.
- The PyInstaller build ([Canlytics.spec](CANAnalyzer/Canlytics.spec) +
  [_build_common.py](CANAnalyzer/_build_common.py), shared by both the onefile and onedir
  outputs) explicitly excludes most optional PySide6 submodules and pins `hiddenimports`.
  If you add a new third-party dependency or a dynamically-imported `can`/Qt interface,
  update `_build_common.py`'s `collect_app_hiddenimports()`/excludes lists or the frozen
  build will break.

---

## Derived Signals feature — **COMPLETE** (merged into `dev`)

Signals computed from raw CAN data or already-decoded signals via a user-defined
Python/NumPy formula evaluated in a restricted sandbox.  **Advanced mode only** —
Basic Mode (visual pipeline builder) was planned but is cancelled; it will not be built.

### Implemented

| File | Role |
|------|------|
| `models/derived_signal.py` | `DerivedSignal` dataclass: `name`, `formula`, `inputs`, `simple_config` (pipeline builder state, or `None` for pure-Advanced formulas) |
| `models/derived_view_signal.py` | Visual wrapper with same style props as `ViewSignal` |
| `services/signal_aligner.py` | `align(*series)` — ffill onto union timestamp axis |
| `services/formula_context.py` | Sandbox namespace: `np`, `math`, `signal()`, `bam_messages()`, `bam_extract()`, `raw_frames()`, `raw_extract()`, `decode_bytes()`, `align()` |
| `services/formula_evaluator.py` | `evaluate(formula, context) → (ts, y)`; raises `FormulaError` |
| `tests/test_signal_aligner.py` | 8 characterization tests |
| `tests/test_formula_evaluator.py` | 24 characterization tests (sandbox escapes, dtypes, helpers) |
| `viewmodels/plot_viewmodel.py` | `self.derived: dict[str, DerivedViewSignal]`; CRUD; `get_plot_data()` evaluates derived after decoding raw; `.conf` bumped to **version 3** with `"derived_signals"` key |
| `views/signal/derived_signal_dialog.py` | `DerivedSignalDialog` — formula editor, style/filter tabs, live preview |
| `views/plot/plot_window.py` | "Add derived signal" context-menu action; edit/remove dispatch for derived vs. raw |

**Formula sandbox** — `exec()` with `__builtins__ = {}`.  Formula must assign
`result = (ts_array, y_array)` or `result = y_array`.  No `import`, no `open`, no
`print` (explicitly excluded from the allowlist in `services/formula_context.py`).

**BAM RSSI example** (works today in Advanced mode):
```python
messages = bam_messages(pgn=0xFF17)
ts_out, val_out = [], []
for msg in messages:
    for i in range(0, len(msg.data), 20):
        chunk = msg.data[i : i + 20]
        if len(chunk) == 20:
            ts_out.append(msg.timestamp)
            val_out.append(decode_bytes(chunk, 18, 2, 'int16le'))
result = np.array(ts_out), np.array(val_out)
```

---

## Real-time plot — Incremental update (`feature/realtime-incremental`)

Branch off `dev` when ready. Derived Signals must be merged first (done on `dev`).

### Problem

Every time `dataframe_changed` fires (new frames arrive over SSH / Kvaser / replay),
the plot calls `get_plot_data()` which recomputes **all** series from the beginning of
the accumulated DataFrame:

1. **Performance degrades** — O(total frames) work on every update.
2. **Zoom/pan resets** — the viewport is recalculated from scratch on every batch.

**Design rule:** plot updates in streaming mode must always be **incremental** — decode
only the new frames and append to existing series; never rebuild from scratch while
data is flowing. The final result must be **identical** to a full recompute.

### Signal categories

| Category | Examples | Incremental strategy |
|---|---|---|
| Raw signals | decoded CAN signals, raw byte extracts | Append new-batch slice only |
| Simple derived | `signal(x) * k`, `raw_bits(...) + offset` | Same — no cross-series dependency |
| Aligned derived | any formula that calls `align()` | `align_incremental()` — see below |

All three categories are fully incremental. No signal needs periodic full recompute.

### `align_incremental()` design

`align()` today builds a **union timestamp axis** across all input series and
forward-fills each signal onto it. This can be made incremental because ffill only
depends on the last known value at the watermark:

```python
# services/signal_aligner.py — new function
def align_incremental(
    new_batches: list[tuple[np.ndarray, np.ndarray]],
    last_known: list[float],          # last y value of each signal at watermark
) -> tuple[np.ndarray, list[np.ndarray], list[float]]:
    """
    Align only the new-batch slices of N signals.

    Returns:
        ts_union  — union timestamp axis of the new batch
        ys        — forward-filled new values for each signal
        new_last  — updated last_known values (pass back next call)
    """
    # 1. build mini union axis from new_batches timestamps only
    # 2. ffill each signal starting from its last_known value
    # 3. result is identical to slicing a full align() at [watermark:]
```

`PlotViewModel` stores `_align_last_known: dict[str, list[float]]` — one entry per
derived signal that uses `align()`, updated after each incremental step.

### Files to create / modify

| File | Change |
|------|--------|
| `services/signal_aligner.py` | Add `align_incremental(new_batches, last_known)` |
| `tests/test_signal_aligner.py` | Add characterization tests: incremental == full recompute slice |
| `viewmodels/plot_viewmodel.py` | Add `_watermark: int`, split `get_plot_data()` into `get_full_data()` + `get_incremental_data(since)`, store `_align_last_known` |
| `views/plot/plot_window.py` | Subscribe to incremental update path; preserve viewport; "Live" toggle auto-scrolls to right edge |

### `PlotViewModel` watermark

```python
# plot_viewmodel.py additions
_watermark: int = 0                          # row index into the DataFrame
_align_last_known: dict[str, list[float]]    # per derived signal using align()

def get_full_data(self, ...) -> list[dict]:
    self._watermark = len(self._df)
    # ... existing get_plot_data() logic ...

def get_incremental_data(self, ...) -> list[dict]:
    new_slice = self._df[self._watermark:]
    self._watermark = len(self._df)
    # decode new_slice for raw signals
    # for aligned derived: call align_incremental() with _align_last_known
    # return list[dict] with only the new (ts, y) points to append
```

Reset `_watermark = 0` and `_align_last_known = {}` when the source DataFrame is
replaced (log reload), not when new frames are appended.

### `PlotWindow` viewport preservation

```python
# plot_window.py — on incremental update
def _on_incremental_data(self, new_points: list[dict]) -> None:
    for entry in new_points:
        self.renderer.append_series(entry["label"], entry["x"], entry["y"])
    if self._live_mode:
        self.renderer.scroll_to_right_edge()
    # else: do NOT touch the viewport — user is panning through history
```

"Live" mode activates automatically when the user drags the viewport to the right
edge (within one screen width of the latest timestamp). Panning away deactivates it.
A "Live" toggle button in the View ribbon tab shows the current state.

### Invariant to test

For any signal and any split point `k` in the DataFrame:
```
full_result[k:] == incremental_result_from_watermark_k
```
This must hold for raw signals, simple derived, and aligned derived. The
characterization tests in `test_signal_aligner.py` pin this property.

---

## UI/UX Audit Roadmap - APPROVED SCOPE COMPLETE

Status captured on 2026-06-15. All 12 items completed on branch `feature/ui-redesign`
(merged into `dev`). MUX Detection and HMI Video remain excluded until the user
explicitly re-enables them.

### Completed

| # | Item | Track | Branch commit |
|---|------|-------|---------------|
| 1 | File menu: separators + Ctrl+O/S + Clear at the end | a11y | 1763fa3 |
| 2 | Regroup CAN ID panel into "CAN IDs" / "Interpretation" | declutter | 3fcccbf |
| 3 | Cursor: replace 4-level submenu with "Cursor settings" dialog | declutter | 5621e84 |
| 4 | "Advanced" collapsible in candidate / derived windows; MUX skipped | declutter | 1e323f7 |
| 5 | Status bar message for DBC restore | visual | bd37c01 |
| 6 | DBC manager: Close button + confirm delete / Connection consistency | consist. | 8fc8cd9 |
| 7 | Empty states in candidate window; plot empty state removed per user request | visual | 5f9e555 |
| 8 | Analyze Data: legend + stats grid | visual | 89857ea |
| 9 | Remove dead layout in HMI | consist. | 3991e78 |
| 10 | Relocate candidate tag imports to Tools menu | declutter | b8d295e |
| 11 | Ribbon bar for main window (Home / Analysis / Settings tabs) | feat | 934a356 |
| 12 | Ribbon bar for plot window (Signals / View / Cursor tabs) | feat | e280735 |

### Design decisions recorded

- **Plot empty state**: added in commit 5f9e555, then removed per user direction
  (2026-06-15). Do **not** re-add a "No signals yet" overlay on the plot widget.
- **Time filter moved**: out of the CAN ID side panel → `Settings > Time filter…`
  to keep the side panel focused on selection and interpretation.
- **MUX Detection + HMI Video**: excluded from this audit wave. Do not touch
  their UI unless the user explicitly re-enables them. MUX Detection has since
  been fully disabled (2026-07-15) — see "Streaming perf audit" below; HMI
  Video is untouched and still reachable normally.
- **Hidden menu bar**: `menuBar().setVisible(False)` keeps QAction shortcuts alive
  (`Qt::WindowShortcut` context fires even when the bar is invisible). Do not remove
  the `build_main_menu()` call — it is the shortcut registration, not a visible menu.
- **Ribbon icon refresh**: `PlotRibbonBar` auto-refreshes icons via `paletteChanged`;
  `RibbonBar` (main window) requires an explicit `reload_icons()` call after
  `apply_theme()` in `_set_theme()`.

### Pending (next wave)

- Theme token migration: several view files still use hardcoded color strings instead
  of theme tokens from `config/theme.py` (all interactive widget disabled states are
  now covered globally in QSS; remaining are one-off `setStyleSheet` calls in views).
- Accessibility pass: tooltips on jargon controls, keyboard mnemonics, inline
  validation feedback in Connection dialog.

**Done since last audit:**
- ✓ Signal visibility + view config (y_axis_mode, grid, legend, fit_x, fit_y) persisted in `.conf` v4 — `feature/time-config-ux`.
- ✓ Plot export: Image (PNG/JPG/BMP) and CSV via `services/plot_exporter.py`; Export group in Signals ribbon tab — `feature/plot-export-fixes`.
- ✓ Disabled control appearance: global QSS `:disabled` rules for QPushButton, QToolButton, QLineEdit, QSpinBox, QComboBox, QTimeEdit, QCheckBox, QRadioButton, QLabel and ribbon buttons — `dev` (direct commit).
- ✓ Ribbon collapse/auto-hide with F10 and Excel-style hover popup — `feature/ribbon-collapse`.
- ✓ Connection dialog: `_OffsetWidget` sign toggle replaced QPushButton with compact flat QToolButton (22×22).
- ✓ Sandbox fix: `print` removed from formula allowlist (`services/formula_context.py`).
- ✓ "Time Config" label normalized everywhere (was "TimeConfig", "Time format", "Time settings") — `dev` (445c9d2).
- ✓ Real-time analysis moved from connection dialog to Analysis ribbon tab; button only enabled when connection is running (`running_changed` signal) — `dev` (6746401).
- ✓ Cursor stats: min/max and count display options added; only Δ delta on by default; cursor lines/labels recolor on theme switch — `dev` (dd6a0f1).
- ✓ FFT frequency analysis window (`services/fft_analysis.py`, `views/plot/fft_window.py`): Hann-windowed rfft, linear/dB toggle, uses dual-cursor range if active — `dev` (41d78ca).
- ✓ Plot ribbon reorganized to **Signals / View / Cursor / Tools**: View gains Appearance group (Grid, Legend, Split Y ribbon toggles + Graph settings button); Tools has Playback, FFT, Time Config; `GraphSettingsDialog` simplified (removed y-axis, legend visibility, visual config — all now ribbon toggles) — `dev` (41d78ca).

---

## Analyze Data window redesign — **COMPLETE** (`feature/analyze-data-redesign`,
`feature/range-diff` for the second wave)

**First wave** (branch off `dev` commit `b2dbabf`):

- Stats panel hidden by default — users open it via an inline "▸ Statistics" toggle
  button (replaces the buried Settings > Show details menu item, which is kept in
  sync via `blockSignals`).
- Stats displayed as a **chip grid** (4 per row) — each chip is a `QFrame#stat_chip`
  with a muted key label + bold value label, using theme tokens.
- Prominent `QLabel#selected_id` at the top of the right panel shows the currently
  selected CAN ID (13pt bold), updated in `_on_can_id_changed` and `_select_can_id`.
- Left panel gains a `QLabel#panel_header` ("CAN IDs") for visual hierarchy.
- New QSS tokens in `config/theme.py`: `panel_header`, `selected_id`, `stat_chip`,
  `stat_chip_key`, `stat_chip_val`, `stats_toggle`.

**Second wave (2026-07-16):** CAN ID list moved from left to the right column so the
plot is dominant and centered; Mux + per-byte selection moved out of the layout into a
`QToolBar` (`_setup_toolbar()` in `views/analyze_data_window.py`):

- Toolbar actions: Time Config, Time Filter (pre-existing), plus a Mux action (icon
  `grid`) + `mux_case` `QComboBox`, plus a `_btn_bytes` `QToolButton` with a popup
  `QMenu` for per-byte visibility (All / None / B0..B7).
- Byte toggles are **`QWidgetAction` wrapping real `QCheckBox` widgets**, not checkable
  `QAction`s — a checkable `QAction` closes its `QMenu` on every click (verified with a
  real `QTest.mouseClick`, not just `.trigger()`, which doesn't reproduce the native
  close-on-click behavior). `self._byte_checks: dict[int, QCheckBox]`.

### Verification

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v
```

---

## Candidate Interpretations improvements — **COMPLETE** (`feature/range-diff`, 2026-07-16)

Two areas of work: better "is this a signal" scoring, and a full window redesign.

### Scoring (`services/candidate_interpretations.py`)

`_candidate_score(values, changes, distinct_values)` combines a shape score (change
ratio, distinct-value ratio, span) with a **lag-1 autocorrelation** smoothness factor
(`_autocorrelation`) applied as a **multiplicative gate**, not an additive term —
additive smoothness let pure random noise's maxed-out change/distinct/span ratios
outscore a real, rare-but-genuine signal (found via numeric simulation: noise scored
0.75 vs. a real signal's 0.36 under the old additive formula). `_size_scale(n)`
discounts confidence for small samples (`sqrt(n/30)` capped at 1.0).

**Scipy alternatives investigated and rejected** (empirically, not just in theory —
each was implemented and numerically compared against the autocorrelation approach
before being discarded): KS-test against a uniform distribution, spectral
entropy/periodogram (`scipy.signal.periodogram` + `scipy.stats.entropy`), and
Savitzky-Golay-based SNR (`scipy.signal.savgol_filter`). All either underperformed or
reintroduced false positives on noisy real-world signals. Don't re-attempt these
without new evidence — the rejection was based on real numbers, not the tool being
"boring".

`_passes_sensitivity(...)` gained `include_constant: bool = False` — makes the
"always discard constant bytes" rule optional (some bytes worth surfacing are
constant, e.g. protocol version fields).

### Two-pass search (`_build_candidate_items`)

`_iter_signal_specs(...)` is a pure generator enumerating every `(length, byte_order,
start_bit, type)` combination the search would try — no dataframe access. The
planning pass counts total work (`sum(1 for _ in _iter_signal_specs(...))`, not a
materialized list) to drive the progress dialog; the execution pass regenerates the
same generator lazily per group. This avoids holding the whole search space in memory
and keeps cancel responsive during a large "Try All" search.

`RecalculateProgress` dialog now shows a live **percentage + ETA** (computed from
elapsed time and done/total) instead of a bare spinner.
`viewmodels/candidate_interpretations_viewmodel.py::_ProgressThrottle` caps progress
signal emissions to ~200 for the whole run (plus the final one) so the UI doesn't
choke on a fast loop emitting thousands of `progress(int, int)` signals.

### Window redesign (`views/candidate_interpretations_window.py`)

`QTabWidget` (Results / Matrix) inside the window, with a **persistent sidebar**
(filters + candidate list) outside the tabs so it never disappears when switching
tabs: `outer_splitter` = `self.tabs` + `results` (the sidebar), and `self.tabs`'s
Results tab is its own inner splitter of just CAN ID list + details/plot.

- Sidebar filter grid (2 columns): Value Type, Tag, Category, Min. score, plus a
  full-width "Hide multi-byte fragments" checkbox. No Sort control (removed — CI1's
  "sort by score" combo was judged not worth the row of UI it took).
- **Signal category taxonomy** (`services/candidate_interpretations.py::
  classify_signal_type`): pure, display-time classification into `SignalCategory`
  (`COUNTER`/`BINARY`/`ENUM`/`ANALOG`/`CONSTANT`/`OTHER`) from stats already computed
  per candidate (distinct values, change ratio, autocorrelation, and `observe_byte`'s
  monotonic-wrap check reused from `range_diff.py`). Feeds both the sidebar's
  Category filter and the Matrix tab's grouping — one classifier, two consumers.
- **Matrix tab**: entries group into collapsible per-category sections (`▸`/`▾`,
  same pattern as "Advanced parameters"/"Details"), sourced from the sidebar's
  currently-visible candidates so every active filter already applies before Matrix
  ever sees them. Collapse state persists in `self._matrix_section_collapsed` across
  rebuilds (filter changes, tab re-entry).
- **Multi-byte fragment detection**: `is_multi_byte_fragment` flags *both* halves of
  a carry-linked byte pair (not just the low byte) — a candidate is a "fragment" if
  it's either side of a flagged pair, computed once per group via
  `_multi_byte_hints_for_group`/`_fragment_byte_indices`.
- CAN ID list uses `itemActivated` (Enter / double-click) to toggle checkstate, not
  `itemClicked` — clicking the checkbox glyph itself already toggles via Qt's native
  handling, so a second manual toggle on `itemClicked` would double-toggle (net no
  change) for glyph clicks. `SingleSelection` mode fixes keyboard navigation without
  that conflict.
- **Menu bar is hidden** (`self.menuBar().setVisible(False)`), same pattern as the
  main window — `_setup_menu_bar()` is still called first so `QAction` shortcuts stay
  registered (`Qt::WindowShortcut` context fires even with the bar invisible); every
  action reachable from the old menu (Time Config, Filters, Constraint Search, Export
  Tags, Import Tags) has an icon equivalent in the `QToolBar` built by
  `_setup_toolbar()`. The toolbar holds only actions -- output filters live in the
  sidebar, never mixed into the same row.

Reviewed via `ui-ux-auditor` + `qt-mvvm-reviewer` + `code-reviewer` in parallel, then
every finding (bugs + UX gaps) fixed in the same pass — including a "Select None"
button that asymmetrically triggered a full recalculate (unlike "Select All").

---

## Time config UX (`feature/time-config-ux` → merged into `dev` 2026-06-15)

Cross-cutting improvements to timestamp display, cursor filtering, plot persistence,
and the connection dialog. All 5 commits merged with `--no-ff` (merge `d5e5ace`).

| Commit | Scope | What changed |
|--------|-------|--------------|
| `0d4eeec` | `fix(cursor)` | Cursor value box only shows **visible** signals — `_visible_only()` filter reads `data["style"]["visible"]` |
| `858b50f` | `refactor(plot)` | `utils/timezone_format.py` — `format_timestamp(value, tz_mode)` centralises all TS display; `TimeAxisItem` delegates to it; `enableAutoSIPrefix(False)` suppresses `(x1e+09)` label |
| `b0f472f` | `feat(plot)` | **Fit X / Fit Y** checkable ribbon toggles (`arrow-left-right.svg`, `arrow-up-down.svg`); signal visibility and full view config persisted in **conf v4** (`"view"` key + `"visible"` per signal) |
| `8710561` | `feat(analyze-data)` | Toolbar with "Time format" (`clock`) and "Time filter" (`sliders-horizontal`) actions |
| `2656716` | `feat(connection)` | PC vs Device timestamp source radio buttons; `_OffsetWidget` (±HH:MM:SS via `QTimeEdit` + sign toggle); live clock label; "Time format…" button opening `TimeConfigDialog`; `_SshTimePollThread` parses `candump -ta {iface}` for device timestamps |

### Key implementation notes

- **`_apply_axis_mode_ui()` after timezone change** — in `PlotWindow._set_timezone`, do NOT call
  `self.plot.setAxisItems(...)` (it destroys auxiliary viewboxes in separate-signals mode).
  Call `self.renderer._apply_axis_mode_ui()` instead.
- **`_OffsetWidget`** — compact `±HH:MM:SS` widget; `.value()` returns `float` seconds; `.setValue(seconds)` restores sign + time.
- **SSH device timestamp polling** — use `candump -ta {iface}` parsed by `parse_candump_line()`,
  NOT `date +%s` (user rule: reuse the existing log parser).
- **conf v4 schema** — adds `"view": {y_axis_mode, grid, legend, fit_x, fit_y}` and
  `"visible": bool` per signal entry. `_load_config_file` applies view config via
  `_apply_view_config` on the window side.

---

## Range Diff — Fase 1 **COMPLETE** (merged into `dev`), Fase 2 pendiente

Feature para comparar **qué cambió en el payload CAN entre dos ventanas de tiempo**,
a nivel de byte y **sin depender de DBC** (el DBC, si está cargado, solo *nombra* lo
que cambió; nunca es requisito).

- **Fase 1 — Range Diff (offline):** ventana nueva. El usuario fija dos rangos A y B
  sobre el log cargado/acumulado y obtiene un reporte clasificado de cambios por byte.
  **Implementado en `feature/range-diff`** (branch aún no mergeada a `dev`).
- **Fase 2 — Baseline vs vivo (real-time):** dentro del Real-Time window. El usuario
  "captura un baseline" y ve, en vivo, qué se desvía de él con la misma taxonomía.
  **Aún no implementado** — plan más abajo.

Extra sobre lo planeado originalmente: se agregó un test de significancia estadística
**Mann-Whitney** (`scipy.stats.mannwhitneyu`) como filtro opcional (`DiffOptions.
require_significance`, off por defecto) para descartar diffs que son solo ruido de una
señal poco estable, no un cambio real. `ByteObservation` gana un campo `raw` (los
valores crudos) y `ByteDiff` un campo `p_value: float | None`; `scipy` es import perezoso
dentro de `_mann_whitney_p`, y el módulo funciona sin scipy instalado (el checkbox de
significancia queda deshabilitado/no aplicable). El mismo criterio aplicaría a Fase 2
— ver nota en esa sección.

Archivos implementados (Fase 1):

| Archivo | Rol |
|---------|-----|
| `services/range_diff.py` | núcleo puro: taxonomía, `classify_byte`, `build_range_diff_report`, `_mann_whitney_p` |
| `tests/test_range_diff.py` | 36 tests: taxonomía, filtros, scoring, significancia (skip si no hay scipy) |
| `viewmodels/range_diff_viewmodel.py` | `set_dataframe` (incremental, barato) vs `reset_dataframe` (full reload, resetea rangos/densidad) |
| `viewmodels/range_diff_worker.py` | `QThread` worker sobre `build_range_diff_report` |
| `views/widgets/range_timeline.py` | histograma de densidad + 2 bandas arrastrables (rango A/B) |
| `views/range_diff_window.py` | ventana: selección de rangos, filtros en memoria, árbol de resultados |
| `views/range_diff_window_manager.py` | `BaseWindowManager` de single-instance |

Cableado en `viewmodels/main_window_viewmodel.py` (`dataframe_replaced` → `reset_dataframe`,
`dataframe_changed` → `set_dataframe`), ribbon Analysis (icono `git-compare`) y menú Tools
en `views/main_window.py` / `views/widgets/ribbon_bar.py` / `views/menu/main_menu_factory.py`.

### Principio arquitectónico rector

> **La taxonomía de cambio se escribe y se testea UNA sola vez, como núcleo puro y
> Qt-free.** Ambas fases (offline y vivo) son solo dos formas distintas de alimentar
> ese núcleo con dos observaciones `A` y `B`.

Consecuencia directa de diseño — **separar "clasificar" de "filtrar":**

- `classify_byte(a, b)` es **objetivo**: dada la evidencia, dice qué tipo de cambio es.
  No conoce las opciones de la UI. Siempre devuelve una clasificación (incluido
  `UNCHANGED`).
- El **filtrado** (misma oscilación, contadores, solo territorio nuevo, mínimo de
  frames, presencia) es **política**: una función pura aparte sobre el reporte ya
  clasificado. Se aplica en memoria al togglear checkboxes, **sin re-escanear** el log
  (mismo patrón que `signal_coverage`: se computa todo una vez, los filtros son
  display-time).

Esto habilita: (a) la UI reactiva sin recomputar, y (b) que la Fase 2 reclasifique en
vivo y filtre barato en cada refresco.

### Mapa de capas

```
services/range_diff.py         NÚCLEO PURO (Fases 1 y 2)
  ├─ ByteObservation            reducción de 1 byte sobre 1 ventana
  ├─ observe_byte(seq)          Sequence[int] -> ByteObservation
  ├─ classify_byte(a, b)        (ByteObservation, ByteObservation) -> ByteDiff   [objetivo]
  ├─ ByteDiff / IdDiff / RangeDiffReport
  ├─ RangeDiffReport.visible(opts)   re-filtro puro (política)          [barato, sin re-scan]
  ├─ build_range_diff_report(df, a, b, ...)   agregador offline
  ├─ slice_window(df, range)    slice por TS
  └─ frame_density(df, buckets) histograma para la mini-timeline

services/realtime_analysis.py  (Fase 2) LiveByteAccumulator
  └─ acumulador incremental que produce el MISMO ByteObservation que observe_byte
     Invariante testeable:  acc.fed(seq).snapshot() == observe_byte(seq)

tests/test_range_diff.py        taxonomía + agregador + filtros + scoring
tests/test_range_diff_live.py   (Fase 2) invariante acumulador == observe_byte

# ---- Fase 1 (Qt) ----
viewmodels/range_diff_viewmodel.py + range_diff_worker.py
views/range_diff_window.py + range_diff_window_manager.py
views/widgets/range_timeline.py

# ---- Fase 2 (Qt) ----
viewmodels/real_time_analysis_viewmodel.py   (+ capture_baseline / clasificación en vivo)
views/realtime_analysis_window.py            (+ toggle baseline + display de clasificación)
```

`LiveByteAccumulator` vive en `realtime_analysis.py` (es estado incremental propio del
RT) pero **produce el `ByteObservation` de `range_diff.py` y alimenta el mismo
`classify_byte`**. Así la maquinaria incremental queda junto al RT y la taxonomía sigue
teniendo una sola fuente de verdad.

### Núcleo puro — `services/range_diff.py`

#### Tipos

```python
from enum import Enum

class ChangeType(str, Enum):
    UNCHANGED       = "unchanged"        # mismo valor constante en A y B  -> se descarta siempre
    SAME_OSCILLATION= "same_oscillation" # mismo conjunto de valores (>1)  -> filtro "misma oscilación"
    CONST_SHIFT     = "const_shift"      # A=x fijo, B=y fijo, x!=y         -> el más "limpio"
    NEW_TERRITORY   = "new_territory"    # B alcanza valores que A no tuvo
    RANGE_SHIFT     = "range_shift"      # min/max/media se desplaza, sin territorio nuevo

@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float

@dataclass(frozen=True)
class ByteObservation:
    """Reducción de un byte sobre una ventana. Todo derivable de la secuencia."""
    n_frames: int
    values: tuple[int, ...]     # distintos, ordenados
    vmin: int
    vmax: int
    mean: float
    first: int                  # primer valor en orden TS
    last: int                   # último valor en orden TS
    change_ratio: float         # fracción de frames consecutivos donde el byte cambió
    looks_counter: bool         # incrementa monótono (mód 256) o togglea 2 valores casi siempre

@dataclass(frozen=True)
class ByteDiff:
    byte_index: int
    change_type: ChangeType
    a: ByteObservation
    b: ByteObservation
    new_values: tuple[int, ...]     # SB - SA (territorio ganado)
    lost_values: tuple[int, ...]    # SA - SB (valores perdidos)
    delta_mean: float               # b.mean - a.mean
    is_counter: bool                # a.looks_counter and b.looks_counter (overlay, ortogonal al tipo)
    score: float

@dataclass(frozen=True)
class IdDiff:
    can_id: str
    presence: str                   # "both" | "only_a" | "only_b"
    frames_a: int
    frames_b: int
    len_a: tuple[int, ...]
    len_b: tuple[int, ...]
    len_changed: bool
    byte_diffs: tuple[ByteDiff, ...]  # TODOS los bytes con su clasificación (incl. UNCHANGED)
    score: float
    dbc_hint: str | None            # nombre(s) de señal DBC que cubren un byte cambiado, si hay DBC

@dataclass(frozen=True)
class DiffOptions:                  # política de visibilidad (todo display-time)
    ignore_same_oscillation: bool = True
    ignore_counters: bool = True
    only_new_territory: bool = False
    include_presence: bool = True
    min_frames: int = 3

@dataclass(frozen=True)
class RangeDiffReport:
    range_a: TimeRange
    range_b: TimeRange
    ids: tuple[IdDiff, ...]         # clasificación COMPLETA, sin filtrar
    def visible(self, opts: DiffOptions) -> list[IdDiff]: ...   # re-filtro puro
```

#### Funciones

```python
def observe_byte(values: Sequence[int]) -> ByteObservation: ...
def classify_byte(a: ByteObservation, b: ByteObservation) -> ByteDiff: ...   # objetivo, sin opts
def slice_window(df: pl.DataFrame, r: TimeRange) -> pl.DataFrame: ...          # TS in [start, end]
def frame_density(df: pl.DataFrame, *, buckets: int) -> tuple[list[float], list[int]]: ...

def build_range_diff_report(
    df: pl.DataFrame, range_a: TimeRange, range_b: TimeRange, *,
    dbc_manager=None,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> RangeDiffReport: ...
```

#### Taxonomía (spec de `classify_byte`)

Con `SA = set(a.values)`, `SB = set(b.values)`:

```
si SA == SB:
    len==1  -> UNCHANGED
    else    -> SAME_OSCILLATION
si SA != SB:
    len(SA)==1 y len(SB)==1 -> CONST_SHIFT      (x -> y)
    elif (SB - SA)          -> NEW_TERRITORY    (B ganó valores nuevos)
    else                    -> RANGE_SHIFT      (B perdió/estrechó valores)
```

`is_counter = a.looks_counter and b.looks_counter` — **overlay ortogonal**, no un tipo
aparte. Resuelve el solape que notaste: un contador de ciclo completo cae en
`SAME_OSCILLATION` (mismo set); uno de **ciclo parcial** (rangos cortos → `SA != SB`)
cae en `NEW_TERRITORY`/`RANGE_SHIFT` pero con `is_counter=True`, así el filtro de
contadores lo atrapa igual.

#### Filtro (spec de `RangeDiffReport.visible`)

Puro, barato, sin re-scan. Por cada `IdDiff`:

- **Presencia** `only_a` / `only_b`: se conserva sólo si `opts.include_presence`.
- **`both`:**
  - Si `frames_a < min_frames` **o** `frames_b < min_frames`: se descartan los
    byte-diffs (comparación de valores no confiable); el ID sobrevive sólo si
    `len_changed`.
  - Si no, se filtran los byte-diffs:
    - `UNCHANGED` → fuera **siempre** (regla 1).
    - `SAME_OSCILLATION` → fuera si `ignore_same_oscillation`.
    - `is_counter` → fuera si `ignore_counters`.
    - si `only_new_territory` → sólo quedan `NEW_TERRITORY`.
  - El ID se conserva si le quedan byte-diffs visibles, o `len_changed`, o presencia.
- Orden final por `score` desc.

#### Scoring (guía, tunable vía `config`)

```
peso_base = {CONST_SHIFT:1.0, NEW_TERRITORY:0.8, RANGE_SHIFT:0.5, SAME_OSCILLATION:0.1, UNCHANGED:0.0}
mag       = min(1.0, abs(delta_mean)/255)          # magnitud del corrimiento
byte.score= peso_base[type] * (0.5 + 0.5*mag) * (0.2 if is_counter else 1.0)
id.score  = max(byte.score) + 0.05*n_bytes_visibles + (0.3 si presencia/len_changed)
```

#### Rendimiento

`slice_window` una vez por rango; `partition_by("ID")`; por ID se extraen los bytes de
cada ventana a NumPy y se llama `observe_byte` (8 × 2 por ID). Acotado y en worker
thread. `frame_density` se computa una vez por df (para la timeline), no por comparación.

### Fase 1 — Range Diff offline (Qt) — **COMPLETE**, detalle de implementación

#### `viewmodels/range_diff_viewmodel.py`

Adaptador delgado (mismo esqueleto que `SignalCoverageViewModel`):

- Estado: `_df`, `_range_a`, `_range_b`, `_options`, `_report`, worker/QThread.
- Signals: `analysis_started/finished/failed/canceled`, `progress_changed(int,int)`,
  `report_changed(object)`, `visible_changed(list)`, `density_changed(object)`,
  `ranges_changed(object)`.
- `set_dataframe(df)` — desde `data_vm.dataframe_changed`; recomputa `frame_density`,
  emite `density_changed`, resetea rangos a los extremos del log.
- `set_range_a/b`, `set_options(opts)` — al cambiar opciones **no** re-escanea: reemite
  `visible_changed(self._report.visible(opts))`.
- `run()` — lanza `RangeDiffWorker` en `QThread`; al terminar guarda `_report` y emite
  `report_changed` + `visible_changed`.
- `shutdown()` — cancela y espera el thread.

#### `viewmodels/range_diff_worker.py`

Copia del patrón `SignalCoverageWorker`: `run()` llama a `build_range_diff_report(...)`
con `should_cancel`/`on_progress`; señales `finished(object)`, `canceled()`,
`failed(str)`, `progress(int,int)`; `cancel()`.

#### `views/widgets/range_timeline.py`

`QWidget` custom. Pinta un histograma de densidad de frames sobre todo el span TS y
**dos bandas arrastrables** A y B (colores del tema). Sincronización bidireccional con
los campos numéricos.

```python
class RangeTimeline(QWidget):
    range_a_changed = QtSignal(float, float)
    range_b_changed = QtSignal(float, float)
    def set_density(self, edges: list[float], counts: list[int]) -> None: ...
    def set_range_a(self, start: float, end: float) -> None: ...   # sync programático
    def set_range_b(self, start: float, end: float) -> None: ...
    # paintEvent: histograma + 2 bandas ; mousePress/Move: mover/redimensionar banda activa
```

#### `views/range_diff_window.py`

```
┌─ Comparar rangos ─────────────────────────────────────────────┐
│ Rango A  inicio [ 12.340 ] fin [ 15.900 ]  [usar selección]    │
│ Rango B  inicio [ 88.100 ] fin [ 92.450 ]  [usar selección]    │
│  |▁▂▅█▇▃▁▁▂▄█▆▂▁▁▁▃▅▇█▆▂▁|   ← RangeTimeline (bandas A/B)       │
│ ─────────────────────────────────────────────────────────────│
│ ☑ Misma oscilación  ☑ Contadores  ☐ Solo territorio nuevo      │
│ ☑ Cambios de presencia   Mín. frames [ 3 ]      [ Comparar ]   │
│ ─────────────────────────────────────────────────────────────│
│ CAN ID ▸ Byte │ Presencia │  A  │  B  │ Tipo │ Δ media │ N A/B │
│ 18FEF100    …expandible a sus bytes cambiados…                 │
└────────────────────────────────────────────────────────────────┘
```

- Selección de rangos: campos numéricos (formato-tiempo-aware vía
  `utils/timezone_format`) + `RangeTimeline` sincronizada + botón "usar selección de
  tabla" (autollena desde la selección de la tabla principal).
- Filtros: al togglear, sólo re-filtra en memoria (`set_options` → `visible_changed`).
- Resultados: árbol `ID → bytes`, chip de color por `ChangeType`, empty state, barra de
  progreso + cancelar. Acciones por fila: **enviar byte al plot** (reusa `plot_manager`,
  como `signal_coverage_window`) y **export CSV**.

#### `views/range_diff_window_manager.py`

`BaseWindowManager`; `_create_window()` → `RangeDiffWindow(self._vm, plot_manager=..., parent=None)`.

#### Cableado (puntos exactos)

- **`viewmodels/main_window_viewmodel.py`**
  - import `RangeDiffViewModel`; en `__init__`: `self.range_diff_vm = RangeDiffViewModel(self)`
  - `self.data_vm.dataframe_changed.connect(self.range_diff_vm.set_dataframe)`
  - en `shutdown()`: `self.range_diff_vm.shutdown()`
- **`views/main_window.py`**
  - import `RangeDiffWindowManager`; crear
    `self.range_diff_manager = RangeDiffWindowManager(vm=self.vm.range_diff_vm, plot_manager=self.plot_manager)`
  - añadir `on_range_diff=self.range_diff_manager.open_window` en **ambas**
    construcciones de callbacks: `build_main_menu(...)` (~L140) y `RibbonCallbacks(...)` (~L154)
  - añadir `self.range_diff_manager` a las tuplas de `_has_open_secondary_windows` (~L404)
    y `_close_all_secondary_windows` (~L418)
- **`views/widgets/ribbon_bar.py`**
  - `on_range_diff: Callable[[], None]` en `RibbonCallbacks`
  - botón en el grupo **Analysis** junto a Coverage (icono Lucide `git-compare`);
    `btn.clicked.connect(cb.on_range_diff)`
- **`config/ui_text.py`** — strings: `ribbon_btn_range_diff`, `menu_range_diff`, título de
  ventana, headers de tabla, labels de filtros, empty states, tooltips.

#### Tests — `tests/test_range_diff.py`

Con DataFrames sintéticos (`can_data_parser.frame_dict`/`rows_to_df`): byte idéntico →
`UNCHANGED` (fuera) · mismo set → `SAME_OSCILLATION` (fuera/dentro según flag) ·
`CONST_SHIFT` x→y · `NEW_TERRITORY` · contador ciclo completo vs parcial (`is_counter`) ·
presencia `only_a`/`only_b`/`len_changed` · guard `min_frames` · orden por score ·
`visible()` no re-escanea (mismo `report`, distintos `opts`).

### Fase 2 — **Diff Analyzer**: rename de Range Diff + modo Live + tab de plot A/B — **pendiente, plan revisado 2026-07-18**

**Decisión de diseño (2026-07-18, tras varias iteraciones con el usuario):** Range Diff
se **renombra a "Diff Analyzer"** (nombre neutral, ya no es solo offline) y gana un modo
**Live**. Se eligió esta opción sobre (a) mantener el nombre, y (b) fusión total
absorbiendo Real-Time. Razonamiento registrado:

- Range Diff ya lee del mismo `data_vm` que crece en vivo (`dataframe_changed` emite el
  DataFrame completo acumulado en cada chunk, confirmado en `data_viewmodel.py`), así
  que **ya funciona offline y online** para el modo manual de dos rangos. Lo único que
  falta es un modo donde B se extienda solo hasta "ahora" sin re-apretar "Comparar".
- **Real-Time Analysis NO se absorbe ni se toca.** Es otro trabajo: ver los valores en
  vivo y subrayar lo que cambió frame-a-frame. Meter su tabla de valores + period/ΔT en
  el Diff Analyzer sería la anti-patrón mega-ventana (mezclar "ver valores" con
  "comparar diferencias"). Su "show only changing" sigue siendo el diff frame-a-frame de
  siempre. Opcional: un botón "Comparar desde ahora" en Real-Time que abre Diff Analyzer
  en modo Live.
- Diff Analyzer es **una ventana, un motor (`classify_byte`), dos formas de alimentar
  A/B** (manual vs. baseline-congelado/B-creciendo). Mismo timeline + árbol + filtros en
  ambos modos: es genuinamente una sola herramienta, el rename solo hace honesto el
  nombre.

Análogo honesto del diff en streaming (forward-only): **A = snapshot congelado al
capturar baseline (todo lo acumulado hasta ese instante), B = lo que seguirá llegando
desde entonces.** Reusa `classify_byte` al 100 %.

**Mann-Whitney en vivo:** mismo toggle opcional (off por defecto, `DiffOptions.
require_significance`) ya usado en Fase 1 — sin trabajo extra, porque el modo live
produce el mismo `RangeDiffReport`/`IdDiff`/`ByteDiff` que el modo batch y pasa por el
mismo `.visible(opts)`. El test se recalcula cada tick sobre una muestra que crece
(`baseline` fijo vs. `live_acc[i].snapshot()` actual); mantenerlo barato depende de que
`classify_byte`/`_mann_whitney_p` ya evitan correr scipy sobre bytes sin cambio de set
de valores (ver guard `len(set(a_raw)|set(b_raw)) < 2` en `_mann_whitney_p`).

#### Bug de timestamp a arreglar **primero** (defecto real del offline actual)

Los campos Range A/B se pintan con `f"{valor:g}"` sobre el epoch crudo (~1.78×10⁹). Con
esa magnitud, 6 cifras significativas dan **precisión de solo ~10 000 s**, lo que causa
las tres cosas que el usuario reportó, todas por la misma raíz:

1. No respeta el timezone configurado (muestra epoch, no hora formateada).
2. Ilegible (notación científica).
3. "Los rangos toman el rango completo" — al perder foco, `editingFinished` re-parsea el
   valor redondeado y la selección se pega a bloques enormes ≈ medio log (no es
   aleatorio: es la pérdida de precisión del `:g`).

Fix: mostrar los campos A/B vía `utils/timezone_format.format_timestamp(value, tz_mode)`
(respeta timezone; sin tz devuelve `.2f` con precisión completa), pasar `timezone_mode`
a la ventana (cablear por el manager + `main_window` + `timezone_changed`, como las
demás ventanas), y hacer los campos **read-only**: la selección fina va por el timeline
(ya arreglado el bug de que llegaba vacío, ver `emit_current_state`) + botón "usar
selección de tabla". Elimina el round-trip lossy de texto→float que rompía la selección.

#### `services/range_diff.py` — extensiones

- `LiveByteAccumulator` (nuevo, puro): mantiene incrementalmente los mismos campos que
  `ByteObservation` (min/max, suma+conteo para media, set de valores, transiciones para
  `change_ratio`/`looks_counter`, first/last, `raw` para Mann-Whitney) y los congela con
  `snapshot()`. Invariante (test): `acc.feed(seq); acc.snapshot() == observe_byte(seq)`
  — misma filosofía "incremental == recompute" del plot incremental del repo.
- Refactor: extraer de `_diff_for_id` un helper `_diff_bytes(obs_a: list[ByteObservation
  | None], obs_b: list[ByteObservation | None]) -> list[ByteDiff]` compartido entre el
  modo batch (hoy) y el modo live (nuevo) — evita reimplementar la clasificación por
  byte dos veces.
- `build_live_diff_report(baseline, live_acc, *, range_a, now, dbc_manager=None) ->
  RangeDiffReport`: reusa `_diff_bytes`/`_id_score`/`_dbc_hint_for_id` tal cual: mismo
  tipo de retorno que `build_range_diff_report`, así la vista no necesita saber de qué
  modo vino el reporte.

#### `viewmodels/range_diff_viewmodel.py` — extensiones

- Nuevo estado: `_live_active`, `_live_baseline: dict[str, list[ByteObservation |
  None]]`, `_live_acc: dict[str, list[LiveByteAccumulator]]`, `_live_watermark: int`,
  `_live_capture_ts: float | None`, un `QTimer` (~1000 ms) para reclasificar.
- `capture_live_baseline()`: congela A = todo lo acumulado hasta ahora (worker thread,
  un solo `observe_byte` por (id, byte) — pesado una sola vez, no por tick), fija
  `_live_watermark = len(df)` en ese instante.
- En `set_dataframe(df)` (ya cableada a `dataframe_changed`), si `_live_active`: tomar
  solo `df[_live_watermark:]` (filas nuevas), alimentar `_live_acc` por (id, byte),
  actualizar watermark. Evita el anti-patrón de re-escanear todo el df en cada tick.
- Timer tick: `build_live_diff_report(...)` → reusa **los mismos signals** que ya
  existen (`report_changed`, `visible_changed`) — la vista no cambia su forma de
  renderizar resultados entre modo batch y modo live.

#### Vista Diff Analyzer — `views/range_diff_window.py` (o renombrar a `diff_analyzer_window.py`)

Layout con **`QTabWidget`** (nuevo requisito del usuario 2026-07-18):

- **Tab "Resultados"** (lo actual): timeline + filtros + árbol ID→bytes.
- **Tab "Plot"** (nuevo): al seleccionar un byte-diff en el árbol, ese byte ya aparece
  **ploteado automáticamente** (sin tener que mandarlo al plot manualmente), y sobre el
  plot se **resaltan las dos ventanas A y B** como bandas sombreadas (mismos colores que
  la `RangeTimeline`: A=accent, B=error) con etiquetas "A"/"B" — así el usuario ve *dónde*
  cambió, no solo el reporte numérico. En modo Live, la banda B se extiende sola hacia el
  borde derecho a medida que llegan datos. Reusa `PlotWidget` + `TimeAxisItem` (respeta
  timezone) y las `LinearRegionItem`/overlays de pyqtgraph para las bandas; NO recomputa
  nada — usa el mismo slice de datos que ya tiene el reporte.
- Toggle "Live" junto a `btn_compare`: ON deshabilita el picker manual de A/B y el
  timeline arrastrable, muestra "capturado a las HH:MM:SS → creciendo"; OFF restaura el
  picker manual. El checkbox de significancia (`chk_significance`) aplica igual en ambos
  modos sin duplicar nada.

#### Tests — `tests/test_range_diff_live.py`

Invariante del acumulador (feed incremental == `observe_byte`) para: constante,
oscilación, contador (wrap 255→0), toggle, ventana vacía; y que `build_live_diff_report`
produce el mismo `IdDiff` que `build_range_diff_report` para rangos A/B equivalentes
(la regresión de que el refactor de `_diff_bytes` no cambió nada del modo batch ya la
cubren los 36 tests existentes de `test_range_diff.py`, deben seguir pasando igual).

### Secuencia de commits

**Fase 1** (rama `feature/range-diff` desde `dev`) — **hecho**, pendiente mergear a `dev`:

1. `feat(range-diff)`: núcleo `services/range_diff.py` + `tests/test_range_diff.py` ✓
2. `feat(range-diff)`: viewmodel + worker ✓
3. `feat(range-diff)`: widget `range_timeline.py` ✓
4. `feat(range-diff)`: ventana + window manager ✓
5. `feat(range-diff)`: cableado (composition root + ribbon + i18n) ✓
6. `chore(range-diff)`: dependencia scipy para Mann-Whitney ✓
7. `fix(range-diff)`: `emit_current_state` — timeline vacío al abrir la ventana ✓ (esta sesión)

**Fase 2** (rama `feature/diff-analyzer` desde `dev`, tras mergear Fase 1) — plan, no iniciada:

8. `fix(range-diff)`: timestamps A/B formateados por timezone + read-only (bug de precisión `:g`)
9. `feat(diff-analyzer)`: rename Range Diff → Diff Analyzer (i18n, título, ribbon, menú, clases)
10. `feat(diff-analyzer)`: `LiveByteAccumulator` + refactor `_diff_bytes` + `tests/test_range_diff_live.py`
11. `feat(diff-analyzer)`: modo live en el ViewModel (baseline worker + watermark + timer)
12. `feat(diff-analyzer)`: `QTabWidget` con tab Plot (byte auto-ploteado + bandas A/B resaltadas)
13. `feat(diff-analyzer)`: toggle "Live" en la vista
14. `feat(realtime-analysis)`: (opcional) botón "Comparar desde ahora" como atajo hacia Diff Analyzer

Revisión por commit: `ui-ux-designer` → `qt-mvvm-reviewer` → `qa-verifier`. Tests desde
`CANAnalyzer/`:
`.venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

### Decisiones abiertas / riesgos

- **Byte presente con LEN variable:** un byte cuenta si `i < LEN`; si el LEN varía entre
  tramas de un ID, eso ya se reporta como `len_changed`.
- **Rangos solapados entre sí:** permitido; sólo aviso si A y B son idénticos.
- **Fase 2, modelo de ventana B:** v1 usa "todo lo posterior al baseline" (sin límite,
  el `raw` de `LiveByteAccumulator` crece mientras el modo live esté activo). Alternativa
  futura si una sesión live corre por horas: ventana deslizante de los últimos N s en
  vez de "todo desde el baseline" — mismo `classify_byte`, decisión ya documentada como
  v2, no bloqueante para v1.
- **Tab Plot en modo Live:** la banda B crece; hay que refrescar el overlay de la región
  en el mismo timer tick que reclasifica, y (como el plot window incremental del repo)
  no reconstruir la curva desde cero — solo extender/mover la región B.
- **Rename:** cuidar que `session_state`/`.conf` no persistan un nombre viejo que rompa
  al renombrar clases (Range Diff no persiste config propia hoy; verificar antes).
- **DBC hint:** enriquecimiento opcional; nunca condiciona la detección.

---

## Dataframe perf optimization — ✅ items 1-2 done, item 3 partial (2026-07-20)

El gran cuello de botella (re-escaneo total → incremental) ya está resuelto por los
commits `perf(...)`. Cada frame guardaba sus bytes 3 veces: `DATA` (hex str), `B0..B7`
(hex str por byte), `D0..D7` (Int64 por byte).

1. ✅ **`with_data_int` lee D0..D7** en vez de re-parsear el hex de `DATA` — ya hecho
   (ver el docstring de `services/can_decoder.py::with_data_int`, mide ~5.32ms/call
   eliminados), de una sesión anterior a esta.
2. ✅ **PERF1 — B0..B7 fuera del esquema.** `FRAME_SCHEMA`/`DEFAULT_COLUMNS`/
   `REAL_TIME_ANALYSIS_COLUMNS` ya no tienen B0..B7; `D0..D7` se deriva directo del hex
   de `DATA`. Todo lector migrado a `D{i}` (analyze_data, candidate_interpretations,
   realtime_analysis, real_time_analysis_viewmodel); labels hex vía
   `utils.can_bytes.byte_value_to_hex()`. Verificado end-to-end contra un candump real
   de ~195MB/4M filas: mismo esquema/stats/mux-bucketing que antes de migrar,
   ~493MB de B0..B7 eliminados de esa sesión.
3. 🟡 **Parcial.** `candidate_interpretations.py::_split_by_mux_case` vectorizado
   (era `iter_rows()` + un re-filtro del df completo por cada label distinto —
   1.63s → 0.10s medido sobre un grupo real de ~484K filas con MUX configurado).
   Quedan sin vectorizar (evaluados, de menor prioridad): `bam_reassembly.py`/
   `bam_decode.py`/`formula_context.py` (secuenciales/con estado, difícil — dejar);
   `signal_coverage.py:206` y `real_time_analysis_viewmodel.py:119` son loops
   por-chunk ya acotados a solo las filas nuevas (no O(dataset completo) por tick),
   no urgentes.

---

## Interfaz explícita para backends de conexión (`CanSource`) — PLAN (pendiente, no urgente)

Evaluado 2026-07-18: la arquitectura actual es MVVM estricto, no hexagonal/clean. Migrar
todo `services/` a un esquema de puertos/adaptadores formal **no se recomienda** — es una
app de escritorio Qt de una sola UI, el dominio ya vive Qt-free en `services/`+`utils/` y
ya es testeable con characterization tests; una reescritura grande pagaría un costo alto
por un beneficio marginal.

Lo único que sí vale la pena, quirúrgico y acotado: una interfaz explícita **solo** donde
hoy hay implementaciones intercambiables reales sin contrato común — el caso claro es el
backend de streaming CAN (SSH / Kvaser / replay). Hoy `RemoteConnection`
([services/remote_connection.py:21](CANAnalyzer/services/remote_connection.py#L21)) es una
clase concreta atada a `paramiko`, y Kvaser/replay viven en módulos separados sin un
`Protocol` común — `connection_stream_viewmodel.py` termina conociendo detalles de cada
backend concreto en vez de programar contra una abstracción única.

Propuesta:

```python
# services/can_source.py — nuevo, pequeño
from typing import Protocol, Iterator

class CanSource(Protocol):
    def open(self, *, cancel_check=...) -> None: ...
    def is_alive(self) -> bool: ...
    def read_frames(self) -> Iterator[bytes]: ...
    def close(self) -> None: ...
```

`RemoteConnection` y los backends Kvaser/replay implementan el `Protocol` estructuralmente
(sin heredar). `connection_stream_viewmodel.py` deja de importar `RemoteConnection`
directamente y recibe un `CanSource` ya construido — beneficio concreto: tests pueden
pasar un `FakeCanSource` sin tocar sockets/paramiko/hardware Kvaser real.

**No aplicar el mismo patrón** a `dbc_manager.py`, `formula_evaluator.py`, `range_diff.py`,
etc. — ahí no hay múltiples implementaciones compitiendo, son lógica pura de un solo
camino, y ya son testeables tal cual. Señal para justificar una interfaz explícita en
otro lugar: "¿hay o va a haber más de una implementación real de esto?" — si no, envolverla
en un `Protocol` es ceremonia sin beneficio.

No iniciado. Backlog, no bloquea nada del pipeline de detección (ver [ROADMAP.md](ROADMAP.md)).

---

## Connection dialog resilience (SSH / Kvaser) — merged into `dev` 2026-07-15

`services/remote_connection.py`: `RemoteConnection.is_alive()` (checks
`transport.is_active()`, backed by the 30s SSH keepalive already configured in
`open()`) and `.ping()` (`transport.send_ignore()`, returns `False` on failure).

`viewmodels/connection_stream_viewmodel.py` (`_ConnectionStreamWorker._stream_lines`):
disconnects are detected two ways — immediately via `exit_status_ready()` / an empty
`recv()` (clean disconnect), and via an idle-triggered active probe
(`_IDLE_PING_SECONDS = 5.0`, calls `RemoteConnection.ping()`) for silent drops that
never surface an EOF. A clean/silent disconnect distinction matters because only the
former is instantly detectable over TCP/SSH — the latter needs a timeout by protocol
design, not an implementation gap.

Kvaser bitrate mismatches don't raise an exception, so wrong-bitrate detection is a
"does real traffic actually arrive" probe, not exception-based retry:
`_probe_bitrates()`/`_probe_has_traffic()` (`_BITRATE_PROBE_SECONDS = 3.0` per
candidate) try each candidate bitrate in order and keep the first one that yields
non-error frames. `services/kvaser_config.py::bitrate_probe_order()` reorders
candidates so 250k/500k are tried first. The "try all bitrates" checkbox in
`views/settings/connection_dialog.py` only enables for interfaces that actually expose
a bitrate list (`_kvaser_bitrate_candidates()`).

SSH auto-reconnect: a checkbox in the SSH page retries on any error (including the very
first connection attempt) with a backoff (`3 + 2*(attempt-1)`, capped at 15s), canceled
by a manual Start/Stop or by unchecking the box.

## Per-window memory contract (EPIC Performance y memoria, item 6, 2026-07-20)

What each heavy window actually holds resident, so a future change doesn't
accidentally turn a bounded view into a full-log copy. Not a rule to enforce in
code, just the map of what's true today:

| Window | Consumes | Notes |
|---|---|---|
| Main table (`data_vm`) | Full accumulated DataFrame | `TableModel` holds its own selected/filtered copy too — two live references, not one |
| Real-Time Analysis | Live entries dict, one `_LiveEntry` per (ID, mux-case) key | Bounded by distinct (ID, mux) combos seen, not by frame count |
| Analyze Data | Per-ID `AnalyzeDataAccumulator` (bounded LRU cache, `_LAZY_CACHE_CAPACITY=16`) + Matrix rollup (one decimated series per byte per ID, independent of the accumulator cache) | `precompute_all()`/`Free memory` are the explicit opt-in/opt-out for warming every ID at once |
| Diff Analyzer (offline) | `slice_window()` + `partition_by("ID")` over the two selected ranges only | Not the whole log — bounded by range width |
| Diff Analyzer (Live) | Frozen baseline snapshot + `LiveByteAccumulator._raw` per byte, growing while live is on | v1 has no sliding-window cap (documented earlier in this file as a known future v2) |
| Candidate Interpretations | Every accepted candidate's full `timestamps`/`values` arrays, held for the session | ~1,456 raw candidates on a full 118-ID default search on the real log (2026-07-20) — moderate scale, not virtualized (see below) |
| Signal Coverage | Scans the full log once, partitions by PGN/ID; per-signal stats arrays retained | No incremental cache/eviction — full re-scan on "Recalculate" |
| Plot / derived signals | `DecodedSignalCache`: lazy-concatenated chunk lists per signal (2026-07-20 — see item 8) | Chunks accumulate for the life of the plot window; no eviction |

Item 7 (virtualized/paginated result lists) was evaluated against this same real
log: Candidate Interpretations' `QListWidget` (~1,456 raw items, fewer after CI5's
"Group overlapping" collapse) is a moderate scale that didn't show evidence of
needing a `QAbstractItemModel` rewrite today — revisit only if a future search
config (e.g. full 1-64 bit combinatorial range) produces an order of magnitude more.

## Streaming perf audit — index + throttle pattern (merged into `dev` 2026-07-15)

Prompted by "the Signal Coverage window gets heavy over time" — confirmed no memory
leak there, but found two real, recurring inefficiencies in how several
viewmodels/windows handle the high-frequency `chunk_ready`/`dataframe_changed` signals
that fire while streaming (up to ~20 Hz):

- **Defect A — O(all tracked items) scan per chunk.** Fixed by building a
  `dict[can_id_int, list[index]]` reverse index once per full rescan, and having the
  per-chunk update look up only the affected indexes instead of scanning every tracked
  item. Applied to `services/signal_coverage.py` (`build_can_id_index` +
  `refresh_last_values`) and `viewmodels/real_time_analysis_viewmodel.py`
  (`_id_to_entries`, used by `details_data_for_selection`).
- **Defect B — unthrottled Qt widget/redraw mutation per chunk.** Fixed by buffering
  the latest value/state per identity key and flushing via a periodic `QTimer` instead
  of repainting on every signal emit. Applied to `views/signal_coverage_window.py`
  (`_UI_FLUSH_MS = 200`) and `views/plot/plot_window.py` (`_REDRAW_FLUSH_MS = 200`,
  `data_changed` → `_schedule_redraw()`/`_flush_redraw()`; explicit `_redraw()` calls
  from UI actions like style/grid changes stay instant, only the high-frequency
  `data_changed` path is coalesced).
- **Unconditional wiring regardless of window state.** Mux Detection and Candidate
  Interpretations were both connected to `data_vm.dataframe_changed` at the composition
  root (`MainWindowViewModel.__init__`), unconditionally, so they did work on every
  incoming chunk even with their window closed. Mux Detection is now **fully disabled**
  (no menu entry, no wiring — see the UI/UX Audit Roadmap section above); Candidate
  Interpretations now connects only while its window is open, matching the pattern
  `PlotWindowManager` already used for `ingest_raw_chunk`/`set_dataframe`
  (`CandidateInterpretationsWindowManager._create_window()` connects,
  `_on_window_destroyed()` disconnects).

**Memory leak found and fixed:** `views/plot/plot_window.py` never set
`Qt.WA_DeleteOnClose`, so `close()` only *hid* the window — the QMainWindow, its
pyqtgraph curves, `DecodedSignalCache`, and (with this pass) the new redraw `QTimer`
all stayed alive in memory for the rest of the process, for every plot window ever
opened and closed. Fixed by setting the attribute in `PlotWindow.__init__`, matching
every other secondary window in the app (`analyze_data_window.py`,
`candidate_interpretations_window.py`, `mux_detection_window.py`,
`signal_coverage_window.py`, `hmi_video_extractor_window.py` all already set it).

**`views/realtime_analysis_window.py` fixed too (2026-07-15):** same missing
`WA_DeleteOnClose` bug as Plot. Verified safe to add: `closeEvent` already calls
`self._interpret_vm.shutdown()` unconditionally (harmless no-op if no thread is
running), `_interpret_vm`/`_filter_vm`/`_table_model` are all created fresh in
`__init__` and parented to `self`, and every signal connection runs from the
long-lived `analysis_vm` to methods/widgets owned by the window instance — so once the
old window is actually destroyed, PySide auto-disconnects those and a fresh window
(with a fresh `InterpretationViewModel`) is built cleanly on next open. Confirmed via
grep sweep of every `*_window.py` + every create-once/show/raise/activate call site
(`.raise_()`) in `views/` that no other window has this gap.

**Reviewed and left as-is (not the same bug):**
- `views/plot/fft_window.py` explicitly sets `WA_DeleteOnClose = False` — one FFTWindow
  is deliberately reused per `PlotWindow` (refreshed via `set_data()`, not recreated),
  bounded to at most one extra hidden widget per plot window, not unbounded growth.
- `views/main_window.py`'s `self._connection_dialog` (the SSH/Kvaser Connection
  dialog) has no `WA_DeleteOnClose` either, but it's a single instance parented to
  `MainWindow` and reused for the whole app session (never recreated) — bounded, not a
  growing leak. Do **not** just flip this to `True`: nothing resets
  `self._connection_dialog` to `None` on close, so the next `_open_connection()` would
  call `.show()` on an already-deleted C++ object and crash. Fixing this properly would
  need a `destroyed`-connected reset first, same as `BaseWindowManager`.

---

## Auditoría de arquitectura (2026-07-18) — hallazgos pendientes de verificación

Revisión exhaustiva vía 5 agentes en paralelo sobre el código real (no solo lo
documentado aquí). **Nada de esto está en BUGS.md todavía** — son hallazgos de una
pasada de auditoría, a verificar (vía `/nuevo-bug` + `code-reviewer`) antes de
registrarse como bug formal o de actuar sobre ellos. Verificar contra el estado actual
del código antes de confiar en archivo:línea — pueden haber corrido más commits desde
esta fecha.

### Veredicto general

MVVM se respeta con rigor en `models/`/`utils/` (sin excepciones encontradas) y en las
áreas rediseñadas recientemente (Analyze Data, Range Diff, ribbon). La erosión se
concentra en: `services/` con dos clases `QObject` reales, varias vistas que saltan el
ViewModel para llamar servicios de cómputo directamente, un ViewModel de 547 líneas con
lógica de dominio de hardware, un composition root con documentación fragmentada, y
deuda histórica puntual (código muerto grande, un bug de threading más extendido de lo
documentado, un mapa de tests desactualizado en un tercio).

### A. Violaciones de capas MVVM

**Qt leakage en `services/` (rompe "Qt-free"):**
- `services/dbc_manager.py:7,23-24` — `DbcManager(QObject)` con `QtSignal`. Gestor
  central de DBCs usado en toda la app, no un worker aislado — la violación más grave
  por ser transversal.
- `services/hmi_video_processor.py:8,18-24` — `HmiVideoProcessingWorker(QObject)`. Más
  defendible (worker explícito de `QThread`), pero técnicamente debería vivir en
  `viewmodels/`.

**Vistas que saltan el ViewModel y llaman servicios directo:**
- `views/settings/connection_dialog.py:33-90` — el peor caso: `_SshTimePollThread
  (QThread)` completo definido dentro de la vista, abre `RemoteConnection` y parsea
  `candump` él mismo.
- `views/plot/plot_window.py:442,882,899` — llama `compute_fft`/`export_plot_image`/
  `export_plot_csv` directo, sin pasar por `PlotViewModel`.
- `views/signal/derived_signal_dialog.py:357,381,412,502` — llama `generate_formula(cfg)`
  repetidamente.
- `views/signal/tabs/decode_tab.py:368`, `pipeline_builder.py:837,982` — escanean PGNs
  (`available_bam_pgns`/`available_j1939_pgns`) directo sobre el DataFrame.

**ViewModels pesados (no son "adaptador delgado"):**
- `viewmodels/connection_stream_viewmodel.py` (547 líneas, el más grande) —
  `_probe_bitrates`/`_probe_has_traffic` y los bucles `_run_ssh`/`_run_kvaser`/
  `_run_replay` son lógica de dominio de hardware completa, candidata a extraerse a
  `services/`.
- `real_time_analysis_viewmodel.py::ingest_df` — bucle de orquestación con estado de
  70+ líneas que debería ser un acumulador de servicio.
- `plot_viewmodel.py::get_plot_data`/`_load_config_file` — alineación de series y
  parseo de `.conf` v3/v4 inline.

### B. Composition root y wiring

- **Posible fuga de thread:** `candidate_interpretations_vm` tiene `shutdown()`
  (cancel+quit+wait) pero **nunca se invoca** desde `MainWindowViewModel.shutdown()` —
  solo se cancela al cerrar su ventana, sin esperar el hilo al cerrar la app.
- El diagrama de pipeline en la cabecera de este archivo (sección "Composition root and
  signal wiring") está desactualizado: no refleja que `signal_coverage_vm`/
  `range_diff_vm` reciben `dataframe_changed`/`dataframe_replaced`, ni que
  `candidate_interpretations_vm` se conecta solo bajo demanda. La info correcta existe,
  pero fragmentada en otras secciones de este mismo archivo.
- `HmiVideoExtractorWindowManager` reimplementa el patrón en vez de heredar
  `BaseWindowManager` (deriva no documentada, sin impacto funcional aparente).
- `MuxDetectionWindowManager` parece código muerto, no referenciado en ningún lado.
- Sin señales huérfanas ni dobles-conexiones detectadas — el resto del wiring parece sano.

### C. Contrato de dataframe / esquema

- `FRAME_SCHEMA` vs `DEFAULT_COLUMNS`: orden difiere (`DATA`/`LEN` invertidos) pero
  parece inofensivo — todo selecciona por nombre, no por posición.
- **Hot path ya documentado arriba (§ Dataframe perf optimization), ahora con línea
  exacta confirmada:** `can_decoder.py:22-27` re-parsea el hex de `DATA` en vez de leer
  `D0..D7`. Call sites: `can_decoder.py:118` (cada decode de señal) y
  `signal_coverage.py:357` (cada scan completo).
- **Caso nuevo, no estaba en el plan de perf de arriba:**
  `candidate_interpretations.py::_split_by_mux_case` (250-269) — `iter_rows()` +
  reconstrucción por índice, O(n²)-ish, dentro del loop principal de construcción de
  candidatos sobre el grupo completo (ID, LEN). Candidato a sumarse al plan de
  vectorización si se confirma el costo real.
- Versionado de `.conf` (v1-v4): manejo correcto con gates incrementales, sin bug de
  migración aparente.

### D. Tests

- 613 tests corridos, todos OK, 4 skips (artefacto de entorno en `test_theme.py`, no
  gap real).
- **Hueco grande sin cubrir:** todo el pipeline HMI/OCR (`hmi_roi_tracker` 349 líneas,
  `hmi_numeric_reader`, `hmi_frame_stabilizer`, `hmi_ocr`, `hmi_video_loader` — ~890
  líneas combinadas) sin ningún test. Tampoco `fft_analysis.py`, `pgn_scanner.py`,
  `plot_exporter.py`, `session_state.py`.
- **`tests/README.md` desactualizado:** dice "418 tests", la suite real corre 613 —
  faltan ~20 archivos de test en el mapa (incluye `test_range_diff.py`,
  `test_theme.py`, `test_plot_incremental.py`, entre otros). Arreglo mecánico, bajo
  riesgo.

### E. Salud de código

- **Posible código muerto grande:** `views/signal/pipeline_builder.py` (984 líneas, 2º
  archivo más grande del repo) implementa el "Basic Mode" que este documento declara
  cancelado, pero sigue instanciándose en cada apertura de `derived_signal_dialog.py`
  (el toggle para alcanzarlo está permanentemente comentado, líneas 233,280-282). A
  verificar antes de eliminar — confirmar que de verdad no hay ningún camino que lo
  active.
- **Bug de threading potencialmente más extendido de lo documentado:** además del ya
  conocido `set_selected_id` (ver ROADMAP.md "Bug de performance: cambiar de CAN ID es
  lento"), `_full_refresh()` síncrono también se dispararía desde
  `set_mux_configuration`, `set_selected_mux_case` y `set_time_range`.
- **Posible bug nuevo, no documentado antes de esta auditoría:**
  `viewmodels/data_viewmodel.py::set_normalize` re-leería y re-parsearía el archivo de
  log completo desde disco síncronamente en el hilo principal, disparado por solo
  togglear la opción de normalización de timestamps — congelaría la UI en logs
  grandes. A verificar con un log real antes de confirmar como bug.
- `data_viewmodel.py::load_log`/`append_log` parecen código muerto (sin callers
  encontrados en esta pasada).
- **Triplicación de "qué cambió":** confirma lo que ya advierte ROADMAP.md § "Primitiva
  transversal: conjunto de cambiados monotónico" — hoy coexisten 3 implementaciones
  divergentes (`realtime_analysis.py`, `analyze_data.py`, `range_diff.py`), la
  unificación sigue sin ejecutarse.
- Strings hardcodeados: no sistemático, aislado a `mux_detection_window.py`
  (deshabilitado) y al `pipeline_builder.py` posiblemente muerto.
- `from __future__ import annotations`: faltaría en 17/149 archivos, incluyendo
  `plot_window.py`, `plot_renderer.py`, `can_log.py`, `can_decoder.py`,
  `candump_parser.py`.

### Priorización sugerida para cuando se decida verificar/actuar

| # | Hallazgo | Tipo | Impacto estimado |
|---|---|---|---|
| 1 | `data_viewmodel.set_normalize` bloquearía UI recargando el log completo | Posible bug nuevo | Alto |
| 2 | Fuga de thread de `candidate_interpretations_vm` al cerrar la app | Posible bug nuevo | Medio |
| 3 | `_full_refresh()` síncrono con más triggers de los documentados | Amplía bug conocido | Medio-alto |
| 4 | `pipeline_builder.py` (984 líneas posiblemente muertas) | Deuda/código muerto | Medio |
| 5 | `with_data_int` hot path + caso nuevo en `candidate_interpretations.py` | Perf (ya en plan) | Medio |
| 6 | `dbc_manager.py` como `QObject` en `services/` | Erosión arquitectónica | Bajo-medio |
| 7 | `tests/README.md` desactualizado (418 vs 613) | Doc drift | Bajo |
| 8 | HMI/OCR sin tests | Cobertura | Medio |

Los ítems 1-3 son candidatos a `/nuevo-bug` (verificación con `code-reviewer` +
regresión) cuando se decida priorizarlos — **no registrados todavía por pedido
explícito del usuario (2026-07-18)**.

---

## CAN Send — **COMPLETE** (merged into `dev`/`master`, released as v0.4.0)

First transmit-capable feature — until now Canlytics was read-only (load/stream/decode/
analyze, never send onto the bus). Supports one-shot and periodic frames, built from raw
hex or DBC-assisted (pick a loaded message, fill signal values,
`cantools.Message.encode(...)`), over **both** SSH and Kvaser backends. Replay mode rejects
sends (no real bus).

| File | Role |
|------|------|
| `models/can_send.py` | `TransmitEntry` (list-first data model — `entry_id`, `can_id`, `extended`, `dlc`, `data_hex` as the authoritative payload regardless of source, `source: "raw"\|"dbc"`, `dbc_source`, `mode: "single"\|"periodic"`, `interval_ms`, `enabled`), `DbcFrameSource`, `TxLogRecord` |
| `services/can_send.py` | Qt-free: `resolve_transmit_entry()` (the single choke point both editors funnel through — parses `can_id`/`data_hex`, validates DLC), `encode_dbc_payload()` (`cantools.Message.encode(scaling=True, padding=True, strict=False)` — `strict=False` is deliberate, TX/fault-injection is a legitimate use case unlike decode), `build_cansend_command()` (pads hex digits explicitly per standard/extended — can-utils' `cansend` infers frame type from digit count) |
| `services/remote_connection.py` | `exec_once(command, timeout=5.0)` — one-off blocking remote command, no PTY (would mangle exit-code semantics); must only be called from the thread that already owns the connection |
| `viewmodels/connection_stream_viewmodel.py` | `_ConnectionStreamWorker.send_frame()` (dispatches to `bus.send()` for Kvaser or `exec_once(cansend ...)` for SSH); `ConnectionStreamViewModel.request_send()` (rejects if not running or if mode is replay) |
| `viewmodels/can_send_viewmodel.py` | One `QTimer` per periodic-enabled entry (mirrors `RealTimeAnalysisViewModel`'s per-concern `QTimer` idiom); `_tx_log` capped at 500; constructor-injected `dbc_manager`/`connection_vm`/`session_state` |
| `views/can_send_window.py`, `can_send_entry_dialog.py`, `views/widgets/hex_byte_row.py` | Table (Enabled/Label/ID/Ext/DLC/Data/Source/Mode/Interval/Send Now/Periodic) + TX Log tab; entry dialog with raw-hex vs. DBC-assisted `QStackedWidget` pages |
| `views/can_send_window_manager.py` | `BaseWindowManager` subclass |

**The threading crux:** `_ConnectionStreamWorker.run()` is a blocking `while not self._stop:`
loop for the whole connection lifetime — Qt's `exec()` (needed to deliver a queued
cross-thread signal) is never reached until the loop exits. Fix: `QCoreApplication.
processEvents()` once per iteration inside the existing blocking loops (`_stream_lines()`
for SSH, the main loop in `_run_kvaser()`), turning them into a pump for queued calls —
latency bounded by their existing cadence (~10ms SSH idle poll, ~100ms Kvaser
`poll_timeout`). `_run_replay()` needs no change — replay sends are rejected synchronously
at the `ConnectionStreamViewModel` layer before ever reaching the worker. Every send (one-
shot and every periodic tick) routes through this same worker thread, keeping all bus/
transport access serialized for both backends — `python-can`'s native `send_periodic()` was
considered and rejected because its own background thread would call `.send()` concurrently
with the worker thread's `.recv()` on the same `Bus` object, an untested pattern.

**Persistence:** entry list persisted via `session_state.py`'s `get_window_prefs`/
`set_window_prefs` (window key `"can_send"`), restored eagerly in `CanSendViewModel.
__init__`. **Deliberately not persisted:** whether a periodic timer was *active* at last
shutdown — every session starts with periodic sends off, requiring explicit re-enable.

**Tests:** `tests/test_can_send.py` (`resolve_transmit_entry`, `encode_dbc_payload`,
`build_cansend_command`), `tests/test_connection_stream_viewmodel.py` (new file, also
covers the Kvaser-bitrate log metadata below).

---

## Signal Coverage (Signal Scan) — CSV export + PDU1 default (COMPLETE, v0.4.0)

- **CSV export button** (`views/signal_coverage_window.py`, icon `download`) — `_export_csv()`
  reads from `self.table` (respects current filters/sort) and writes extra columns beyond the
  visible table via `services/signal_coverage.py::export_signal_coverage_csv()`: `Start Bit`,
  `Length (bits)`, `Byte Order`, `Value Type`, `Scale`, `Offset`, `MUX Start`, `MUX bytes`,
  `MUX value` — sourced from the `SignalCoverageItem` stashed via `Qt.UserRole` on column 0.
  Scale/offset/mux geometry are **CSV-only**, never added to the visible table (user's
  explicit choice) — without them a re-imported mux signal can't be decoded, see below.
- **`hide_pdu1` filter now defaults to `True`** (`SignalCoverageWindow.__init__`, `self.
  _filters`) — a J1939 PDU1 signal legitimately appears once per source/destination-address
  pair sharing one PGN (PDU1: PF < 0xF0 → PGN = PF only, PS becomes a destination address,
  not part of the PGN) — the same signal name showing up under multiple CAN IDs is correct
  behavior, not a bug, and hiding PDU1 by default declutters the common case.
- Export always reflects the currently applied filters (including `hide_pdu1`).

This CSV export is what `pgn_csv_to_dbc.py`'s new "DBC Order" schema (below) can re-import.

---

## DBC ⇄ CSV round-trip: dual schema, auto-detected — **COMPLETE** (v0.4.0)

`services/pgn_csv_to_dbc.py` now accepts **two** independently-named, auto-detected CSV
schemas — "can I re-import the Signal Coverage export as a DBC?" turned out to need real
support for a second, structurally different CSV shape, not just a tweak to the existing one:

| Name | What it is | Signature columns (for auto-detect) |
|------|-----------|--------------------------------------|
| **CAI Order** | Pre-existing proprietary schema from CAI (a company) — the converter's original design target | `"PGN Byte Offset"`, `"Parameter Length (Bytes)"` |
| **DBC Order** | Signal Coverage's own CSV export schema (above) | `"CAN ID"`, `"Start Bit"`, `"Length (bits)"` |

- `detect_csv_order(fieldnames) -> str | None` — column **names** decide the schema, not
  column order or position, via set-inclusion of each schema's signature columns.
- `convert_pgn_csv_to_dbc(csv_path, dbc_path, *, order: str | None = None, ...)` — now returns
  a 3-tuple `(Database, list[SignalOverlap], resolved_order_name)`; `order=` forces a schema,
  skipping detection. DBC Order path returns `overlaps=[]` (overlap detection isn't
  implemented for this schema — mux-sharing bytes would false-positive the CAI-only check).
- `build_database_from_dbc_order_rows(rows) -> Database` — groups by CAN ID
  (`utils.can_id.can_id_to_int`), splits plain vs. mux rows (empty/non-empty `MUX Start`),
  matches a plain row occupying the mux selector's byte position as the multiplexor
  (`is_multiplexer=True`, synthesizing a bare selector `Signal` if none is found), builds mux
  rows with `multiplexer_signal`/`multiplexer_ids=[mux_value]` — real `cantools` multiplexing
  reconstruction, verified against the actual installed cantools 41.0.2 API (`Message()` takes
  **no** special multiplexing argument; it derives everything from the flat `signals` list via
  `Message.refresh()`). `is_extended_frame=can_id > STANDARD_ID_MAX` (`utils.j1939`).
- `UnrecognizedCsvOrderError(ValueError)` — raised instead of a generic `ValueError` when
  `detect_csv_order` returns `None` and no explicit `order` was forced.

**Manual format-picker fallback (SavvyCAN-style):** `viewmodels/dbc_load_worker.py`'s
`DbcLoadWorker(path, forced_order=None)` catches `UnrecognizedCsvOrderError` specifically
(before the generic `except Exception`) and emits a new `unrecognized_format(path,
display_name)` signal instead of `failed`. `views/dbc/dbc_manager_dialog.py::
_on_unrecognized_format()` shows a `QMessageBox` with `CAI_ORDER`/`DBC_ORDER` custom buttons
(English, per convention) + Cancel; picking one re-invokes `_start_dbc_load(path,
forced_order=<chosen>)`. On a successful **auto-detected** load, `_show_csv_order_info()`
confirms the detected format + message/signal counts via `QMessageBox.information`.

**Tests:** `tests/test_pgn_csv_to_dbc.py` extended — `DetectCsvOrderTests`,
`BuildDatabaseFromDbcOrderRowsTests` (simple/extended/signed/big-endian signals, PDU1 two-
CAN-IDs-same-PGN stay separate, muxed 2-case decode, missing-selector synthesis, empty-CAN-ID
skip, duplicate-name disambiguation, full round-trip via a real temp DBC file),
`ManualOrderOverrideTests` (unrecognized raises, explicit `order=` matches auto-detect,
forcing the wrong order yields zero messages rather than silently guessing right).

---

## Kvaser bitrate log metadata — **COMPLETE** (v0.4.0)

Saving a log now records the Kvaser bitrate it was captured at, **only if the log was
actually recorded via Kvaser this session** (not SSH/replay) — pure metadata, never
interpreted on load.

- `viewmodels/connection_stream_viewmodel.py`: `_ConnectionStreamWorker.
  kvaser_bitrate_resolved = QtSignal(int)`, emitted in `_run_kvaser()` right after the
  bitrate is resolved. `ConnectionStreamViewModel.last_kvaser_bitrate` (property, backed by
  `_last_kvaser_bitrate: int | None`) — reset to `None` on **every** `_start_worker()` call
  regardless of mode, so a stale bitrate from a previous Kvaser session can't leak into a
  later SSH/replay session's saved log.
- `views/main_window.py::_save_current_log`: if `connection_vm.last_kvaser_bitrate` is set,
  writes a leading `# Recorded via Kvaser @ {bitrate} bps` comment line before the frame rows.
- Loading tolerates the comment line unconditionally (candump parsing already skips
  non-frame lines) — `tests/test_can_data_parser.py::MetadataCommentLineTests` pins that a
  `#`-prefixed leading line doesn't break `load_can_dataframe`.
- `tests/test_connection_stream_viewmodel.py::LastKvaserBitrateTests` — initial `None`, set
  via the resolved signal, reset on every new `_start_worker()` call regardless of mode.

---

## CI: `cache-warm.yml` scoped to `requirements.txt` changes

`.github/workflows/cache-warm.yml` used to run its 3-platform (Windows/Linux/macOS) pip-cache
warm job on **every push to `master`**, even when nothing dependency-related changed — wasted
Actions minutes (macOS bills 10x on private repos) for a re-cache that changes nothing.
Scoped with `paths: [requirements.txt]` under the existing `on: push: branches: [master]`
trigger — it now only runs when the dependency list itself changes. Purpose: keeps `master`'s
pip cache warm so `release.yml`'s tag-triggered builds inherit it (GitHub isolates each tag's
own cache, but every ref falls back to the default branch's).

---

## Linux build size regression — root-caused and fixed (`feature/linux-build-size`, not yet merged)

v0.4.0's Linux release assets grew ~18MB (onefile and onedir) over v0.3.1, traced to the
Linux CI build environment switching from `python:3.11-slim-bullseye` to `ubuntu-latest`
(done earlier to fix a broken Linux pip cache) — the real dependency-discovery breakdown
(downloaded and diffed the actual released binaries via WSL) showed two distinct, unrelated
causes, both fixable in `Canlytics.spec`/`_build_common.py`:

1. **`libpython3.11.so.1.0` ships with debug symbols on `ubuntu-latest`** (23.05MB) that
   `slim-bullseye`'s didn't (5.38MB) — and **`Canlytics.spec` hardcoded `strip=False`
   unconditionally on all three build steps** (`EXE` onefile/onedir, `COLLECT`), on every
   platform. Windows already compensates via UPX (`_upx = sys.platform == 'win32'`); Linux/
   macOS never got PyInstaller's native `strip` pass at all. Fix: `_strip = sys.platform !=
   'win32'`, applied to all three `strip=` args — mirrors the existing `_upx` per-platform
   pattern. Empirically confirmed on the real v0.4.0 onedir release: stripping recovers
   **~46.6MB** (640MB → 577MB), more than the full regression — lands *below* v0.3.1's
   original 597MB baseline.
2. **`ubuntu-latest` has GTK3 installed**, so PyInstaller's `ldd`-based automatic binary
   discovery pulls in Qt's GTK3 platform-theme plugin
   (`_internal/PySide6/Qt/plugins/platformthemes/libqgtk3.so`) the moment it's importable,
   dragging the entire `libgtk-3`/`libgdk-3`/`libcairo`/`libpango`/`libatk`/`libgdk_pixbuf`
   chain with it (~11.4MB). Canlytics has its own complete theme system (`config/theme.py`,
   QPalette+QSS) and never relied on native GTK theming; `readelf -d` across every bundled
   `.so` confirmed `libqgtk3.so` is the **only** entry point into that chain — nothing else
   in the bundle links against any of those libs. Fix: `_build_common.
   GTK_PLATFORM_THEME_BINARY_EXCLUDES` (substring list) + `filter_binaries()`, applied to
   `a.binaries` right after `Analysis()` when `sys.platform not in ('win32', 'darwin')`.

Both fixes are Linux/macOS-only conditionals (`sys.platform`-gated) — the Windows build path
is untouched (verified: a local Windows build with these changes still succeeds). Branch
`feature/linux-build-size` (off `dev`) has the change; pending a Linux CI build to confirm
the stripped/filtered binary still runs, before merging.
