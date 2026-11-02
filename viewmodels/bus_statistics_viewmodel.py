from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal as QtSignal
import polars as pl

from config.app_config import get_option
from services.bus_statistics import BusStatisticsAccumulator, BusStatisticsSnapshot


class BusStatisticsViewModel(QObject):
    statistics_changed = QtSignal(object)

    def __init__(self, connection_vm: QObject, parent: QObject | None = None):
        super().__init__(parent)
        self._connection_vm = connection_vm
        self._accumulator = BusStatisticsAccumulator(
            missing_after_seconds=float(get_option("bus_stats_missing_after_seconds", 2.0))
        )
        self._live = False
        self._bitrate: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(int(get_option("measurement_status_refresh_ms", 1000)))
        self._timer.timeout.connect(self.publish)
        self._timer.start()
        self._snapshot = self._accumulator.snapshot()

    @property
    def snapshot(self) -> BusStatisticsSnapshot:
        return self._snapshot

    def ingest_chunk(self, dataframe: pl.DataFrame) -> None:
        self._accumulator.ingest(dataframe)

    def seed_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        self._bitrate = None
        self._accumulator.seed(dataframe)
        self.publish()

    def reset(self) -> None:
        self._accumulator.reset()
        self.publish()

    def set_connection_running(self, running: bool) -> None:
        self._live = bool(running)
        self._bitrate = self._connection_vm.last_kvaser_bitrate if running else self._bitrate
        self.publish()

    def set_bitrate(self, bitrate: int) -> None:
        self._bitrate = int(bitrate)
        self.publish()

    def publish(self) -> None:
        if self._connection_vm.running and self._connection_vm.last_kvaser_bitrate:
            self._bitrate = self._connection_vm.last_kvaser_bitrate
        self._snapshot = self._accumulator.snapshot(bitrate=self._bitrate, live=self._live)
        self.statistics_changed.emit(self._snapshot)

    def shutdown(self) -> None:
        self._timer.stop()
