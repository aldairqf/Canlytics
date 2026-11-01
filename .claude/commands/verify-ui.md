---
description: Launch Canlytics (python main.py) to verify a change actually works, not just that it imports
argument-hint: "[flow to check, e.g. 'open Range Diff and run a comparison']"
allowed-tools: Bash, PowerShell, Read, Glob, Grep
---

Launch Canlytics to verify: **$ARGUMENTS**

Steps:
1. From the repo root, use the project venv (`.venv/Scripts/python.exe`).
2. Prefer a targeted smoke script over a bare `python main.py` when you need to drive a
   specific flow (load a fixture log, open a window, click a button) rather than just
   confirm the app boots. Pattern used throughout this project's sessions:

```python
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow

app = QApplication(sys.argv)
vm = MainWindowViewModel()
win = MainWindow(vm)
# ... drive the flow named in $ARGUMENTS here (open a window, load a fixture log
# from tests/fixtures/logs/, toggle a control, run an analysis) ...
QTimer.singleShot(300, app.quit)
app.exec()
vm.shutdown()
print("OK")
```

3. If the flow involves loading data, use a fixture from `tests/fixtures/logs/` or
   `tests/fixtures/dbc/` rather than a hand-built dataframe, unless the flow needs
   something a fixture can't produce.
4. **Screenshots as evidence.** After each step of the flow, capture every relevant window with `widget.grab().save("<scratchpad>/verify/<step>.png")`. Call `app.processEvents()` before each capture so the window has repainted. Then open each PNG with the Read tool and check what it actually shows (rows, order, highlights, empty states, dialogs). For live flows, replay a real log through Connection → Replay rather than a hand-built dataframe. Never write screenshots into the repo.
5. Report what you actually observed (window opened, control worked, exception raised)
   — never claim success just because the script imported or exited 0 without checking.
6. If the app can't launch (missing hardware backend, headless environment), say so
   explicitly instead of silently skipping verification.

Remember: before calling a change with visible/behavioral surface done, run it and watch
the actual flow — a passing test suite proves the logic, not the feature.
