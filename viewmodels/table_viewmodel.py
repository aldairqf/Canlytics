from PySide6.QtCore import QObject, QTimer
import polars as pl

class TableViewModel(QObject):
    def __init__(self, model):
        super().__init__()
        self._model = model
        self._pending_df: pl.DataFrame | None = None
        self._scheduled = False

    def set_dataframe(self, df: pl.DataFrame):
        self._pending_df = df

        if self._scheduled:
            return

        self._scheduled = True
        QTimer.singleShot(0, self._flush)

    def _flush(self):
        self._scheduled = False

        if self._pending_df is None:
            return

        self._model.set_dataframe(self._pending_df)
        self._pending_df = None

    def set_decode_context(self, dbc_manager, enabled: bool):
        self._model.set_decode_context(dbc_manager, enabled)

    def set_all_expanded(self, expanded: bool):
        self._model.set_all_expanded(expanded)

    def toggle_row_expanded(self, row: int):
        self._model.toggle_row_expanded(row)
