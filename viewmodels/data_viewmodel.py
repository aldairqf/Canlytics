from PySide6.QtCore import QObject, Signal
import polars as pl

from models.log_columns import DEFAULT_COLUMNS
from services.can_log import CANLog
from services.contracts import DataService, LogLoaderService
from services.log_data_service import LogDataService


class LogDataViewModel(QObject):
    dataframe_changed = Signal(object)
    can_ids_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self._log: LogLoaderService | None = None
        self._df_all = None
        self._normalize = False
        self._data_service: DataService = LogDataService()

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

        self._df_all = self._data_service.merge_frames(
            self._df_all,
            df_new,
            normalize=self._normalize,
        )

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

        self._df_all = self._data_service.merge_frames(
            self._df_all,
            df_new,
            normalize=self._normalize,
        )

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
