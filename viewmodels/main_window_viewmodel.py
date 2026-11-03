from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

import polars as pl
from cantools.database.can import Message
from PySide6.QtCore import QObject, QThread, Qt, Signal as QtSignal

from config.defaults import DEFAULT_COLUMNS
from config.app_config import get_option, get_text
from services.continuous_recorder import find_interrupted_recording, make_recording_path, dismiss_interrupted_recording
from services.app_logging import QtLogHandler
from services.dbc_manager import DbcManager
from services.working_dbc import WorkingDbc
from services.session_state import SessionStateStore
from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel
from viewmodels.can_send_viewmodel import CanSendViewModel
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel
from viewmodels.mux_detection_viewmodel import MuxDetectionViewModel
from viewmodels.log_load_viewmodel import LogLoadViewModel
from viewmodels.log_export_viewmodel import LogExportViewModel
from viewmodels.continuous_recorder_viewmodel import ContinuousRecorderViewModel
from viewmodels.range_diff_viewmodel import RangeDiffViewModel
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel
from viewmodels.signal_coverage_viewmodel import SignalCoverageViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from viewmodels.table_viewmodel import TableViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.time_range_viewmodel import TimeRangeViewModel
from viewmodels.measurement_status_viewmodel import MeasurementStatusViewModel
from viewmodels.bus_statistics_viewmodel import BusStatisticsViewModel
from viewmodels.analysis_context_viewmodel import AnalysisContextViewModel
from viewmodels.mux_configuration_viewmodel import MuxConfigurationViewModel
from viewmodels.mcp_session_viewmodel import McpSessionViewModel
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel

logger = logging.getLogger(__name__)


def new_session_prompt_kind(has_unsaved: bool) -> str:
    return "save_discard_append_cancel" if has_unsaved else "none"


def unsaved_prompt_kind(has_data: bool, has_unsaved: bool) -> str:
    if has_unsaved:
        return "save_discard_cancel"
    if has_data:
        return "confirm"
    return "none"


class MainWindowViewModel(QObject):
    normalize_applied = QtSignal(bool)
    timezone_changed = QtSignal(str)
    log_cleared = QtSignal()
    dbc_restore_started = QtSignal()
    dbc_restore_finished = QtSignal(bool)
    dbc_restore_failed = QtSignal(str)
    dbc_restore_progress = QtSignal(int, int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        qt_log_handler: QtLogHandler | None = None,
        enable_mcp_session: bool = False,
        mcp_session_endpoint_path: str | Path | None = None,
    ):
        super().__init__(parent)
        self._timezone_mode = "none"
        self.session_state = SessionStateStore()
        self.mux_configuration_vm = MuxConfigurationViewModel(self.session_state, self)
        self.qt_log_handler = qt_log_handler

        self.dbc_manager = DbcManagerViewModel(self)
        self.working_dbc = WorkingDbc()
        working_entry = self.dbc_manager.add_loaded_db(
            str(self.session_state.working_dbc_path),
            self.working_dbc.database_copy(),
            preferred_name="Working DBC",
            active=True,
            mode="exact",
        )
        self._working_dbc_entry_name = working_entry.name
        self.data_vm = LogDataViewModel()
        self.filter_vm = TableFilterViewModel()
        self.table_model = TableModel(DEFAULT_COLUMNS)
        self.table_vm = TableViewModel(self.table_model)

        self.log_load_vm = LogLoadViewModel(self)
        self.log_export_vm = LogExportViewModel(self)
        self.continuous_recorder_vm = ContinuousRecorderViewModel(self)
        recording_directory = Path(str(get_option("continuous_recording_directory", "~/Canlytics/Recordings"))).expanduser()
        self.interrupted_recording = find_interrupted_recording(recording_directory)
        self.interpret_vm = InterpretationViewModel(self.dbc_manager, self.table_vm, parent=self)
        self.time_config_vm = TimeConfigViewModel(
            normalize=bool(getattr(self.data_vm, "normalize", False)),
            timezone=self._timezone_mode,
            parent=self,
        )
        self.time_range_vm = TimeRangeViewModel(self)
        self.connection_vm = ConnectionStreamViewModel(self)
        self.measurement_status_vm = MeasurementStatusViewModel(self.dbc_manager, self)
        self.bus_statistics_vm = BusStatisticsViewModel(self.connection_vm, self)
        self.real_time_analysis_vm = RealTimeAnalysisViewModel(self)
        self.analyze_data_vm = AnalyzeDataViewModel(self)
        self.candidate_interpretations_vm = CandidateInterpretationsViewModel(self)
        self.mux_detection_vm = MuxDetectionViewModel(self)
        self.signal_coverage_vm = SignalCoverageViewModel(self.dbc_manager, self)
        self.range_diff_vm = RangeDiffViewModel(self.dbc_manager, self)
        self.can_send_vm = CanSendViewModel(self.dbc_manager, self.connection_vm, self.session_state, self)
        self.analysis_context_vm = AnalysisContextViewModel(self)

        for consumer in (
            self.filter_vm,
            self.analyze_data_vm,
            self.mux_detection_vm,
        ):
            self.time_range_vm.range_changed.connect(consumer.set_time_range)
        self.time_range_vm.range_changed.connect(self.candidate_interpretations_vm.set_global_time_range)

        for consumer in (
            self.real_time_analysis_vm,
            self.analyze_data_vm,
            self.candidate_interpretations_vm,
            self.range_diff_vm,
        ):
            consumer.set_mux_configuration(self.mux_configuration_vm.configs)
            self.mux_configuration_vm.configuration_changed.connect(consumer.set_mux_configuration)

        self.data_vm.dataframe_replaced.connect(self.filter_vm.set_history_dataframe)
        self.data_vm.dataframe_changed.connect(self.filter_vm.update_history_source)
        self.data_vm.rows_appended.connect(self.filter_vm.append_history_rows)
        # Candidate Interpretations is wired to dataframe_changed lazily by its
        # own window manager (connect on open, disconnect on close) instead of
        # unconditionally here -- see CandidateInterpretationsWindowManager.
        # Mux Detection is disabled entirely (not wired, no menu entry) until
        # explicitly re-enabled; see CLAUDE.md.
        self.data_vm.dataframe_replaced.connect(self.signal_coverage_vm.reset_dataframe)
        self.data_vm.dataframe_changed.connect(self.signal_coverage_vm.set_dataframe)
        self.data_vm.dataframe_replaced.connect(self.range_diff_vm.reset_dataframe)
        self.data_vm.dataframe_changed.connect(self.range_diff_vm.set_dataframe)
        self.filter_vm.dataframe_changed.connect(self.table_vm.set_dataframe)
        self.filter_vm.rows_appended.connect(self.table_vm.append_rows)
        self.connection_vm.chunk_ready.connect(self.data_vm.append_df)
        self.connection_vm.chunk_ready.connect(self.measurement_status_vm.ingest_chunk)
        self.connection_vm.chunk_ready.connect(self.bus_statistics_vm.ingest_chunk)
        self.connection_vm.chunk_ready.connect(self.range_diff_vm.ingest_live_chunk)
        self.connection_vm.chunk_ready.connect(self.real_time_analysis_vm.ingest_df)
        self.connection_vm.chunk_ready.connect(self.signal_coverage_vm.ingest_df)
        self.connection_vm.chunk_ready.connect(
            self.continuous_recorder_vm.append_chunk, Qt.ConnectionType.DirectConnection
        )
        self.mcp_session_vm = McpSessionViewModel(
            self,
            endpoint_path=mcp_session_endpoint_path,
            enabled=enable_mcp_session,
            action_handler=self.handle_mcp_session_action,
        )
        self.data_vm.dataframe_replaced.connect(self._replace_mcp_session_dataframe)
        self.data_vm.rows_appended.connect(self._append_mcp_session_rows)
        self.data_vm.unsaved_capture_changed.connect(self.mcp_session_vm.snapshot.set_unsaved_capture)
        self.connection_vm.running_changed.connect(self._update_mcp_session_connection)
        self.analysis_context_vm.context_changed.connect(self.mcp_session_vm.snapshot.set_analysis_context)
        self.connection_vm.running_changed.connect(self._on_connection_running_changed)
        self.connection_vm.running_changed.connect(self.measurement_status_vm.set_connection_running)
        self.connection_vm.running_changed.connect(self.bus_statistics_vm.set_connection_running)
        self.data_vm.rows_appended.connect(self.measurement_status_vm.append_rows)
        self.data_vm.dataframe_replaced.connect(self.measurement_status_vm.replace_data)
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
        self.bus_statistics_vm.reset()
        self.real_time_analysis_vm.clear()
        self.log_cleared.emit()

    def shutdown(self) -> None:
        self.mcp_session_vm.shutdown()
        self.connection_vm.stop_and_drain()
        self.continuous_recorder_vm.stop_and_drain()
        self.measurement_status_vm.shutdown()
        self.bus_statistics_vm.shutdown()
        self.log_export_vm.shutdown()
        self.log_load_vm.shutdown()
        self.interpret_vm.shutdown()
        self.mux_detection_vm.shutdown()
        self.signal_coverage_vm.shutdown()
        self.range_diff_vm.shutdown()
        self.can_send_vm.shutdown()
        self.analyze_data_vm.shutdown()
        if self._restore_thread is not None and self._restore_thread.isRunning():
            if self._restore_worker is not None:
                self._restore_worker.request_stop()
            self._restore_thread.quit()
            self._restore_thread.wait()

    def dismiss_interrupted_recording(self) -> None:
        if self.interrupted_recording is not None:
            _, marker = self.interrupted_recording
            dismiss_interrupted_recording(marker)
            self.interrupted_recording = None

    def _on_connection_running_changed(self, running: bool) -> None:
        if not running:
            self.continuous_recorder_vm.stop_and_drain()
            return
        folder = Path(str(get_option("continuous_recording_directory", "~/Canlytics/Recordings"))).expanduser()
        path = make_recording_path(folder, self.connection_vm.capture_source_label)
        self.continuous_recorder_vm.start_recording(path)

    def _replace_mcp_session_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        can_ids = ()
        if dataframe is not None and "ID" in dataframe.columns:
            can_ids = tuple(sorted(set(dataframe["ID"].to_list()), key=lambda value: int(value, 16)))
        self.mcp_session_vm.replace_dataframe(
            dataframe,
            can_ids=can_ids,
            source_paths=self.data_vm.source_paths,
            unsaved=self.data_vm.has_unsaved_capture,
            connection_running=self.connection_vm.running,
        )

    def _append_mcp_session_rows(self, delta: pl.DataFrame, _new_ids: tuple[str, ...]) -> None:
        dataframe = self.data_vm.df
        self.mcp_session_vm.append_rows(
            delta,
            can_ids=self.data_vm.can_ids,
            source_paths=self.data_vm.source_paths,
            total_frames=dataframe.height if dataframe is not None else 0,
            unsaved=self.data_vm.has_unsaved_capture,
            connection_running=self.connection_vm.running,
        )

    def _update_mcp_session_connection(self, running: bool) -> None:
        mode = "replay" if running and self.connection_vm.is_replay else "live" if running else "offline"
        self.mcp_session_vm.snapshot.set_connection_mode(mode)

    def cancel_restore_dbcs(self) -> None:
        if self._restore_worker is not None:
            self._restore_worker.request_stop()

    def start_restore_dbcs(self) -> None:
        if self._restore_thread is not None and self._restore_thread.isRunning():
            return

        saved = self.session_state.get_saved_dbcs()
        if self.session_state.working_dbc_path.exists():
            saved.append({
                "name": self._working_dbc_entry_name,
                "path": str(self.session_state.working_dbc_path),
                "active": True,
                "mode": "exact",
                "order": len(saved),
                "working": True,
            })
        if not saved:
            self.dbc_restore_finished.emit(False)
            return

        logger.info("DBC restore started (%d cached DBC(s))", len(saved))
        self.dbc_restore_started.emit()
        self._restore_worker = _DbcRestoreWorker(saved)
        self._restore_thread = QThread(self)
        self._restore_worker.moveToThread(self._restore_thread)
        self._restore_thread.started.connect(self._restore_worker.run)
        self._restore_worker.finished.connect(self._on_restore_finished)
        self._restore_worker.failed.connect(self._on_restore_failed)
        self._restore_worker.progress.connect(self.dbc_restore_progress)
        self._restore_worker.finished.connect(self._restore_thread.quit)
        self._restore_worker.failed.connect(self._restore_thread.quit)
        self._restore_thread.finished.connect(self._cleanup_restore_worker)
        self._restore_thread.start()

    def _apply_loaded_df(self, path, df, is_full_load: bool, source_tz_offset_minutes=None) -> None:
        if is_full_load:
            self.bus_statistics_vm.seed_dataframe(df)
            self.data_vm.replace_log(path, df, source_tz_offset_minutes=source_tz_offset_minutes)
        else:
            self.bus_statistics_vm.ingest_chunk(df)
            self.data_vm.append_df(df, unsaved=False)

    def _apply_normalize(self, normalize: bool) -> None:
        self.data_vm.set_normalize(normalize)
        self.bus_statistics_vm.seed_dataframe(self.data_vm.df)
        self.normalize_applied.emit(normalize)

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = tz
        self.timezone_changed.emit(tz)

    def _sync_session_state(self) -> None:
        self.session_state.sync_dbc_manager(self.dbc_manager)

    def save_working_dbc(self) -> Path:
        """Persist the working DBC and refresh decode caches."""
        canonical_key = os.path.normcase(str(self.session_state.working_dbc_path.resolve()))
        for entry in self.dbc_manager.list_entries():
            entry_key = os.path.normcase(str(Path(entry.path).expanduser().resolve()))
            if entry.name != self._working_dbc_entry_name and entry_key == canonical_key:
                self.dbc_manager.remove_entry(entry.name)
        if not any(
            entry.name == self._working_dbc_entry_name for entry in self.dbc_manager.list_entries()
        ):
            self.dbc_manager.add_loaded_db(
                str(self.session_state.working_dbc_path),
                self.working_dbc.database_copy(),
                preferred_name=self._working_dbc_entry_name,
                active=True,
                mode="exact",
            )
        output = self.working_dbc.export(self.session_state.working_dbc_path)
        self.dbc_manager.update_entry_database(
            self._working_dbc_entry_name,
            self.working_dbc.database_copy(),
        )
        if self.working_dbc.list_messages():
            other_names = [
                entry.name for entry in self.dbc_manager.list_entries()
                if entry.name != self._working_dbc_entry_name
            ]
            self.dbc_manager.set_order([self._working_dbc_entry_name, *other_names])
        return output

    def list_working_messages(self) -> list[Message]:
        """Return an isolated snapshot of the editable DBC messages."""
        return sorted(self.working_dbc.database_copy().messages, key=lambda message: message.frame_id)

    def _mutate_working_dbc(self, mutation: Callable[[], object]) -> Path:
        previous = self.working_dbc.database_copy()
        try:
            mutation()
            return self.save_working_dbc()
        except Exception:
            self.working_dbc = WorkingDbc(previous)
            if any(
                entry.name == self._working_dbc_entry_name
                for entry in self.dbc_manager.list_entries()
            ):
                self.dbc_manager.update_entry_database(self._working_dbc_entry_name, previous)
            raise

    def edit_working_message(self, frame_id: int, **changes: object) -> Path:
        """Edit a message and persist the working DBC."""
        return self._mutate_working_dbc(lambda: self.working_dbc.update_message(frame_id, **changes))

    def add_working_message(
        self, name: str, frame_id: int, length: int = 8, is_extended_frame: bool | None = None,
    ) -> Path:
        """Add a message and persist the working DBC."""
        return self._mutate_working_dbc(lambda: self.working_dbc.create_message(
            name, frame_id, length=length, is_extended_frame=is_extended_frame,
        ))

    def delete_working_message(self, frame_id: int) -> Path:
        """Delete a message and persist the working DBC."""
        return self._mutate_working_dbc(lambda: self.working_dbc.delete_message(frame_id))

    def add_working_signal(self, frame_id: int, name: str, **changes: object) -> Path:
        """Add a signal and persist the working DBC."""
        return self._mutate_working_dbc(lambda: self.working_dbc.create_signal(frame_id, name, **changes))

    def edit_working_signal(self, frame_id: int, name: str, **changes: object) -> Path:
        """Edit a signal and persist the working DBC."""
        return self._mutate_working_dbc(
            lambda: self.working_dbc.update_signal(frame_id, name, **changes)
        )

    def delete_working_signal(self, frame_id: int, name: str) -> Path:
        """Delete a signal and persist the working DBC."""
        return self._mutate_working_dbc(lambda: self.working_dbc.delete_signal(frame_id, name))

    def export_working_dbc(self, path: str | Path) -> Path:
        """Export a copy of the working DBC without changing its canonical path."""
        output_key = os.path.normcase(str(Path(path).expanduser().resolve()))
        protected_paths = [self.session_state.working_dbc_path]
        protected_paths.extend(
            Path(entry.path) for entry in self.dbc_manager.list_entries()
            if entry.name != self._working_dbc_entry_name
        )
        if any(os.path.normcase(str(source.expanduser().resolve())) == output_key for source in protected_paths):
            raise ValueError(get_text("working_dbc_source_protected"))
        return self.working_dbc.export(path)

    def handle_mcp_session_action(self, method: str, params: dict) -> dict:
        """Run bounded DBC operations requested by an authenticated MCP client."""
        if method == "decode_with_dbc":
            can_id = str(params.get("can_id") or "").strip().upper().removeprefix("0X")
            data_hex = str(params.get("data_hex") or "").strip()
            if not can_id or not data_hex:
                raise ValueError("can_id and data_hex are required")
            try:
                frame_id = int(can_id, 16)
                payload = bytes.fromhex(data_hex)
            except ValueError as exc:
                raise ValueError("can_id or data_hex is invalid") from exc
            if not 0 <= frame_id <= 0x1FFFFFFF:
                raise ValueError("can_id must fit a 29-bit CAN identifier")
            if len(payload) > 8:
                raise ValueError("decode_with_dbc accepts classic CAN payloads up to 8 bytes")
            resolved = self.dbc_manager.resolve_message(can_id)
            if resolved is None:
                return {"can_id": can_id, "matched": False, "message_name": None, "signals": []}
            if resolved[1].length > 8:
                raise ValueError("decode_with_dbc does not reassemble J1939 BAM payloads")
            signals = self.dbc_manager.decode_frame(can_id, data_hex)
            return {
                "can_id": can_id,
                "matched": True,
                "message_name": resolved[1].name,
                "signals": signals,
            }
        if method != "save_signal_to_working_dbc":
            raise ValueError(f"Unknown MCP session action: {method}")
        return self.save_working_signal(params)

    def working_signal_dialog_defaults(self, can_id: str) -> dict:
        """Return editable message metadata for the signal dialog."""
        normalized_id = str(can_id or "").strip().upper().removeprefix("0X")
        try:
            frame_id = int(normalized_id, 16)
        except ValueError:
            return {
                "message_name": "", "message_length": 8, "multiplexer_signals": [],
                "existing_message": False, "working_message": False,
            }
        working_message = True
        try:
            message = self.working_dbc.get_message(frame_id)
        except KeyError:
            working_message = False
            resolved = self.dbc_manager.resolve_message(normalized_id)
            message = resolved[1] if resolved is not None else None
        if message is None:
            return {
                "message_name": f"ID_{frame_id:X}",
                "message_length": 8,
                "multiplexer_signals": [],
                "existing_message": False,
                "working_message": False,
            }
        message_name = message.name
        if not working_message:
            existing_names = {item.name for item in self.working_dbc.list_messages()}
            if message_name in existing_names:
                base_name = message_name
                suffix = 2
                while f"{base_name}_{suffix}" in existing_names:
                    suffix += 1
                message_name = f"{base_name}_{suffix}"
        return {
            "message_name": message_name,
            "message_length": message.length,
            "multiplexer_signals": [signal.name for signal in message.signals if signal.is_multiplexer],
            "existing_message": True,
            "working_message": working_message,
        }

    def save_working_signal(self, params: dict) -> dict:
        """Validate, persist, and register one signal in Working DBC."""
        can_id = str(params.get("can_id") or "").strip().upper().removeprefix("0X")
        try:
            frame_id = int(can_id, 16)
        except ValueError as exc:
            raise ValueError("can_id must be hexadecimal") from exc
        if not 0 <= frame_id <= 0x1FFFFFFF:
            raise ValueError("can_id must fit a 29-bit CAN identifier")
        requested_message_length = params.get("message_length")
        if requested_message_length is not None:
            try:
                requested_message_length = int(requested_message_length)
            except (TypeError, ValueError) as exc:
                raise ValueError("message_length must be an integer") from exc
        message = None
        created_message = False
        message_in_working = False
        copied_source_name = None
        try:
            message = self.working_dbc.get_message(frame_id)
            message_in_working = True
        except KeyError:
            resolved = self.dbc_manager.resolve_message(can_id)
            if resolved is not None and resolved[0].name != self._working_dbc_entry_name:
                copied_source_name = resolved[1].name
                message = self.working_dbc.copy_message(resolved[1], frame_id=frame_id)
                created_message = True
            else:
                message_name = str(params.get("message_name") or f"ID_{frame_id:X}")
                message_length = requested_message_length or 8
                message = self.working_dbc.create_message(
                    message_name,
                    frame_id,
                    length=message_length,
                    is_extended_frame=frame_id > 0x7FF,
                )
                created_message = True
        try:
            requested_name = str(params.get("message_name") or "").strip()
            if message_in_working and requested_name and requested_name != message.name:
                raise ValueError("message_name does not match the existing CAN ID")
            if copied_source_name is not None and requested_name and requested_name != copied_source_name:
                message = self.working_dbc.update_message(frame_id, name=requested_name)
            if requested_message_length is not None and requested_message_length != message.length:
                raise ValueError("message_length does not match the existing CAN ID")
        except Exception:
            if created_message:
                self.working_dbc.delete_message(frame_id)
            raise
        signal_name = str(params.get("signal_name") or "").strip()
        signal = None
        try:
            signal = self.working_dbc.create_signal(
                frame_id,
                signal_name,
                start=params.get("start"),
                length=params.get("length"),
                byte_order=params.get("byte_order", "little_endian"),
                is_signed=params.get("is_signed", False),
                scale=params.get("scale", 1.0),
                offset=params.get("offset", 0.0),
                unit=params.get("unit"),
                minimum=params.get("minimum"),
                maximum=params.get("maximum"),
                comment=params.get("comment"),
                is_float=params.get("is_float", False),
                is_multiplexer=params.get("is_multiplexer", False),
                multiplexer_signal=params.get("multiplexer_signal"),
                multiplexer_ids=params.get("multiplexer_ids"),
            )
            output = self.save_working_dbc()
        except Exception:
            if signal is not None:
                self.working_dbc.delete_signal(frame_id, signal.name)
            if created_message:
                self.working_dbc.delete_message(frame_id)
            raise
        return {
            "can_id": f"{frame_id:X}",
            "message_name": message.name,
            "signal_name": signal.name,
            "start": signal.start,
            "length": signal.length,
            "path": str(output),
            "active": True,
        }

    def _on_restore_finished(self, payload: list[dict]) -> None:
        restored_names: list[str] = []
        active_names: set[str] = set()
        working_restored = False
        for item in payload:
            if item.get("working"):
                self.working_dbc = WorkingDbc(item["db"])
                self.dbc_manager.update_entry_database(
                    self._working_dbc_entry_name,
                    self.working_dbc.database_copy(),
                )
                working_restored = True
                continue
            try:
                entry = self.dbc_manager.add_loaded_db(
                    item["path"],
                    item["db"],
                    preferred_name=item.get("name"),
                    active=bool(item.get("active", True)),
                    mode=str(item.get("mode") or "exact"),
                )
            except Exception:
                logger.exception("Failed to apply restored DBC %s", item.get("path"))
                continue
            restored_names.append(entry.name)
            if entry.active:
                active_names.add(entry.name)

        if restored_names or working_restored:
            restored_names = [name for name in restored_names if name != self._working_dbc_entry_name]
            if self.working_dbc.list_messages():
                restored_names.insert(0, self._working_dbc_entry_name)
            else:
                restored_names.append(self._working_dbc_entry_name)
            active_names.add(self._working_dbc_entry_name)
            self.dbc_manager.set_order(restored_names)
            self.dbc_manager.set_active(active_names)
        logger.info("DBC restore finished (%d of %d restored)", len(restored_names), len(payload))
        self.dbc_restore_finished.emit(bool(restored_names or working_restored))

    def _on_restore_failed(self, message: str) -> None:
        logger.warning("DBC restore failed: %s", message)
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
    progress = QtSignal(int, int)

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
            ordered = sorted(self._saved, key=lambda row: int(row.get("order", 0)))
            total = len(ordered)
            for done, item in enumerate(ordered, start=1):
                if self._stop_requested:
                    break
                stored_path = str(item.get("path") or "").strip()
                if not stored_path:
                    self.progress.emit(done, total)
                    continue
                try:
                    db = loader.load_database(stored_path)
                except Exception:
                    self.progress.emit(done, total)
                    continue
                payload.append(
                    {
                        "name": str(item.get("name") or ""),
                        "path": stored_path,
                        "active": bool(item.get("active", True)),
                        "mode": str(item.get("mode") or "exact"),
                        "db": db,
                        "working": bool(item.get("working", False)),
                    }
                )
                self.progress.emit(done, total)
            self.finished.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))
