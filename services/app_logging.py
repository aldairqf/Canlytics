"""App-wide logging setup: one root logger, console + rotating file handlers, plus
a Qt-bridging handler for the (future) live debug window.

`logging.getLogger(__name__)` per module already gives the "tag per module" the
user asked for (e.g. `viewmodels.candidate_interpretations_viewmodel`) -- no
separate tagging system needed. Default level is INFO (INFO/WARNING/ERROR always
captured); the "Debug" checkbox in the Debug Log window raises it to DEBUG. The
rotating file handler is always active regardless of that toggle, so
".canlytics_state/logs/canlytics.log" is there to attach to a bug report even if
the user never turned debug mode on.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from PySide6.QtCore import QObject, Signal as QtSignal

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s/%(name)s: %(message)s"
DATE_FORMAT = "%m-%d %H:%M:%S"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


class QtLogHandler(logging.Handler, QObject):
    """Bridges stdlib log records to Qt -- workers run on QThreads and can't touch
    a QWidget directly, so the debug window subscribes to record_emitted instead
    of polling the log file (same worker->view signal pattern as everywhere else)."""

    record_emitted = QtSignal(str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.record_emitted.emit(self.format(record))
        except Exception:
            self.handleError(record)


def log_file_path(state_dir: Path) -> Path:
    """Single source of truth for where the rotating log file lives -- both
    configure_logging() and the debug window (to backfill its history on open)
    derive the path from here instead of each re-deriving "logs/canlytics.log"."""
    return Path(state_dir) / "logs" / "canlytics.log"


def configure_logging(state_dir: Path, *, level: int = logging.INFO) -> QtLogHandler:
    """Call once at startup (main.py). Returns the QtLogHandler so a debug window
    opened later can subscribe to record_emitted without reconfiguring the root
    logger again."""
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = log_file_path(state_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    qt_handler = QtLogHandler()
    qt_handler.setFormatter(formatter)
    root.addHandler(qt_handler)

    return qt_handler


def set_debug_enabled(enabled: bool) -> None:
    logging.getLogger().setLevel(logging.DEBUG if enabled else logging.INFO)


def is_debug_enabled() -> bool:
    return logging.getLogger().getEffectiveLevel() <= logging.DEBUG
