from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

_TICK_MS = 250


class EtaProgressDialog(QProgressDialog):
    """QProgressDialog that always shows a live percentage + ETA once report_progress()
    starts getting called, instead of a bare indeterminate spinner -- shared by every
    long-running operation in the app (user rule, 2026-07-19: every loading window).

    The label refreshes on its own tick (not only when a new report_progress() call
    arrives): a worker can go many seconds between progress callbacks (e.g. one slow
    group in Candidate Interpretations' search), and a label that only updates on
    callback made the whole dialog look frozen -- percentage AND the "~Xs left"
    countdown both stuck, indistinguishable from a hang (user report, 2026-07-19).
    """

    def __init__(self, message: str, cancel_text: str, parent: QWidget | None = None):
        super().__init__(message, cancel_text, 0, 0, parent)
        self._message = message
        self._start_time: float | None = None
        self._done = 0
        self._total = 0
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumDuration(0)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_TICK_MS)
        self._tick_timer.timeout.connect(self._refresh_label)

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._done = 0
        self._total = 0
        self.show()
        self._tick_timer.start()

    def report_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        if self.maximum() != total:
            self.setRange(0, total)
        self.setValue(done)
        self._done = done
        self._total = total
        self._refresh_label()

    def _refresh_label(self) -> None:
        if self._total <= 0 or self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        percent = int(self._done * 100 / self._total)
        text = f"{self._message} ({percent}%)"
        if self._done > 0 and elapsed > 0.5:
            rate = self._done / elapsed  # average items/sec since start, recomputed every tick
            remaining = self._total / rate - elapsed
            if remaining > 0.5:
                text += f" -- ~{format_eta(remaining)} left"
            else:
                # Already past the last estimate but not done -- ticking "0s left"
                # forever would look just as frozen as before; count elapsed time
                # up instead so the user can still see it's alive.
                text += f" -- finishing up ({format_eta(elapsed)} elapsed)"
        self.setLabelText(text)

    def closeEvent(self, event) -> None:
        # Every call site in this app closes these dialogs via .close() (not
        # .accept()/.reject()), which does NOT reliably emit finished() on
        # QProgressDialog -- confirmed empirically, not an assumption. Without this,
        # the tick QTimer would keep firing every 250ms forever on an orphaned-but-
        # still-alive dialog (parented to the window, so Qt doesn't destroy it just
        # because the Python reference is dropped).
        self._tick_timer.stop()
        super().closeEvent(event)


def format_eta(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs:02d}s"
