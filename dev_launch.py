"""Developer launcher — starts the app pre-loaded with a DBC and a log file.

Runs the full application but skips the splash screen and auto-loads the
specified DBC (in j1939 mode by default) and log file so you don't have to
click through the UI on every test run.

Usage (from CANAnalyzer/):
    python dev_launch.py --dbc path/to/file.dbc --log path/to/log.txt
    python dev_launch.py --dbc path/to/file.dbc --log path/to/log.txt --dbc-mode bam
    python dev_launch.py --dbc path/to/file.dbc --log path/to/log.txt --dbc-mode exact
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow


def _autoload(vm: MainWindowViewModel, dbc_path: str, log_path: str, dbc_mode: str) -> None:
    db = vm.dbc_manager.load_database(dbc_path)
    entry = vm.dbc_manager.add_loaded_db(dbc_path, db, mode=dbc_mode)
    print(f"[dev] DBC loaded: {entry.name!r} (mode={dbc_mode})")
    vm.start_load(path=log_path, mode="load")
    print(f"[dev] Log loading: {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev launcher — starts CAN Analyzer pre-loaded with a DBC and a log file.",
    )
    parser.add_argument("--dbc", required=True, help="Path to .dbc file")
    parser.add_argument("--log", required=True, help="Path to CAN log file")
    parser.add_argument(
        "--dbc-mode",
        default="j1939",
        choices=["exact", "j1939", "bam"],
        help="DBC matching mode (default: j1939)",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    vm = MainWindowViewModel()
    w = MainWindow(vm)
    w.show()
    app.processEvents()

    # Wait for any session-state DBC restoration to finish before adding the dev DBC,
    # so the dev entry appears last (and doesn't race with the restore worker).
    vm.dbc_restore_finished.connect(
        lambda _: _autoload(vm, args.dbc, args.log, args.dbc_mode)
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
