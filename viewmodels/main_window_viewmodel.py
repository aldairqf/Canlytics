from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal

from models.log_columns import DEFAULT_COLUMNS
from services.dbc_manager import DbcManager
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.log_load_viewmodel import LogLoadViewModel
from viewmodels.ssh_can_stream_viewmodel import SshCanStreamViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from viewmodels.table_viewmodel import TableViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel


class MainWindowViewModel(QObject):
    normalize_applied = QtSignal(bool)
    timezone_changed = QtSignal(str)
    log_cleared = QtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._timezone_mode = "none"

        self.dbc_manager = DbcManager()
        self.data_vm = LogDataViewModel()
        self.filter_vm = TableFilterViewModel()
        self.table_model = TableModel(DEFAULT_COLUMNS)
        self.table_vm = TableViewModel(self.table_model)

        self.log_load_vm = LogLoadViewModel(self)
        self.interpret_vm = InterpretationViewModel(self.dbc_manager, self.table_vm, parent=self)
        self.time_config_vm = TimeConfigViewModel(
            normalize=bool(getattr(self.data_vm, "normalize", False)),
            timezone=self._timezone_mode,
            parent=self,
        )
        self.ssh_vm = SshCanStreamViewModel(self)

        self.data_vm.dataframe_changed.connect(self.filter_vm.set_dataframe)
        self.filter_vm.dataframe_changed.connect(self.table_vm.set_dataframe)
        self.ssh_vm.chunk_ready.connect(self.data_vm.append_df)
        self.log_load_vm.loaded.connect(self._apply_loaded_df)
        self.time_config_vm.normalize_changed.connect(self._apply_normalize)
        self.time_config_vm.timezone_changed.connect(self._set_timezone)

    @property
    def timezone_mode(self) -> str:
        return self._timezone_mode

    def start_load(self, *, path: str, mode: str) -> None:
        normalize = bool(getattr(self.data_vm, "normalize", False))
        self.log_load_vm.start(path=path, normalize=normalize, mode=mode)

    def clear_log(self) -> None:
        self.data_vm.clear()
        self.log_cleared.emit()

    def shutdown(self) -> None:
        self.ssh_vm.shutdown()
        self.log_load_vm.shutdown()
        self.interpret_vm.shutdown()

    def _apply_loaded_df(self, path, df, is_full_load: bool) -> None:
        if is_full_load:
            self.data_vm.replace_log(path, df)
        else:
            self.data_vm.append_df(df)

    def _apply_normalize(self, normalize: bool) -> None:
        self.data_vm.set_normalize(normalize)
        self.normalize_applied.emit(normalize)

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = tz
        self.timezone_changed.emit(tz)
