from PySide6.QtCore import QObject, Signal

from services.can_log import CANLog


class LogLoaderWorker(QObject):
    finished = Signal(str, object, bool, object)
    canceled = Signal()
    failed = Signal(str)

    def __init__(self, path: str, normalize: bool, mode: str, source_tz_offset_minutes: int | None = None):
        super().__init__()
        self._path = path
        self._normalize = normalize
        self._mode = mode
        self._source_tz_offset_minutes = source_tz_offset_minutes
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            if self._cancel_requested:
                self.canceled.emit()
                return

            log = CANLog(self._path, source_tz_offset_minutes=self._source_tz_offset_minutes)
            df = log.load(self._normalize if self._mode == "load" else False)

            if self._cancel_requested:
                self.canceled.emit()
                return

            self.finished.emit(self._path, df, self._mode == "load", self._source_tz_offset_minutes)
        except Exception as exc:
            self.failed.emit(str(exc))

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested
