from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
import polars as pl

class TableViewModel(QObject):
    def __init__(self, model):
        super().__init__()
        self._model = model
        self._pending_df: pl.DataFrame | None = None
        self._has_pending_df = False
        self._pending_rows: list[pl.DataFrame] = []
        self._scheduled = False

    def set_dataframe(self, df: pl.DataFrame | None):
        self._pending_df = df
        self._has_pending_df = True
        self._pending_rows.clear()

        self._schedule_flush()

    def append_rows(self, delta: pl.DataFrame):
        if delta is None or delta.is_empty():
            return
        self._pending_rows.append(delta)
        self._schedule_flush()

    def _schedule_flush(self):
        if self._scheduled:
            return

        self._scheduled = True
        QTimer.singleShot(0, self._flush)

    def _flush(self):
        self._scheduled = False

        if not self._has_pending_df and not self._pending_rows:
            return

        if self._has_pending_df:
            self._model.set_dataframe(self._pending_df)
        self._pending_df = None
        self._has_pending_df = False
        if self._pending_rows:
            delta = (
                self._pending_rows[0]
                if len(self._pending_rows) == 1
                else pl.concat(self._pending_rows, how="vertical", rechunk=False)
            )
            self._pending_rows.clear()
            self._model.append_rows(delta)

    def set_decode_context(self, dbc_manager, enabled: bool):
        self._model.set_decode_context(dbc_manager, enabled)

    def set_all_expanded(self, expanded: bool):
        self._model.set_all_expanded(expanded)

    def toggle_row_expanded(self, row: int):
        self._model.toggle_row_expanded(row)
