from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.protocol_observer import IsoTpObserver, classify_diagnostic_payload


def filter_diagnostic_rows(dataframe: pl.DataFrame, configured_ids: list) -> pl.DataFrame:
    if dataframe is None or dataframe.is_empty():
        return dataframe
    can_id = pl.col("ID").cast(pl.Utf8).str.replace(r"(?i)^0x", "").str.to_integer(base=16, strict=False)
    standard_ids = [0x7DF, *range(0x7E0, 0x7F0), 0x18DB33F1]
    configured = [int(value, 16) if isinstance(value, str) else int(value) for value in configured_ids]
    matches = can_id.is_in(standard_ids + configured)
    matches |= can_id.is_between(0x7E0, 0x7EF)
    matches |= pl.col("ID").cast(pl.Utf8).str.replace(r"(?i)^0x", "").str.to_uppercase().str.contains(
        r"^18DA[0-9A-F]{4}$")
    return dataframe.filter(matches).sort("TS", maintain_order=True)


class DiagnosticsHistoryWorker(QObject):
    started = QtSignal(int)
    progress = QtSignal(int, int)
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)

    def __init__(self, dataframe: pl.DataFrame, timeout_seconds: float, configured_ids: list,
                 progress_batch_size: int) -> None:
        super().__init__()
        self._dataframe = dataframe
        self._timeout_seconds = timeout_seconds
        self._configured_ids = configured_ids
        self._progress_batch_size = progress_batch_size
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            rows = filter_diagnostic_rows(self._dataframe, self._configured_ids)
            total = rows.height
            self.started.emit(total)
            observer = IsoTpObserver(self._timeout_seconds, self._configured_ids)
            messages = []
            batch_size = max(1, self._progress_batch_size)
            for index, row in enumerate(rows.iter_rows(named=True), 1):
                if self._cancelled:
                    self.canceled.emit()
                    return
                try:
                    can_id = int(str(row["ID"]).removeprefix("0x").removeprefix("0X"), 16)
                    data = bytes.fromhex(str(row["DATA"]))
                    timestamp = float(row["TS"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                for message in observer.ingest(can_id, data, timestamp):
                    item = classify_diagnostic_payload(message.can_id, message.payload)
                    if item is not None:
                        messages.append(item)
                if index % batch_size == 0 or index == total:
                    self.progress.emit(index, max(1, total))
            self.finished.emit(messages)
        except Exception as exc:
            self.failed.emit(str(exc))
