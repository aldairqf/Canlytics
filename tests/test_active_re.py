from __future__ import annotations

import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cantools
import polars as pl
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from config.app_config import get_option
from models.analysis_context import AnalysisMarker
from services.active_re import (
    MuxSelector, SignalGeometry, generate_signal_ramp, normalize_can_ids, ramp_values, resolve_dbc_signal,
    select_replay_subset,
)
from services.can_send import ResolvedFrame
from services.can_sources import ReplayCanSource
from services.dbc_manager import DbcManager
from viewmodels.active_re_viewmodel import ActiveReViewModel
from viewmodels.range_diff_viewmodel import RangeDiffViewModel
from views.active_re_window import ActiveReWindow

EXT_DBC_ID = 0x98FEF100
J1939_DBC_ID = 0x8CF00400

DBC_TEXT = f'''VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 Std: 8 ECU
 SG_ Be12 : 7|12@0+ (1,0) [0|4095] "" Vector__XXX
 SG_ Sgn : 16|8@1- (1,0) [-128|127] "" Vector__XXX
 SG_ Flt : 32|32@1- (1,0) [0|0] "" Vector__XXX

BO_ 300 MuxMsg: 8 ECU
 SG_ Sel M : 0|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ Val m5 : 8|8@1+ (1,0) [0|255] "" Vector__XXX

BO_ {EXT_DBC_ID} Ext: 8 ECU
 SG_ Speed : 0|16@1+ (1,0) [0|65535] "" Vector__XXX

BO_ {J1939_DBC_ID} Pgn: 8 ECU
 SG_ Rpm : 0|16@1+ (1,0) [0|65535] "" Vector__XXX

SIG_VALTYPE_ 256 Flt : 1;
'''


def _dbc_manager(mode: str = "exact") -> tuple[DbcManager, cantools.database.Database]:
    db = cantools.database.load_string(DBC_TEXT, database_format="dbc")
    manager = DbcManager()
    manager.add_loaded_db("virtual.dbc", db, preferred_name="Test", mode=mode)
    return manager, db


class ActiveReplayTests(unittest.TestCase):
    def setUp(self):
        self.frames = pl.DataFrame({"TS": [1.0, 2.0, 3.0, 4.0], "ID": ["100", "101", "100", "100"],
                                    "DATA": ["0000", "0000", "0000", "0000"], "LEN": [2, 2, 2, 2]})

    def test_selects_id_and_inclusive_time_range(self):
        result = select_replay_subset(self.frames, can_ids={"100"}, time_range=(2.0, 4.0))
        self.assertEqual(result["TS"].to_list(), [3.0, 4.0])

    def test_markers_define_inclusive_time_range(self):
        result = select_replay_subset(self.frames, markers=(2.0, 3.0))
        self.assertEqual(result["TS"].to_list(), [2.0, 3.0])

    def test_time_filter_is_optional(self):
        self.assertEqual(select_replay_subset(self.frames).height, 4)
        self.assertEqual(select_replay_subset(self.frames, can_ids=["100"]).height, 3)

    def test_time_origin_shifts_relative_bounds(self):
        result = select_replay_subset(self.frames, time_range=(1.0, 2.0), time_origin=1.0)
        self.assertEqual(result["TS"].to_list(), [2.0, 3.0])

    def test_id_matching_ignores_leading_zeros_and_prefix(self):
        df = pl.DataFrame({"TS": [1.0, 2.0, 3.0], "ID": ["0CF00300", "0xCF00400", "100"]})
        for requested in ("CF00300", "0CF00300", "0xCF00300", 0xCF00300):
            self.assertEqual(select_replay_subset(df, can_ids=[requested])["TS"].to_list(), [1.0], requested)
        self.assertEqual(select_replay_subset(df, can_ids=["cf00400"])["TS"].to_list(), [2.0])
        self.assertEqual(normalize_can_ids(["0x10", 16, "010"]), {16})


class ReplaySourceFilterTests(unittest.TestCase):
    LOG = ("(100.0) can0 123#01\n(101.0) can0 124#02\n"
           "(101.5) can0  20000004   [8]  00 04 00 00 00 00 00 00   ERRORFRAME  \n"
           "(102.0) can0 123#03\n(103.0) can0 124#04\n")

    def _source(self, content: str, **config):
        handle = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
        handle.write(content)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        source = ReplayCanSource({"path": handle.name, "speed": 1000.0, **config}, sleep=lambda _s: None)
        source.open(canceled=lambda: False, status=lambda _m: None)
        return source

    @staticmethod
    def _drain(source) -> list:
        frames = []
        for _ in range(100):
            if source.finished:
                break
            frame = source.receive(0.01)
            if frame is not None:
                frames.append(frame)
        return frames

    def test_filtered_replay_opens_without_unbound_import_and_filters_once(self):
        frames = self._drain(self._source(self.LOG, can_ids=["123"]))
        self.assertEqual([f.timestamp for f in frames if not f.is_error], [100.0, 102.0])

    def test_error_frames_follow_the_same_id_and_time_filter(self):
        self.assertEqual(len([f for f in self._drain(self._source(self.LOG)) if f.is_error]), 1)
        self.assertFalse([f for f in self._drain(self._source(self.LOG, can_ids=["123"])) if f.is_error])
        frames = self._drain(self._source(self.LOG, time_range=(101.0, 102.0)))
        self.assertEqual(len([f for f in frames if f.is_error]), 1)
        frames = self._drain(self._source(self.LOG, time_range=(102.5, 103.5)))
        self.assertFalse([f for f in frames if f.is_error])

    def test_relative_time_range_uses_first_frame_as_origin(self):
        frames = self._drain(self._source(self.LOG, time_range=(1.0, 2.0), relative_time=True))
        self.assertEqual([f.timestamp for f in frames if not f.is_error], [101.0, 102.0])

    def test_id_filter_matches_leading_zero_ids(self):
        source = self._source("(1.0) can0 0CF00300#01\n(2.0) can0 123#02\n", can_ids=["CF00300"])
        self.assertEqual([f.can_id for f in self._drain(source)], [0xCF00300])


class RampTests(unittest.TestCase):
    def test_ramp_encodes_scaled_little_endian_values(self):
        frames = generate_signal_ramp(can_id="100", base_data=b"\x00\x00", geometry=SignalGeometry(0, 8),
                                      start=3, stop=7, step=2, scale=2, offset=1)
        self.assertEqual([frame.data for frame in frames], [b"\x01\x00", b"\x02\x00", b"\x03\x00"])

    def test_ramp_encodes_big_endian_signal_like_cantools(self):
        frames = generate_signal_ramp(can_id="100", base_data=bytes(8), geometry=SignalGeometry(7, 12, False),
                                      start=0x123, stop=0x123, step=1)
        self.assertEqual(frames[0].data, bytes.fromhex("1230000000000000"))
        _manager, db = _dbc_manager()
        self.assertEqual(db.get_message_by_name("Std").encode({"Be12": 0x123, "Sgn": 0, "Flt": 0.0}),
                         bytes.fromhex("1230000000000000"))

    def test_big_endian_eight_bit_signal_writes_whole_byte(self):
        frames = generate_signal_ramp(can_id="100", base_data=b"\x00\x00", geometry=SignalGeometry(7, 8, False),
                                      start=1, stop=2, step=1)
        self.assertEqual([frame.data for frame in frames], [b"\x01\x00", b"\x02\x00"])

    def test_signed_signal_uses_twos_complement_and_range(self):
        geometry = SignalGeometry(0, 8, signed=True)
        frames = generate_signal_ramp(can_id="100", base_data=b"\x00", geometry=geometry, start=-2, stop=0, step=1)
        self.assertEqual([f.data for f in frames], [b"\xFE", b"\xFF", b"\x00"])
        with self.assertRaises(ValueError):
            generate_signal_ramp(can_id="100", base_data=b"\x00", geometry=geometry, start=0, stop=128, step=128)
        generate_signal_ramp(can_id="100", base_data=b"\x00", geometry=geometry, start=-128, stop=-128, step=1)

    def test_float_signal_matches_cantools_encoding(self):
        _manager, db = _dbc_manager()
        frames = generate_signal_ramp(can_id="100", base_data=bytes(8),
                                      geometry=SignalGeometry(32, 32, signed=True, is_float=True),
                                      start=1.5, stop=1.5, step=1)
        self.assertEqual(frames[0].data, db.get_message_by_name("Std").encode({"Be12": 0, "Sgn": 0, "Flt": 1.5}))

    def test_mux_selector_is_written_with_the_ramp(self):
        mux = MuxSelector(SignalGeometry(0, 8), 5)
        frames = generate_signal_ramp(can_id="12C", base_data=bytes(8), geometry=SignalGeometry(8, 8),
                                      start=10, stop=10, step=1, mux=mux)
        _manager, db = _dbc_manager()
        self.assertEqual(frames[0].data, db.get_message_by_name("MuxMsg").encode({"Sel": 5, "Val": 10}))

    def test_ramp_values_are_indexed_and_include_stop(self):
        values = ramp_values(0.0, 1.0, 0.1)
        self.assertEqual(len(values), 11)
        self.assertEqual(values[-1], 1.0)
        self.assertAlmostEqual(values[3], 0.3)
        self.assertEqual(ramp_values(0, 10, 3), [0, 3, 6, 9, 10])
        self.assertEqual(ramp_values(5, 1, -2), [5, 3, 1])
        self.assertEqual(ramp_values(2, 2, 1), [2])

    def test_float_step_ramp_has_no_accumulated_drift(self):
        frames = generate_signal_ramp(can_id="100", base_data=b"\x00", geometry=SignalGeometry(0, 8),
                                      start=0, stop=1, step=0.1, scale=0.1)
        self.assertEqual([f.data[0] for f in frames], list(range(11)))

    def test_ramp_rejects_unrepresentable_value(self):
        with self.assertRaises(ValueError):
            generate_signal_ramp(can_id="100", base_data=b"\x00", geometry=SignalGeometry(0, 4),
                                 start=0, stop=16, step=16)

    def test_run_id_makes_entry_ids_unique(self):
        kwargs = dict(can_id="100", base_data=b"\x00", geometry=SignalGeometry(0, 8), start=0, stop=1, step=1)
        first = generate_signal_ramp(run_id="a", **kwargs)
        second = generate_signal_ramp(run_id="b", **kwargs)
        self.assertFalse({f.entry_id for f in first} & {f.entry_id for f in second})


class DbcRampSpecTests(unittest.TestCase):
    def test_signed_float_and_big_endian_types_come_from_the_dbc(self):
        manager, _db = _dbc_manager()
        sgn = resolve_dbc_signal(manager, "Test", "Std", "Sgn")
        self.assertTrue(sgn.geometry.signed)
        self.assertFalse(sgn.extended)
        self.assertTrue(resolve_dbc_signal(manager, "Test", "Std", "Flt").geometry.is_float)
        self.assertFalse(resolve_dbc_signal(manager, "Test", "Std", "Be12").geometry.little_endian)

    def test_mux_value_is_resolved(self):
        manager, _db = _dbc_manager()
        spec = resolve_dbc_signal(manager, "Test", "MuxMsg", "Val")
        self.assertEqual((spec.mux.value, spec.mux.geometry.start_bit, spec.mux.geometry.length), (5, 0, 8))

    def test_extended_dbc_message_is_flagged_extended_with_full_id(self):
        manager, _db = _dbc_manager()
        spec = resolve_dbc_signal(manager, "Test", "Ext", "Speed")
        self.assertTrue(spec.extended)
        self.assertEqual(spec.can_id, 0x18FEF100)

    def test_j1939_message_builds_full_29_bit_id_not_the_pgn(self):
        manager, _db = _dbc_manager("j1939")
        spec = resolve_dbc_signal(manager, "Test", "Pgn", "Rpm")
        self.assertTrue(spec.extended)
        self.assertEqual(spec.can_id, 0x0CF00400)


class ActiveReViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.data = Mock(df=pl.DataFrame({"TS": [1.0, 2.0], "ID": ["100", "101"]}), source_paths=(), normalize=False)
        self.connection = Mock(is_replay=False, running=False)
        self.sender = Mock(send_enabled=True)
        self.dbc = Mock()
        self.vm = ActiveReViewModel(self.data, self.connection, self.sender, self.dbc)
        self.addCleanup(self.vm.shutdown)

    @staticmethod
    def _chunk(ts: float) -> pl.DataFrame:
        return pl.DataFrame({"TS": [ts], "ID": ["100"]})

    @staticmethod
    def _wait(predicate, timeout_ms: int = 3000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while not predicate() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        return bool(predicate())

    def _start_replay_side_effect(self):
        self.connection.start_replay.side_effect = lambda **_kw: setattr(self.connection, "running", True)

    def test_filtered_replay_selects_subset_and_starts_existing_source(self):
        self.data.source_paths = ("capture.log",)
        self._start_replay_side_effect()
        result = self.vm.filtered_replay(can_ids=["100"])
        self.assertEqual(result.height, 1)
        self.connection.start_replay.assert_called_once()
        self.assertEqual(self.connection.start_replay.call_args.kwargs["can_ids"], ["100"])
        self.assertIsNone(self.connection.start_replay.call_args.kwargs["time_range"])

    def test_filtered_replay_waits_for_running_session_to_stop(self):
        self.data.source_paths = ("capture.log",)
        self.connection.running = True
        statuses, errors = [], []
        self.vm.status_changed.connect(statuses.append)
        self.vm.error.connect(errors.append)
        self._start_replay_side_effect()
        self.vm.filtered_replay(can_ids=["100"])
        self.connection.stop.assert_called_once()
        self._wait(lambda: False, 80)
        self.connection.start_replay.assert_not_called()
        self.assertFalse(any("Replaying" in s for s in statuses))
        self.connection.running = False
        self.vm._on_running_changed(False)
        self.connection.start_replay.assert_called_once()
        self.assertTrue(any("Replaying" in s for s in statuses))
        self.assertEqual(errors, [])

    def test_filtered_replay_reports_failure_instead_of_claiming_start(self):
        self.data.source_paths = ("capture.log",)
        statuses, errors = [], []
        self.vm.status_changed.connect(statuses.append)
        self.vm.error.connect(errors.append)

        def option(name, default=None):
            return 60 if name == "active_re_replay_start_timeout_ms" else get_option(name, default)

        with patch("viewmodels.active_re_viewmodel.get_option", side_effect=option):
            self.vm.filtered_replay()
        self.assertTrue(self._wait(lambda: bool(errors), 1500))
        self.assertFalse(any("Replaying" in s for s in statuses))

    def test_filtered_replay_marks_replay_time_relative_when_log_is_normalized(self):
        self.data.source_paths = ("capture.log",)
        self.data.normalize = True
        self._start_replay_side_effect()
        self.vm.filtered_replay(time_range=(0.0, 1.5))
        self.assertTrue(self.connection.start_replay.call_args.kwargs["relative_time"])

    def test_generated_ramp_routes_through_can_send_with_unique_ids_per_run(self):
        frames = self.vm.generate_ramp(can_id="100", base_data=b"\0", start=0, stop=1, step=1,
                                       start_bit=0, length=8)
        self.assertTrue(self.vm.send_ramp(frames, period_ms=0))
        self.assertTrue(self.vm.send_ramp(frames, period_ms=0))
        sent = [call.args[0][0] for call in self.sender.send_generated_frames.call_args_list]
        self.assertEqual(len(sent), 4)
        self.assertEqual(len({frame.entry_id for frame in sent}), 4)
        self.assertEqual([frame.data for frame in sent[:2]], [b"\x00", b"\x01"])

    def test_ramp_period_spaces_frames_without_blocking(self):
        frames = self.vm.generate_ramp(can_id="100", base_data=b"\0", start=0, stop=2, step=1,
                                       start_bit=0, length=8)
        self.vm.send_ramp(frames, period_ms=30)
        self.assertEqual(self.sender.send_generated_frames.call_count, 1)
        self.assertTrue(self.vm.ramp_active)
        self.assertTrue(self._wait(lambda: not self.vm.ramp_active))
        self.assertEqual(self.sender.send_generated_frames.call_count, 3)

    def test_observation_window_starts_after_last_ramp_frame(self):
        frames = tuple(ResolvedFrame(f"f{i}", 0x100, b"\0", False) for i in range(3))
        self.vm.ingest_chunk(self._chunk(10.0))
        self.vm.start_observation(frames, "100", 5.0, period_ms=40)
        self.assertTrue(self.vm.ramp_active)
        self.assertFalse(self.vm._observe_timer.isActive())
        self.assertTrue(self._wait(lambda: not self.vm.ramp_active))
        self.assertTrue(self.vm._observe_timer.isActive())

    def test_ramp_aborts_and_reports_when_sending_becomes_unavailable(self):
        errors = []
        self.vm.error.connect(errors.append)
        frames = tuple(ResolvedFrame(f"f{i}", 0x100, b"\0", False) for i in range(3))
        self.vm.send_ramp(frames, period_ms=30)
        self.sender.send_enabled = False
        self.assertTrue(self._wait(lambda: not self.vm.ramp_active))
        self.assertEqual(len(errors), 1)

    def test_observation_uses_stream_timestamps_and_runs_diff(self):
        diff, manager, markers, context = RangeDiffViewModel(None), Mock(), Mock(), Mock()
        markers.add_marker.side_effect = lambda name, state, timestamp: AnalysisMarker(
            sequence=1, name=name, timestamp=timestamp, state=state)
        self.vm.configure_observation(diff_vm=diff, diff_manager=manager, event_markers_vm=markers, context_vm=context)
        self.data.df = pl.DataFrame({
            "TS": [99.99] * 3 + [100.5] * 3, "ID": ["100"] * 6, "LEN": [1] * 6,
            "DATA": ["00", "00", "00", "01", "02", "03"],
            **{f"D{i}": ([0, 0, 0, 1, 2, 3] if i == 0 else [0] * 6) for i in range(8)},
        })
        self.vm.ingest_chunk(self._chunk(100.0))
        self.assertTrue(self.vm.start_observation((Mock(can_id="ignored"),), "100", 0.05, period_ms=0))
        self.vm.ingest_chunk(self._chunk(100.5))
        self.assertTrue(self._wait(lambda: manager.open_window.called))
        self.assertTrue(self._wait(lambda: not diff.running))
        result = diff.report.ids[0]
        self.assertEqual(result.byte_diffs[0].a.values, (0,))
        self.assertEqual(result.byte_diffs[0].b.values, (1, 2, 3))
        self.assertEqual(markers.add_marker.call_args.args[2], 100.0)
        observation_context = context.set_context.call_args.args[0]
        self.assertEqual(observation_context.range_b, (100.0, 100.5))
        self.assertEqual(observation_context.markers[0].timestamp, observation_context.range_a[1])
        self.assertLess(diff.report.range_a.end, diff.report.range_b.start)

    def test_observation_without_received_frames_is_refused(self):
        errors = []
        self.vm.error.connect(errors.append)
        self.vm.send_ramp = Mock()
        self.assertFalse(self.vm.start_observation((Mock(),), "100", 0.1))
        self.vm.send_ramp.assert_not_called()
        self.assertEqual(len(errors), 1)

    def test_observation_waits_for_a_flush_past_t1(self):
        diff, manager = Mock(running=False, source_comparison=False), Mock()
        self.vm.configure_observation(diff_vm=diff, diff_manager=manager, event_markers_vm=None, context_vm=None)
        self.data.df = pl.DataFrame({"TS": [100.0], "ID": ["100"]})
        self.vm.ingest_chunk(self._chunk(100.0))
        self.vm.start_observation((Mock(),), "100", 0.02, period_ms=0)
        self.vm.ingest_chunk(self._chunk(100.4))
        self.assertTrue(self._wait(lambda: self.vm._observation is not None and self.vm._observation.t1 is not None))
        manager.open_window.assert_not_called()
        self.data.df = pl.DataFrame({"TS": [100.0, 100.4], "ID": ["100", "100"]})
        self.vm._on_dataframe_changed(self.data.df)
        manager.open_window.assert_called_once()
        diff.run.assert_called_once()

    def test_observation_flush_timeout_still_finishes(self):
        diff, manager = Mock(running=False, source_comparison=False), Mock()
        self.vm.configure_observation(diff_vm=diff, diff_manager=manager, event_markers_vm=None, context_vm=None)
        self.data.df = pl.DataFrame({"TS": [100.0], "ID": ["100"]})
        self.vm.ingest_chunk(self._chunk(100.0))
        self.vm.start_observation((Mock(),), "100", 0.02, period_ms=0)
        self.vm.ingest_chunk(self._chunk(100.4))
        self.assertTrue(self._wait(lambda: manager.open_window.called, 3000))

    def test_busy_range_diff_queues_and_comparison_mode_switches_to_live(self):
        diff, manager = Mock(running=True, source_comparison=True), Mock()
        self.vm.configure_observation(diff_vm=diff, diff_manager=manager, event_markers_vm=None, context_vm=None)
        self.data.df = pl.DataFrame({"TS": [100.0, 100.4], "ID": ["100", "100"]})
        statuses = []
        self.vm.status_changed.connect(statuses.append)
        self.vm.ingest_chunk(self._chunk(100.0))
        self.vm.start_observation((Mock(),), "100", 0.02, period_ms=0)
        self.vm.ingest_chunk(self._chunk(100.4))
        self.assertTrue(self._wait(lambda: self.vm._pending_diff is not None))
        diff.run.assert_not_called()
        diff.running = False
        self.assertTrue(self._wait(lambda: diff.run.called))
        diff.clear_source_comparison.assert_called_once()
        manager.open_window.assert_called_once()
        self.assertTrue(any("busy" in s for s in statuses))

    def test_observation_uses_dbc_message_can_id(self):
        self.vm.ingest_chunk(self._chunk(1.0))
        self.vm.send_ramp = Mock()
        self.vm.start_observation((ResolvedFrame("x", 0x18FEF100, b"\0", True),), "wrong", 0.2)
        self.assertEqual(self.vm._observation.can_id, "18FEF100")

    def test_observation_can_be_canceled(self):
        self.vm.ingest_chunk(self._chunk(1.0))
        self.vm.send_ramp = Mock()
        self.assertTrue(self.vm.start_observation((Mock(),), "100", 0.2))
        self.vm.cancel_observation()
        self.assertIsNone(self.vm._observation)

    def test_connection_loss_cancels_observation(self):
        errors = []
        self.vm.error.connect(errors.append)
        self.vm.ingest_chunk(self._chunk(1.0))
        self.vm.send_ramp = Mock()
        self.vm.start_observation((Mock(),), "100", 0.2)
        self.vm._on_running_changed(False)
        self.assertFalse(self.vm.observing)
        self.assertEqual(len(errors), 1)

    def test_shutdown_stops_timers_and_observation(self):
        self.vm.ingest_chunk(self._chunk(1.0))
        self.vm.start_observation((Mock(),), "100", 0.5, period_ms=0)
        self.assertTrue(self.vm._observe_timer.isActive())
        self.vm.shutdown()
        self.assertFalse(self.vm.observing)
        self.assertFalse(self.vm._observe_timer.isActive())
        self.assertFalse(self.vm._progress_timer.isActive())

    def test_observation_is_blocked_in_replay(self):
        self.connection.is_replay = True
        self.sender.send_enabled = False
        self.vm.send_ramp = Mock()
        self.assertFalse(self.vm.start_observation((Mock(),), "100", 0.1))
        self.vm.send_ramp.assert_not_called()

    def test_dbc_ramps_honour_signed_float_mux_and_extended(self):
        manager, db = _dbc_manager()
        vm = ActiveReViewModel(self.data, self.connection, self.sender, manager)
        self.addCleanup(vm.shutdown)

        def ramp(message, signal, value):
            return vm.generate_ramp(can_id="", base_data=b"", start=value, stop=value, step=1,
                                    dbc_signal=("Test", message, signal))

        std = db.get_message_by_name("Std")
        self.assertEqual(ramp("Std", "Sgn", -1)[0].data, std.encode({"Be12": 0, "Sgn": -1, "Flt": 0.0}))
        self.assertEqual(ramp("Std", "Flt", 2.5)[0].data, std.encode({"Be12": 0, "Sgn": 0, "Flt": 2.5}))
        self.assertEqual(ramp("MuxMsg", "Val", 7)[0].data,
                         db.get_message_by_name("MuxMsg").encode({"Sel": 5, "Val": 7}))
        self.assertTrue(ramp("Ext", "Speed", 1)[0].extended)

    def test_manual_ramp_supports_big_endian_signed_and_extended(self):
        frames = self.vm.generate_ramp(can_id="18FEF100", base_data=bytes(2), start=-2, stop=-2, step=1,
                                       start_bit=7, length=8, little_endian=False, signed=True)
        self.assertEqual(frames[0].data, b"\xFE\x00")
        self.assertTrue(frames[0].extended)


class _FakeVm(QObject):
    status_changed = Signal(str)
    error = Signal(str)
    can_observe_changed = Signal(bool)
    activity_changed = Signal()
    observing = False
    ramp_active = False
    can_observe = True

    def __init__(self):
        super().__init__()
        self.generate_kwargs = {}
        self.replay_kwargs = {}

    def generate_ramp(self, **kwargs):
        self.generate_kwargs = kwargs
        return (ResolvedFrame("a", 0x100, b"\0", False),)

    def filtered_replay(self, **kwargs):
        self.replay_kwargs = kwargs


class ActiveReWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_offscreen_window_has_replay_and_ramp_controls_and_delete_on_close(self):
        window = ActiveReWindow(Mock())
        self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        self.assertTrue(window.replay_button.text())
        self.assertTrue(window.generate_button.text())
        self.assertTrue(window.observe_button.text())
        window.close()

    def test_inject_tab_displays_ampersand(self):
        window = ActiveReWindow(_FakeVm())
        self.assertEqual(window.tabs.tabText(2), "Inject && observe")
        window.close()

    def test_sections_and_manual_geometry_visibility_follow_signal_selection(self):
        window = ActiveReWindow(_FakeVm(), (("Working DBC", "Message", "Signal"),))
        self.assertEqual([window.tabs.tabText(i) for i in range(window.tabs.count())],
                         ["Replay subset", "Ramp", "Inject && observe"])
        self.assertFalse(window.manual_group.isHidden())
        self.assertTrue(window.can_id.isVisibleTo(window.manual_group))
        window.dbc_signal.setCurrentIndex(2)
        self.assertTrue(window.manual_group.isHidden())
        window.dbc_signal.setCurrentIndex(0)
        self.assertFalse(window.manual_group.isHidden())
        window.close()

    def test_vm_signals_are_disconnected_after_close(self):
        vm = _FakeVm()
        window = ActiveReWindow(vm)
        vm.status_changed.emit("hello")
        self.assertEqual(window.status.text(), "hello")
        status = window.status
        window.close()
        vm.status_changed.emit("late")
        vm.can_observe_changed.emit(False)
        vm.activity_changed.emit()
        self.assertEqual(status.text(), "hello")

    def test_observe_button_follows_vm_state_without_touching_privates(self):
        vm = _FakeVm()
        window = ActiveReWindow(vm)
        window._frames = (object(),)
        window._update_buttons()
        self.assertTrue(window.observe_button.isEnabled())
        vm.can_observe = False
        vm.can_observe_changed.emit(False)
        self.assertFalse(window.observe_button.isEnabled())
        window.close()

    def test_time_range_is_optional_and_manual_inputs_reach_the_view_model(self):
        vm = _FakeVm()
        window = ActiveReWindow(vm)
        window._replay()
        self.assertIsNone(vm.replay_kwargs["time_range"])
        window.use_time_range.setChecked(True)
        window.start_time.setValue(1.0)
        window.end_time.setValue(2.0)
        window._replay()
        self.assertEqual(vm.replay_kwargs["time_range"], (1.0, 2.0))
        window.byte_order.setCurrentIndex(1)
        window.value_type.setCurrentIndex(1)
        window.extended.setChecked(True)
        window.scale.setValue(0.5)
        window.offset.setValue(2.0)
        window._generate()
        kwargs = vm.generate_kwargs
        self.assertFalse(kwargs["little_endian"])
        self.assertTrue(kwargs["signed"])
        self.assertTrue(kwargs["extended"])
        self.assertEqual((kwargs["scale"], kwargs["offset"]), (0.5, 2.0))
        window.close()

    def test_signal_selector_groups_working_dbc_first(self):
        options = (("Other", "M", "S1"), ("Working DBC", "M", "S2"))
        window = ActiveReWindow(_FakeVm(), options, working_dbc_name="Working DBC")
        texts = [window.dbc_signal.itemText(i) for i in range(window.dbc_signal.count())]
        self.assertLess(texts.index("Working DBC / M / S2"), texts.index("Other / M / S1"))
        window.close()


if __name__ == "__main__":
    unittest.main()
