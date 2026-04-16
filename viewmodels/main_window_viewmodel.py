from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from config.defaults import DEFAULT_COLUMNS
from services.dbc_manager import DbcManager
from services.session_state import SessionStateStore
from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel
from viewmodels.mux_detection_viewmodel import MuxDetectionViewModel
from viewmodels.log_load_viewmodel import LogLoadViewModel
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from viewmodels.table_viewmodel import TableViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel


class MainWindowViewModel(QObject):
    normalize_applied = QtSignal(bool)
    timezone_changed = QtSignal(str)
    log_cleared = QtSignal()
    dbc_restore_started = QtSignal()
    dbc_restore_finished = QtSignal(bool)
    dbc_restore_failed = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._timezone_mode = "none"
        self.session_state = SessionStateStore()

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
        self.connection_vm = ConnectionStreamViewModel(self)
        self.real_time_analysis_vm = RealTimeAnalysisViewModel(self)
        self.analyze_data_vm = AnalyzeDataViewModel(self)
        self.candidate_interpretations_vm = CandidateInterpretationsViewModel(self)
        self.mux_detection_vm = MuxDetectionViewModel(self)

        self.data_vm.dataframe_changed.connect(self.filter_vm.set_history_dataframe)
        self.data_vm.dataframe_changed.connect(self.analyze_data_vm.set_dataframe)
        self.data_vm.dataframe_changed.connect(self.candidate_interpretations_vm.set_dataframe)
        self.data_vm.dataframe_changed.connect(self.mux_detection_vm.set_dataframe)
        self.filter_vm.dataframe_changed.connect(self.table_vm.set_dataframe)
        self.connection_vm.chunk_ready.connect(self.data_vm.append_df)
        self.connection_vm.chunk_ready.connect(self.real_time_analysis_vm.ingest_df)
        self.log_load_vm.loaded.connect(self._apply_loaded_df)
        self.time_config_vm.normalize_changed.connect(self._apply_normalize)
        self.time_config_vm.timezone_changed.connect(self._set_timezone)
        self.dbc_manager.entries_changed.connect(self._sync_session_state)
        self._restore_thread: QThread | None = None
        self._restore_worker: _DbcRestoreWorker | None = None

    @property
    def timezone_mode(self) -> str:
        return self._timezone_mode

    def start_load(self, *, path: str, mode: str, source_tz_offset_minutes: int | None = None) -> None:
        normalize = bool(getattr(self.data_vm, "normalize", False))
        self.session_state.add_recent_log(path)
        self.log_load_vm.start(
            path=path,
            normalize=normalize,
            mode=mode,
            source_tz_offset_minutes=source_tz_offset_minutes,
        )

    def clear_log(self) -> None:
        self.data_vm.clear()
        self.real_time_analysis_vm.clear()
        self.log_cleared.emit()

    def shutdown(self) -> None:
        self.connection_vm.shutdown()
        self.log_load_vm.shutdown()
        self.interpret_vm.shutdown()
        self.mux_detection_vm.shutdown()
        if self._restore_thread is not None and self._restore_thread.isRunning():
            if self._restore_worker is not None:
                self._restore_worker.request_stop()
            self._restore_thread.quit()
            self._restore_thread.wait()

    def start_restore_dbcs(self) -> None:
        if self._restore_thread is not None and self._restore_thread.isRunning():
            return

        saved = self.session_state.get_saved_dbcs()
        if not saved:
            self.dbc_restore_finished.emit(False)
            return

        self.dbc_restore_started.emit()
        self._restore_worker = _DbcRestoreWorker(saved)
        self._restore_thread = QThread(self)
        self._restore_worker.moveToThread(self._restore_thread)
        self._restore_thread.started.connect(self._restore_worker.run)
        self._restore_worker.finished.connect(self._on_restore_finished)
        self._restore_worker.failed.connect(self._on_restore_failed)
        self._restore_worker.finished.connect(self._restore_thread.quit)
        self._restore_worker.failed.connect(self._restore_thread.quit)
        self._restore_thread.finished.connect(self._cleanup_restore_worker)
        self._restore_thread.start()

    def _apply_loaded_df(self, path, df, is_full_load: bool, source_tz_offset_minutes=None) -> None:
        if is_full_load:
            self.data_vm.replace_log(path, df, source_tz_offset_minutes=source_tz_offset_minutes)
        else:
            self.data_vm.append_df(df)

    def _apply_normalize(self, normalize: bool) -> None:
        self.data_vm.set_normalize(normalize)
        self.normalize_applied.emit(normalize)

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = tz
        self.timezone_changed.emit(tz)

    def _sync_session_state(self) -> None:
        self.session_state.sync_dbc_manager(self.dbc_manager)

    def _on_restore_finished(self, payload: list[dict]) -> None:
        restored_names: list[str] = []
        active_names: set[str] = set()
        for item in payload:
            try:
                entry = self.dbc_manager.add_loaded_db(
                    item["path"],
                    item["db"],
                    preferred_name=item.get("name"),
                    active=bool(item.get("active", True)),
                    mode=str(item.get("mode") or "exact"),
                )
            except Exception:
                continue
            restored_names.append(entry.name)
            if entry.active:
                active_names.add(entry.name)

        if restored_names:
            self.dbc_manager.set_order(restored_names)
            self.dbc_manager.set_active(active_names)
        self.dbc_restore_finished.emit(bool(restored_names))

    def _on_restore_failed(self, message: str) -> None:
        self.dbc_restore_failed.emit(message)
        self.dbc_restore_finished.emit(False)

    def _cleanup_restore_worker(self) -> None:
        if self._restore_worker is not None:
            self._restore_worker.deleteLater()
            self._restore_worker = None
        if self._restore_thread is not None:
            self._restore_thread.deleteLater()
            self._restore_thread = None


class _DbcRestoreWorker(QObject):
    finished = QtSignal(object)
    failed = QtSignal(str)

    def __init__(self, saved: list[dict]):
        super().__init__()
        self._saved = list(saved)
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            loader = DbcManager()
            payload: list[dict] = []
            for item in sorted(self._saved, key=lambda row: int(row.get("order", 0))):
                if self._stop_requested:
                    break
                stored_path = str(item.get("path") or "").strip()
                if not stored_path:
                    continue
                try:
                    db = loader._load_database(stored_path)
                except Exception:
                    continue
                payload.append(
                    {
                        "name": str(item.get("name") or ""),
                        "path": stored_path,
                        "active": bool(item.get("active", True)),
                        "mode": str(item.get("mode") or "exact"),
                        "db": db,
                    }
                )
            self.finished.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))
