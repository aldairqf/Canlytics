from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal as QtSignal

from config.app_config import get_option
from services.measurement_status import (
    FrameRateTracker, memory_warning_threshold_bytes, process_memory_bytes, system_memory_bytes,
)


@dataclass(frozen=True)
class MeasurementStatus:
    frame_count: int
    frames_per_second: float
    process_memory_bytes: int | None
    warning_threshold_bytes: int | None
    active_dbc_names: tuple[str, ...]


class MeasurementStatusViewModel(QObject):
    status_changed = QtSignal(object)
    memory_warning_requested = QtSignal(int, int)

    def __init__(self, dbc_manager=None, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._frame_count = 0
        self._frame_rate = FrameRateTracker()
        self._total_memory_bytes = system_memory_bytes()
        self._warning_active = False
        self._timer = QTimer(self)
        self._timer.setInterval(int(get_option("measurement_status_refresh_ms", 1000)))
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        if self._dbc_manager is not None:
            self._dbc_manager.entries_changed.connect(self.refresh)
        self.refresh()

    @property
    def status(self) -> MeasurementStatus:
        memory = process_memory_bytes()
        threshold = self._warning_threshold()
        return MeasurementStatus(
            frame_count=self._frame_count,
            frames_per_second=self._frame_rate.frames_per_second(),
            process_memory_bytes=memory,
            warning_threshold_bytes=threshold,
            active_dbc_names=tuple(
                entry.name for entry in self._dbc_manager.active_entries()
            ) if self._dbc_manager is not None else (),
        )

    def ingest_chunk(self, chunk) -> None:
        self._frame_rate.add(getattr(chunk, "height", 0))

    def append_rows(self, delta, *_args) -> None:
        self._frame_count += int(getattr(delta, "height", 0))

    def replace_data(self, dataframe) -> None:
        self._frame_count = int(getattr(dataframe, "height", 0))
        if self._frame_count == 0:
            self._warning_active = False

    def set_connection_running(self, running: bool) -> None:
        if not running:
            self._frame_rate = FrameRateTracker()
        self.refresh()

    def refresh(self) -> None:
        status = self.status
        threshold = status.warning_threshold_bytes
        memory = status.process_memory_bytes
        if (memory is None or threshold is None or memory < threshold or self._frame_count == 0):
            self._warning_active = False
        elif not self._warning_active:
            self._warning_active = True
            self.memory_warning_requested.emit(memory, threshold)
        self.status_changed.emit(status)

    def shutdown(self) -> None:
        self._timer.stop()

    def _warning_threshold(self) -> int | None:
        if self._total_memory_bytes is None:
            return None
        return memory_warning_threshold_bytes(
            self._total_memory_bytes,
            int(get_option("memory_warning_absolute_bytes", 2 * 1024**3)),
            float(get_option("memory_warning_system_fraction", 0.60)),
        )
