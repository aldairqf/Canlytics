from __future__ import annotations

import dataclasses
import time
import uuid
from dataclasses import dataclass
from math import nextafter

from PySide6.QtCore import QObject, QTimer, Signal as QtSignal

from config.app_config import get_option, get_text
from models.analysis_context import AnalysisContext, AnalysisMarker

from services.active_re import (
    SignalGeometry, generate_signal_ramp, resolve_dbc_signal, select_replay_subset,
)


@dataclass
class _Observation:
    t0: float
    duration: float
    can_id: str
    started: float
    total_seconds: float
    t1: float | None = None


class ActiveReViewModel(QObject):
    """Coordinates filtered replay, DBC/manual ramps, and CAN Send dispatch."""

    subset_ready = QtSignal(object)
    error = QtSignal(str)
    status_changed = QtSignal(str)
    observation_finished = QtSignal(float, float, float)
    can_observe_changed = QtSignal(bool)
    activity_changed = QtSignal()

    def __init__(self, data_vm, connection_vm, can_send_vm, dbc_manager, parent=None):
        super().__init__(parent)
        self._data_vm, self._connection_vm = data_vm, connection_vm
        self._can_send_vm, self._dbc_manager = can_send_vm, dbc_manager
        self._observe_timer = self._timer(single_shot=True, slot=self._begin_close)
        self._flush_timer = self._timer(single_shot=True, slot=self._finalize_observation)
        self._progress_timer = self._timer(interval=int(get_option("active_re_progress_interval_ms", 200)),
                                           slot=self._update_observation_progress)
        self._ramp_timer = self._timer(slot=self._tick_ramp)
        self._replay_timer = self._timer(interval=int(get_option("active_re_replay_poll_ms", 25)),
                                         slot=self._poll_replay)
        self._diff_timer = self._timer(interval=int(get_option("active_re_replay_poll_ms", 25)),
                                       slot=self._poll_diff)
        self._observation: _Observation | None = None
        self._last_ts: float | None = None
        self._ramp_frames: tuple = ()
        self._ramp_index = 0
        self._ramp_on_done = None
        self._pending_replay: tuple[dict, int, float] | None = None
        self._pending_diff = None
        self._diff_vm = self._diff_manager = self._event_markers_vm = self._context_vm = None
        connection_vm.chunk_ready.connect(self.ingest_chunk)
        connection_vm.running_changed.connect(self._on_running_changed)
        can_send_vm.send_enabled_changed.connect(self._on_send_enabled_changed)
        data_vm.dataframe_changed.connect(self._on_dataframe_changed)

    def _timer(self, *, single_shot: bool = False, interval: int | None = None, slot=None) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(single_shot)
        if interval is not None:
            timer.setInterval(interval)
        if slot is not None:
            timer.timeout.connect(slot)
        return timer

    @property
    def replay_available(self) -> bool:
        return self._connection_vm.is_replay

    @property
    def can_observe(self) -> bool:
        return bool(self._can_send_vm.send_enabled)

    @property
    def observing(self) -> bool:
        return self._observation is not None

    @property
    def ramp_active(self) -> bool:
        return bool(self._ramp_frames)

    def configure_observation(self, *, diff_vm, diff_manager, event_markers_vm, context_vm) -> None:
        self._diff_vm, self._diff_manager = diff_vm, diff_manager
        self._event_markers_vm, self._context_vm = event_markers_vm, context_vm

    def shutdown(self) -> None:
        """Stop every timer and drop any pending ramp, observation, replay, or diff work."""
        self._abort_activity()
        self._replay_timer.stop()
        self._diff_timer.stop()
        self._pending_replay = None
        self._pending_diff = None

    def ingest_chunk(self, chunk) -> None:
        """Track the stream timestamp of the latest received frame."""
        if chunk is None or chunk.is_empty() or "TS" not in chunk.columns:
            return
        self._last_ts = float(chunk["TS"].max())

    def _on_running_changed(self, running: bool) -> None:
        if running:
            self._last_ts = None
            return
        if self.observing or self.ramp_active:
            self._abort_activity(get_text("active_re_error_connection_lost"), error=True)
        self._poll_replay()

    def _on_send_enabled_changed(self, enabled: bool) -> None:
        self.can_observe_changed.emit(bool(enabled))
        if not enabled and (self.observing or self.ramp_active):
            self._abort_activity(get_text("active_re_error_connection_lost"), error=True)

    def _on_dataframe_changed(self, *_args) -> None:
        observation = self._observation
        if observation is not None and observation.t1 is not None and self._df_reaches(observation.t1):
            self._finalize_observation()

    def _df_reaches(self, timestamp: float) -> bool:
        df = self._data_vm.df
        return df is not None and not df.is_empty() and float(df["TS"][-1]) >= timestamp

    def _period_ms(self, period_ms) -> int:
        value = get_option("active_re_ramp_period_ms", 100) if period_ms is None else period_ms
        return max(0, int(value))

    def start_observation(self, frames, can_id: str, duration: float | None = None,
                          period_ms: int | None = None) -> bool:
        if not self.can_observe or not frames or self._observation is not None or self.ramp_active:
            return False
        t0 = self._last_ts
        if t0 is None:
            self.error.emit(get_text("active_re_error_no_frames"))
            return False
        duration = float(duration if duration is not None else get_option("active_re_observation_window_seconds"))
        period = self._period_ms(period_ms)
        first_id = getattr(frames[0], "can_id", None)
        observed_id = f"{first_id:X}" if isinstance(first_id, int) else str(can_id)
        total = max(0, len(frames) - 1) * period / 1000.0 + duration
        self._observation = _Observation(t0, duration, observed_id, time.monotonic(), total)
        self._progress_timer.start()
        self.activity_changed.emit()
        self._emit_observing_status()
        self.send_ramp(frames, period_ms=period, on_done=self._on_observation_ramp_sent)
        return self._observation is not None

    def cancel_observation(self) -> None:
        if self._observation is None and not self.ramp_active:
            return
        self._abort_activity(get_text("active_re_status_canceled"))

    def _abort_activity(self, message: str = "", *, error: bool = False) -> None:
        had_activity = self._observation is not None or self.ramp_active
        for timer in (self._observe_timer, self._flush_timer, self._progress_timer, self._ramp_timer):
            timer.stop()
        self._ramp_frames, self._ramp_index, self._ramp_on_done = (), 0, None
        self._observation = None
        if had_activity:
            self.activity_changed.emit()
            if message:
                (self.error if error else self.status_changed).emit(message)

    def _on_observation_ramp_sent(self) -> None:
        observation = self._observation
        if observation is not None:
            self._observe_timer.start(max(1, round(observation.duration * 1000)))

    def _begin_close(self) -> None:
        observation = self._observation
        if observation is None:
            return
        self._progress_timer.stop()
        t1 = self._last_ts
        if t1 is None or t1 <= observation.t0:
            self._abort_activity(get_text("active_re_error_no_response"), error=True)
            return
        observation.t1 = t1
        if self._df_reaches(t1):
            self._finalize_observation()
        else:
            self._flush_timer.start(int(get_option("active_re_flush_timeout_ms", 500)))

    def _finalize_observation(self) -> None:
        observation = self._observation
        if observation is None or observation.t1 is None:
            return
        self._flush_timer.stop()
        self._observation = None
        self.activity_changed.emit()
        t0, t1, duration = observation.t0, observation.t1, observation.duration
        marker = AnalysisMarker(sequence=1, name=get_text("active_re_marker_name"), timestamp=t0)
        if self._event_markers_vm is not None:
            try:
                marker = self._event_markers_vm.add_marker(get_text("active_re_marker_name"), "ON", t0)
            except ValueError:
                pass
        if self._diff_vm is not None:
            payload = (t0, t1, duration, observation.can_id, marker)
            if self._diff_vm.running:
                self._pending_diff = payload
                self._diff_timer.start()
                self.status_changed.emit(get_text("active_re_status_diff_queued"))
                return
            self._apply_diff(payload)
        self.status_changed.emit(get_text("active_re_status_done"))

    def _poll_diff(self) -> None:
        if self._pending_diff is None:
            self._diff_timer.stop()
        elif not self._diff_vm.running:
            self._diff_timer.stop()
            payload, self._pending_diff = self._pending_diff, None
            self._apply_diff(payload)
            self.status_changed.emit(get_text("active_re_status_done"))

    def _apply_diff(self, payload) -> None:
        t0, t1, duration, can_id, marker = payload
        diff = self._diff_vm
        if diff.source_comparison:
            diff.clear_source_comparison()
        diff.set_dataframe(self._data_vm.df)
        diff.set_range_a(t0 - duration, nextafter(t0, float("-inf")))
        diff.set_range_b(t0, t1)
        if self._context_vm is not None:
            self._context_vm.set_context(AnalysisContext(
                can_id=can_id, range_a=(t0 - duration, t0), range_b=(t0, t1),
                markers=(marker,), source_window=get_text("active_re_title")))
        self._diff_manager.open_window()
        diff.run()
        self.observation_finished.emit(t0, t0 - duration, t1)

    def _emit_observing_status(self) -> None:
        observation = self._observation
        if observation is None:
            return
        elapsed = max(0.0, time.monotonic() - observation.started)
        total = max(observation.total_seconds, 1e-9)
        self.status_changed.emit(get_text("active_re_status_observing").format(
            percent=min(99, round(100 * elapsed / total)), eta=max(0.0, total - elapsed)))

    def _update_observation_progress(self) -> None:
        if self._observation is None:
            self._progress_timer.stop()
            return
        if not self.ramp_active:
            self._emit_observing_status()

    def filtered_replay(self, can_ids=None, time_range=None, markers=None):
        try:
            subset = select_replay_subset(self._data_vm.df, can_ids=can_ids, time_range=time_range, markers=markers)
            self.subset_ready.emit(subset)
            path = self._connection_vm.source_path if self._connection_vm.is_replay else (
                self._data_vm.source_paths[0] if self._data_vm.source_paths else None)
            if not path:
                self.status_changed.emit(get_text("active_re_status_selected").format(count=subset.height))
                return subset
            kwargs = {"path": path, "speed": 1.0, "can_ids": can_ids, "time_range": time_range,
                      "markers": markers, "relative_time": bool(self._data_vm.normalize)}
            timeout = int(get_option("active_re_replay_start_timeout_ms", 2000)) / 1000.0
            self._pending_replay = (kwargs, subset.height, time.monotonic() + timeout)
            if self._connection_vm.running:
                self.status_changed.emit(get_text("active_re_status_stopping"))
                self._connection_vm.stop()
                self._replay_timer.start()
            else:
                self._poll_replay()
            return subset
        except Exception as exc:
            self.error.emit(str(exc))
            return None

    def _poll_replay(self) -> None:
        pending = self._pending_replay
        if pending is None:
            self._replay_timer.stop()
            return
        kwargs, count, deadline = pending
        if not self._connection_vm.running:
            self._connection_vm.start_replay(**kwargs)
            if self._connection_vm.running:
                self._pending_replay = None
                self._replay_timer.stop()
                self.status_changed.emit(get_text("active_re_status_replaying").format(count=count))
                return
        if time.monotonic() >= deadline:
            self._pending_replay = None
            self._replay_timer.stop()
            self.error.emit(get_text("active_re_error_replay_start"))
        elif not self._replay_timer.isActive():
            self._replay_timer.start()

    def generate_ramp(self, *, can_id, base_data, start, stop, step, scale=1.0, offset=0.0,
                      start_bit=None, length=None, little_endian=True, dbc_signal=None,
                      signed=False, is_float=False, extended=False):
        try:
            mux = None
            if dbc_signal is not None:
                spec = resolve_dbc_signal(
                    self._dbc_manager, *dbc_signal,
                    priority=int(get_option("active_re_j1939_priority", 6)),
                    source_address=int(get_option("active_re_j1939_source_address", 254)))
                can_id, base_data, geometry, mux = spec.can_id, spec.base_data, spec.geometry, spec.mux
                scale, offset, extended = spec.scale, spec.offset, spec.extended
            else:
                geometry = SignalGeometry(int(start_bit), int(length), bool(little_endian),
                                          signed=bool(signed), is_float=bool(is_float))
                extended = bool(extended) or int(str(can_id).strip().lower().removeprefix("0x"), 16) > 0x7FF
            return generate_signal_ramp(
                can_id=can_id, base_data=base_data, geometry=geometry, mux=mux, extended=extended,
                start=float(start), stop=float(stop), step=float(step), scale=float(scale), offset=float(offset))
        except Exception as exc:
            self.error.emit(str(exc))
            return ()

    def send_ramp(self, frames, period_ms: int | None = None, on_done=None) -> bool:
        """Send frames through CAN Send one per period; the first goes out immediately."""
        if not frames or self.ramp_active:
            return False
        period = self._period_ms(period_ms)
        run_id = uuid.uuid4().hex[:8]
        self._ramp_frames = tuple(self._with_run_id(frame, run_id, index) for index, frame in enumerate(frames))
        self._ramp_index, self._ramp_on_done = 0, on_done
        self.activity_changed.emit()
        self._tick_ramp()
        if self.ramp_active:
            if period > 0:
                self._ramp_timer.start(period)
            else:
                while self.ramp_active:
                    self._tick_ramp()
        return True

    @staticmethod
    def _with_run_id(frame, run_id: str, index: int):
        if dataclasses.is_dataclass(frame) and hasattr(frame, "entry_id"):
            return dataclasses.replace(frame, entry_id=f"active-re:{run_id}:{index}")
        return frame

    def _tick_ramp(self) -> None:
        if not self._ramp_frames:
            self._ramp_timer.stop()
            return
        if not self._can_send_vm.send_enabled:
            self._abort_activity(get_text("active_re_error_connection_lost"), error=True)
            return
        total = len(self._ramp_frames)
        self._can_send_vm.send_generated_frames((self._ramp_frames[self._ramp_index],),
                                                label=get_text("active_re_tx_label"))
        self._ramp_index += 1
        if self._ramp_index < total:
            self.status_changed.emit(get_text("active_re_status_ramp").format(sent=self._ramp_index, total=total))
            return
        self._ramp_timer.stop()
        done, self._ramp_on_done = self._ramp_on_done, None
        self._ramp_frames, self._ramp_index = (), 0
        self.activity_changed.emit()
        self.status_changed.emit(get_text("active_re_status_ramp_done").format(total=total))
        if done is not None:
            done()
