from PySide6.QtCore import QObject, Signal
import polars as pl

from core.canlog import CANLog


class LogDataViewModel(QObject):
    dataframe_changed = Signal(object)
    can_ids_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self._log = None
        self._df_all = None
        self._normalize = False

    @property
    def df(self) -> pl.DataFrame | None:
        return self._df_all

    @property
    def normalize(self) -> bool:
        return self._normalize

    def load_log(self, path: str):
        self._log = CANLog(path)
        self._df_all = self._log.load(self._normalize)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def append_log(self, path: str):
        new_log = CANLog(path)
        df_new = new_log.load(normalize_time=False)

        if df_new.is_empty():
            return

        if self._df_all is None or self._df_all.is_empty():
            self._log = new_log
            self._df_all = df_new
        else:
            if self._normalize:
                base_ts = self._df_all.select(pl.first("TS")).item()
                df_new = df_new.with_columns(
                    (pl.col("TS") - base_ts).round(6).alias("TS")
                )

            self._df_all = pl.concat(
                [self._df_all, df_new],
                how="vertical",
                rechunk=True,
            ).sort("TS")

        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def set_normalize(self, value: bool):
        self._normalize = value
        if not self._log:
            return

        self._df_all = self._log.load(self._normalize)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def replace_log(self, path: str, df: pl.DataFrame):
        self._log = CANLog(path)
        self._df_all = df
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def append_df(self, df_new: pl.DataFrame):
        if df_new.is_empty():
            return

        if self._df_all is None or self._df_all.is_empty():
            self._df_all = df_new
        else:
            if self._normalize:
                base_ts = self._df_all.select(pl.first("TS")).item()
                df_new = df_new.with_columns(
                    (pl.col("TS") - base_ts).round(6).alias("TS")
                )

            self._df_all = pl.concat(
                [self._df_all, df_new],
                how="vertical",
                rechunk=True,
            ).sort("TS")

        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def clear(self):
        self._log = None
        self._df_all = pl.DataFrame({c: [] for c in DEFAULT_COLUMNS})
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def _emit_ids(self):
        if self._df_all is None or "ID" not in self._df_all.columns:
            self.can_ids_changed.emit([])
            return

        ids = sorted(self._df_all["ID"].unique().to_list())
        self.can_ids_changed.emit(ids)


DEFAULT_COLUMNS = [
    "TS", "Bus", "ID", "DATA", "LEN",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
]
