"""Characterization tests for services/signal_coverage.build_signal_coverage_report.

Pins the core promise of the feature: report every DBC signal that carries at
least one sample in the log, with two parallel stat sets per signal --
stats_all (every captured sample) and stats_real (excluding samples whose raw
bit pattern is "all data bits set", the SAE J1939 "not available" convention,
regardless of the signal's declared type or bit width). Which set to display
and whether to hide "no real data" signals is a display-time choice made by
views/signal_coverage_window.py, not a scan-time parameter.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication

from services.can_data_parser import frame_dict, rows_to_df
from services.dbc_manager import DbcManager
from services.signal_coverage import (
    SignalCoverageCanceled,
    SignalCoverageItem,
    SignalStats,
    build_can_id_index,
    build_signal_coverage_report,
    export_signal_coverage_csv,
    refresh_last_values,
)

# DbcManager is a QObject; ensure an application object exists.
_app = QCoreApplication.instance() or QCoreApplication([])

_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 MsgAlwaysFF: 8 ECU
 SG_ SigAlwaysFF : 0|8@1+ (1,0) [0|255] "unit" ECU

BO_ 257 MsgAlwaysFFFF: 8 ECU
 SG_ SigAlwaysFFFF : 0|16@1+ (1,0) [0|65535] "unit" ECU

BO_ 258 MsgMixedData: 8 ECU
 SG_ SigMixedData : 0|8@1+ (2,5) [0|999] "degC" ECU

BO_ 259 MsgAlwaysSignedAllOnes: 8 ECU
 SG_ SigAlwaysSignedAllOnes : 0|8@1- (1,0) [-128|127] "unit" ECU

BO_ 260 MsgAlwaysFloatAllOnes: 8 ECU
 SG_ SigAlwaysFloatAllOnes : 0|32@1+ (1,0) [0|0] "unit" ECU

BO_ 261 MsgConstant: 8 ECU
 SG_ SigConstant : 0|8@1+ (1,0) [0|255] "unit" ECU

BO_ 262 MsgNeverSeen: 8 ECU
 SG_ SigNeverSeen : 0|8@1+ (1,0) [0|255] "unit" ECU

CM_ SG_ 258 SigMixedData "Coolant temperature";

SIG_VALTYPE_ 260 SigAlwaysFloatAllOnes : 1;
"""


def _row(ts, can_id, *byte_values):
    data = bytes(byte_values) + bytes(8 - len(byte_values))
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=data)


def _test_df():
    rows = []
    for i in range(4):
        rows.append(_row(i * 1.0, "100", 0xFF))  # SigAlwaysFF -- always all-ones
        rows.append(_row(i * 1.0, "101", 0xFF, 0xFF))  # SigAlwaysFFFF -- always all-ones (16 bit)
        rows.append(_row(i * 1.0, "103", 0xFF))  # SigAlwaysSignedAllOnes -- always all-ones raw
        rows.append(_row(i * 1.0, "104", 0xFF, 0xFF, 0xFF, 0xFF))  # SigAlwaysFloatAllOnes
        rows.append(_row(i * 1.0, "105", 7))  # SigConstant -- always 7, never a sentinel
    # SigMixedData: one sentinel frame + three distinct real readings.
    rows.append(_row(10.0, "102", 0xFF))
    rows.append(_row(11.0, "102", 10))
    rows.append(_row(12.0, "102", 20))
    rows.append(_row(13.0, "102", 30))
    return rows_to_df(rows)


class BuildSignalCoverageReportTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)
        self.df = _test_df()

    def tearDown(self):
        os.remove(self.path)

    def _item(self, items, signal_name):
        return next((item for item in items if item.signal_name == signal_name), None)

    def test_empty_dataframe_returns_no_items(self):
        self.assertEqual(build_signal_coverage_report(rows_to_df([]), self.mgr), [])

    def test_signal_never_seen_on_bus_is_excluded(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertIsNone(self._item(items, "SigNeverSeen"))

    def test_uint8_always_all_ones_has_no_real_data(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigAlwaysFF")
        self.assertIsNotNone(item)  # the signal was seen -- it still gets an item
        self.assertIsNone(item.stats_real)  # but every sample was the sentinel

    def test_uint16_always_all_ones_has_no_real_data_not_just_0xff(self):
        # Proves the sentinel scales to the signal's own bit width (0xFFFF for
        # 16 bits), not a hardcoded 0xFF.
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertIsNone(self._item(items, "SigAlwaysFFFF").stats_real)

    def test_signed_signal_always_all_ones_raw_has_no_real_data(self):
        # decode_signal() would show this signal's value as a constant -1.0;
        # the exclusion must key off the raw bit pattern, not the signed value.
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertIsNone(self._item(items, "SigAlwaysSignedAllOnes").stats_real)

    def test_float32_signal_always_all_ones_raw_has_no_real_data(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertIsNone(self._item(items, "SigAlwaysFloatAllOnes").stats_real)

    def test_stats_all_always_includes_sentinel_values(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigAlwaysFF")
        self.assertEqual(item.stats_all.frame_count, 4)
        self.assertEqual(item.stats_all.min_value, 255.0)
        self.assertEqual(item.stats_all.max_value, 255.0)

    def test_constant_non_sentinel_signal_is_not_changing(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigConstant")
        self.assertIsNotNone(item.stats_real)
        self.assertFalse(item.stats_real.is_changing)
        self.assertEqual(item.stats_real.unique_count, 1)

    def test_mixed_data_stats_real_keeps_only_non_sentinel_samples(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigMixedData")
        stats = item.stats_real
        self.assertIsNotNone(stats)
        self.assertEqual(stats.frame_count, 3)  # the 0xFF frame was dropped
        self.assertEqual(stats.unique_count, 3)
        self.assertTrue(stats.is_changing)
        # raw 10/20/30 scaled by (scale=2, offset=5) -> 25/45/65
        self.assertEqual(stats.min_value, 25.0)
        self.assertEqual(stats.max_value, 65.0)
        self.assertAlmostEqual(stats.mean_value, 45.0)
        self.assertEqual(item.unit, "degC")
        self.assertEqual(item.description, "Coolant temperature")

    def test_mixed_data_stats_all_includes_the_sentinel_sample(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        stats = self._item(items, "SigMixedData").stats_all
        self.assertEqual(stats.frame_count, 4)  # the 0xFF frame is counted here
        self.assertEqual(stats.unique_count, 4)

    def test_last_value_is_the_most_recent_sample_in_log_order(self):
        # SigMixedData's last frame (ts=13.0, raw 30 -> scaled 65) is real, so
        # both stat sets agree here; test_trailing_sentinel_after_real_data
        # below covers the case where they diverge.
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigMixedData")
        self.assertEqual(item.stats_all.last_value, 65.0)
        self.assertEqual(item.stats_real.last_value, 65.0)

    def test_message_and_dbc_metadata_are_populated(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        item = self._item(items, "SigMixedData")
        self.assertEqual(item.message_name, "MsgMixedData")
        self.assertEqual(item.can_id, "102")
        self.assertIsNone(item.pgn)  # exact mode has no PGN
        self.assertEqual(item.dbc_name, self.mgr.list_entries()[0].name)
        self.assertEqual(item.match_mode, "exact")

    def test_cancellation_raises(self):
        with self.assertRaises(SignalCoverageCanceled):
            build_signal_coverage_report(self.df, self.mgr, should_cancel=lambda: True)

    def test_no_active_dbc_entries_returns_no_items(self):
        self.mgr.set_active(set())
        self.assertEqual(build_signal_coverage_report(self.df, self.mgr), [])

    def test_on_progress_reports_done_out_of_total_signal_count(self):
        calls = []
        build_signal_coverage_report(self.df, self.mgr, on_progress=lambda done, total: calls.append((done, total)))
        total_signals = sum(len(message.signals) for message in self.mgr.list_entries()[0].db.messages)
        self.assertEqual(len(calls), total_signals)
        self.assertTrue(all(total == total_signals for _, total in calls))
        self.assertEqual([done for done, _ in calls], list(range(1, total_signals + 1)))


_SHARED_MESSAGE_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 300 MsgShared: 8 ECU
 SG_ SigA : 0|8@1+ (1,0) [0|255] "{unit}" ECU
"""


class MultipleActiveDbcsTests(unittest.TestCase):
    """Two active DBCs that happen to define the same message/signal names must
    both show up, independently decoded and tagged by their own dbc_name --
    one DBC must never shadow or merge with another."""

    def setUp(self):
        self.paths = []
        self.mgr = DbcManager()
        for unit in ("volts", "amps"):
            fd, path = tempfile.mkstemp(suffix=".dbc")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_SHARED_MESSAGE_DBC.format(unit=unit))
            self.paths.append(path)
            self.mgr.load_dbc(path)
        self.df = rows_to_df([_row(i * 1.0, "12C", 42) for i in range(3)])  # 300 decimal = 0x12C

    def tearDown(self):
        for path in self.paths:
            os.remove(path)

    def test_both_dbcs_contribute_independent_items(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertEqual(len(items), 2)
        dbc_names = {item.dbc_name for item in items}
        self.assertEqual(len(dbc_names), 2, "each DBC entry must keep its own identity")
        units = {item.unit for item in items}
        self.assertEqual(units, {"volts", "amps"})
        for item in items:
            self.assertEqual(item.message_name, "MsgShared")
            self.assertEqual(item.signal_name, "SigA")
            self.assertEqual(item.stats_all.frame_count, 3)

    def test_sorted_by_dbc_name_first(self):
        items = build_signal_coverage_report(self.df, self.mgr)
        self.assertEqual([item.dbc_name for item in items], sorted(item.dbc_name for item in items))


class J1939ModeTests(unittest.TestCase):
    """get_signal_definition() reports the PGN in its "can_id" field for
    j1939/bam entries (it's used for display) -- that must never be fed back in
    as the frame id to match against, or every j1939 signal silently reports
    zero data (the selector ends up requiring frame_id == PGN, which never
    happens)."""

    def setUp(self):
        pf = 0xF0  # PDU2 range, so PS is a real part of the PGN
        self.msg_id = (0x18 << 24) | (pf << 16) | (0x00 << 8)
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {self.msg_id | 0x80000000} MsgJ1939: 8 ECU
 SG_ SigJ1939 : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_j1939_signal_with_real_data_is_found(self):
        can_id = f"{self.msg_id:X}"
        df = rows_to_df([_row(i * 1.0, can_id, 10 + i) for i in range(5)])

        items = build_signal_coverage_report(df, self.mgr)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.signal_name, "SigJ1939")
        self.assertEqual(item.match_mode, "j1939")
        self.assertEqual(item.stats_all.frame_count, 5)
        self.assertEqual(item.stats_all.min_value, 10.0)
        self.assertEqual(item.stats_all.max_value, 14.0)

    def test_can_id_is_the_real_frame_id_and_pgn_is_separate(self):
        # can_id must be the actual observed frame id, not the PGN -- and the
        # PGN is reported alongside it (0x%04X, matching decode_tab.py's own
        # PGN display), not conflated into the same field.
        df = rows_to_df([_row(0.0, f"{self.msg_id:X}", 10)])
        items = build_signal_coverage_report(df, self.mgr)
        self.assertEqual(items[0].can_id, f"{self.msg_id:X}")
        self.assertEqual(items[0].pgn, "0xF000")

    def test_pdu2_message_is_not_pdu1(self):
        # pf=0xF0 (>=240) here -- PDU2/broadcast, not point-to-point.
        df = rows_to_df([_row(0.0, f"{self.msg_id:X}", 10)])
        items = build_signal_coverage_report(df, self.mgr)
        self.assertFalse(items[0].is_pdu1)


class Pdu1ClassificationTests(unittest.TestCase):
    """is_pdu1 backs the Signal Scan window's 'Hide PDU1' filter -- PDU1
    (point-to-point, pf < 240) messages carry a destination address in the
    byte after PF, unlike PDU2 (broadcast) where that byte is part of the PGN
    itself (see the 18E1EFF3 -> PGN 0xE100 example discussed with the user)."""

    def setUp(self):
        pf = 0xE1  # PDU1 range (< 240): the next byte is a destination, not part of the PGN
        self.msg_id = (0x18 << 24) | (pf << 16) | (0x00 << 8)
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {self.msg_id | 0x80000000} MsgPdu1: 8 ECU
 SG_ SigPdu1 : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_pdu1_message_is_flagged(self):
        # A different destination byte (0xEF here vs 0x00 in the DBC) must
        # still match -- PDU1's destination address isn't part of the PGN.
        df = rows_to_df([_row(0.0, "18E1EF00", 10)])
        items = build_signal_coverage_report(df, self.mgr)
        self.assertEqual(items[0].pgn, "0xE100")
        self.assertTrue(items[0].is_pdu1)

    def test_exact_mode_is_pdu1_is_none(self):
        exact_mgr = DbcManager()
        fd, path = tempfile.mkstemp(suffix=".dbc")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_DBC)
            exact_mgr.load_dbc(path)
            items = build_signal_coverage_report(_test_df(), exact_mgr)
            self.assertTrue(items)
            self.assertTrue(all(item.is_pdu1 is None for item in items))
        finally:
            os.remove(path)


class MultipleSourcesPerPgnTests(unittest.TestCase):
    """A J1939 PGN can be broadcast by more than one source address (ECU) --
    each must get its own SignalCoverageItem with its own CAN ID and its own
    stats, not be silently merged into a single row that mixes both sources'
    samples together."""

    def setUp(self):
        pf = 0xF0  # PDU2 range, so PGN is 0xF000 regardless of source address
        base_id = (0x18 << 24) | (pf << 16) | (0x00 << 8)
        self.can_id_a = base_id | 0x0A
        self.can_id_b = base_id | 0x0B
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {base_id | 0x80000000} MsgJ1939: 8 ECU
 SG_ SigJ1939 : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_two_sources_produce_two_items_with_shared_pgn(self):
        df = rows_to_df(
            [_row(0.0, f"{self.can_id_a:X}", 10), _row(1.0, f"{self.can_id_a:X}", 20)]
            + [_row(2.0, f"{self.can_id_b:X}", 99)]
        )
        items = build_signal_coverage_report(df, self.mgr)

        self.assertEqual(len(items), 2)
        can_ids = {item.can_id for item in items}
        self.assertEqual(can_ids, {f"{self.can_id_a:X}", f"{self.can_id_b:X}"})
        pgns = {item.pgn for item in items}
        self.assertEqual(pgns, {"0xF000"})  # both sources share the same PGN

        item_a = next(item for item in items if item.can_id == f"{self.can_id_a:X}")
        item_b = next(item for item in items if item.can_id == f"{self.can_id_b:X}")
        self.assertEqual(item_a.stats_all.frame_count, 2)
        self.assertEqual(item_a.stats_all.min_value, 10.0)
        self.assertEqual(item_a.stats_all.max_value, 20.0)
        self.assertEqual(item_b.stats_all.frame_count, 1)
        self.assertEqual(item_b.stats_all.min_value, 99.0)

    def test_progress_ticks_once_per_signal_not_per_source(self):
        df = rows_to_df([_row(0.0, f"{self.can_id_a:X}", 10), _row(1.0, f"{self.can_id_b:X}", 20)])
        calls = []
        build_signal_coverage_report(df, self.mgr, on_progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(1, 1)])


class BamModeSkippedTests(unittest.TestCase):
    """BAM (multi-packet J1939) signals are intentionally not decoded by the
    scan for now -- reassembly re-scans the whole log per message, far more
    expensive than the direct exact/j1939 path at DBC scale. They must be
    skipped without crashing and without affecting progress accounting."""

    def setUp(self):
        pf = 0xF0  # PDU2 range, so PS is a real part of the PGN
        self.msg_id = (0x18 << 24) | (pf << 16) | (0x00 << 8)
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {self.msg_id | 0x80000000} MsgBam: 9 ECU
 SG_ SigBam : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_bam_mode_message_produces_no_items(self):
        df = rows_to_df([_row(i * 1.0, f"{self.msg_id:X}", 10 + i) for i in range(5)])
        items = build_signal_coverage_report(df, self.mgr)
        self.assertEqual(items, [])

    def test_bam_mode_message_still_ticks_progress(self):
        df = rows_to_df([_row(0.0, f"{self.msg_id:X}", 10)])
        calls = []
        build_signal_coverage_report(df, self.mgr, on_progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(1, 1)])


class ByteAlignedPropertyTests(unittest.TestCase):
    """SignalCoverageItem.byte_aligned flags signals that both start AND end on
    a byte boundary -- backs the Signal Scan window's 'Only byte-aligned'
    filter, which hides bit-packed fields that aren't a clean whole-byte SPN.
    A 2-bit flag starting at bit 0 is still a sub-byte bitfield even though its
    start bit alone is a multiple of 8 -- length must be checked too."""

    def _item(self, start_bit: int, length: int) -> SignalCoverageItem:
        stats = SignalStats(
            frame_count=1, unique_count=1, min_value=0.0, max_value=0.0,
            mean_value=0.0, is_changing=False, last_value=0.0,
        )
        return SignalCoverageItem(
            dbc_name="d", message_name="m", signal_name="s", can_id="100", pgn=None, is_pdu1=None,
            match_mode="exact",
            unit="", description="", start_bit=start_bit, length=length, byte_order="little_endian",
            value_type="uint", scale=1.0, offset=0.0, mux_info=None,
            mux_start=0, mux_bytes=0, mux_value=None,
            stats_all=stats, stats_real=stats,
        )

    def test_start_bit_zero_full_byte_is_byte_aligned(self):
        self.assertTrue(self._item(0, 8).byte_aligned)

    def test_start_bit_multiple_of_eight_and_whole_bytes_is_byte_aligned(self):
        self.assertTrue(self._item(16, 16).byte_aligned)

    def test_start_bit_mid_byte_is_not_byte_aligned(self):
        self.assertFalse(self._item(4, 8).byte_aligned)

    def test_byte_aligned_start_but_sub_byte_length_is_not_byte_aligned(self):
        # The exact case from the screenshot: "bit 0 . 2 bit" -- start bit is a
        # multiple of 8, but a 2-bit field is not a whole-byte SPN.
        self.assertFalse(self._item(0, 2).byte_aligned)
        self.assertFalse(self._item(24, 2).byte_aligned)

    def test_byte_aligned_start_with_length_not_a_multiple_of_eight(self):
        self.assertFalse(self._item(0, 12).byte_aligned)


class TrailingSentinelLastValueTests(unittest.TestCase):
    """When the most recently captured frame happens to be the "not available"
    sentinel, stats_all.last_value must still report it (it's the literal last
    sample), while stats_real.last_value must keep reporting the last REAL
    sample -- the two stat sets can disagree about "the last value"."""

    _DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 MsgTrailingSentinel: 8 ECU
 SG_ SigTrailing : 0|8@1+ (1,0) [0|255] "unit" ECU
"""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self._DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)

    def tearDown(self):
        os.remove(self.path)

    def test_stats_all_and_stats_real_disagree_on_last_value(self):
        df = rows_to_df([_row(0.0, "100", 10), _row(1.0, "100", 20), _row(2.0, "100", 0xFF)])
        items = build_signal_coverage_report(df, self.mgr)
        item = items[0]
        self.assertEqual(item.stats_all.last_value, 255.0)  # literal last frame
        self.assertEqual(item.stats_real.last_value, 20.0)  # last non-sentinel frame


class RefreshLastValuesTests(unittest.TestCase):
    """refresh_last_values() is the incremental counterpart to
    build_signal_coverage_report() used to keep the "last value" column live
    while streaming -- it must update only last_value (leaving frame_count/
    min/max/mean untouched) and only for items whose CAN ID appears in the new
    slice, without re-running the full scan."""

    _DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 MsgA: 8 ECU
 SG_ SigA : 0|8@1+ (1,0) [0|255] "unit" ECU

BO_ 257 MsgB: 8 ECU
 SG_ SigB : 0|8@1+ (1,0) [0|255] "unit" ECU
"""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self._DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)
        self.base_df = rows_to_df([_row(0.0, "100", 10), _row(1.0, "101", 50)])
        self.items = build_signal_coverage_report(self.base_df, self.mgr)

    def tearDown(self):
        os.remove(self.path)

    def _item(self, items, signal_name):
        return next(item for item in items if item.signal_name == signal_name)

    def test_matching_can_id_gets_last_value_updated(self):
        new_df = rows_to_df([_row(2.0, "100", 42)])
        updated = refresh_last_values(self.items, new_df)
        self.assertEqual(self._item(updated, "SigA").stats_all.last_value, 42.0)
        self.assertEqual(self._item(updated, "SigA").stats_real.last_value, 42.0)

    def test_frame_count_and_other_stats_are_unchanged(self):
        new_df = rows_to_df([_row(2.0, "100", 42)])
        updated = refresh_last_values(self.items, new_df)
        stats = self._item(updated, "SigA").stats_all
        self.assertEqual(stats.frame_count, 1)  # still the count from the full scan
        self.assertEqual(stats.min_value, 10.0)
        self.assertEqual(stats.max_value, 10.0)

    def test_item_with_no_new_matching_frames_is_returned_unchanged(self):
        new_df = rows_to_df([_row(2.0, "100", 42)])
        updated = refresh_last_values(self.items, new_df)
        old_sig_b = self._item(self.items, "SigB")
        new_sig_b = self._item(updated, "SigB")
        self.assertIs(old_sig_b, new_sig_b)  # untouched -- same object

    def test_empty_new_df_returns_items_unchanged(self):
        self.assertIs(refresh_last_values(self.items, rows_to_df([])), self.items)

    def test_no_items_returns_items_unchanged(self):
        new_df = rows_to_df([_row(2.0, "100", 42)])
        self.assertEqual(refresh_last_values([], new_df), [])

    def test_stats_real_stays_none_when_new_data_is_real_but_no_real_data_seen_yet(self):
        # SigA has only ever seen the sentinel -- promoting stats_real needs a
        # full recompute of frame_count/min/max/mean too, which only a full
        # scan does; the incremental refresh must not fabricate a partial one.
        df = rows_to_df([_row(0.0, "100", 0xFF)])
        items = build_signal_coverage_report(df, self.mgr)
        self.assertIsNone(self._item(items, "SigA").stats_real)

        new_df = rows_to_df([_row(1.0, "100", 42)])
        updated = refresh_last_values(items, new_df)
        item = self._item(updated, "SigA")
        self.assertIsNone(item.stats_real)
        self.assertEqual(item.stats_all.last_value, 42.0)


class BuildCanIdIndexTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(RefreshLastValuesTests._DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)
        self.base_df = rows_to_df([_row(0.0, "100", 10), _row(1.0, "101", 50)])
        self.items = build_signal_coverage_report(self.base_df, self.mgr)

    def tearDown(self):
        os.remove(self.path)

    def test_indexes_every_item_by_its_can_id(self):
        index = build_can_id_index(self.items)
        self.assertEqual(set(index.keys()), {0x100, 0x101})
        for indexes in index.values():
            self.assertEqual(len(indexes), 1)

    def test_empty_items_returns_empty_index(self):
        self.assertEqual(build_can_id_index([]), {})


class RefreshLastValuesWithIndexTests(unittest.TestCase):
    """A pre-built can_id_index must give identical results to letting
    refresh_last_values() derive one on the fly -- it's purely an optimization,
    never a behavior change."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(RefreshLastValuesTests._DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)
        self.base_df = rows_to_df([_row(0.0, "100", 10), _row(1.0, "101", 50)])
        self.items = build_signal_coverage_report(self.base_df, self.mgr)

    def tearDown(self):
        os.remove(self.path)

    def _item(self, items, signal_name):
        return next(item for item in items if item.signal_name == signal_name)

    def test_matches_no_index_result(self):
        new_df = rows_to_df([_row(2.0, "100", 42)])
        index = build_can_id_index(self.items)

        without_index = refresh_last_values(self.items, new_df)
        with_index = refresh_last_values(self.items, new_df, index)

        self.assertEqual(
            [i.stats_all.last_value for i in without_index],
            [i.stats_all.last_value for i in with_index],
        )

    def test_unmatched_can_id_leaves_items_untouched(self):
        index = build_can_id_index(self.items)
        new_df = rows_to_df([_row(2.0, "999", 42)])
        updated = refresh_last_values(self.items, new_df, index)
        for old, new in zip(self.items, updated):
            self.assertIs(old, new)

    def test_stale_index_missing_an_item_just_skips_it(self):
        # A defensive characterization, not a recommended usage: if the index
        # doesn't know about a CAN id (e.g. built before that item existed),
        # refresh_last_values() simply can't update it -- it doesn't fall back
        # to scanning, so callers must rebuild the index after a full rescan.
        new_df = rows_to_df([_row(2.0, "100", 42)])
        updated = refresh_last_values(self.items, new_df, can_id_index={})
        for old, new in zip(self.items, updated):
            self.assertIs(old, new)


class RefreshLastValuesJ1939Tests(unittest.TestCase):
    """refresh_last_values() must decode j1939-mode items the same way the
    full scan does -- items carry the real observed frame id (not the PGN),
    so partitioning the new slice by exact CAN id (like the full scan's
    id_groups) must still find them."""

    def setUp(self):
        pf = 0xF0  # PDU2 range
        self.msg_id = (0x18 << 24) | (pf << 16) | (0x00 << 8)
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {self.msg_id | 0x80000000} MsgJ1939: 8 ECU
 SG_ SigJ1939 : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_j1939_item_last_value_updates_from_new_frame(self):
        can_id = f"{self.msg_id:X}"
        base_df = rows_to_df([_row(0.0, can_id, 10)])
        items = build_signal_coverage_report(base_df, self.mgr)
        self.assertEqual(items[0].stats_all.last_value, 10.0)

        new_df = rows_to_df([_row(1.0, can_id, 55)])
        updated = refresh_last_values(items, new_df)
        self.assertEqual(updated[0].stats_all.last_value, 55.0)
        self.assertEqual(updated[0].match_mode, "j1939")  # unchanged


class RefreshLastValuesMuxedTests(unittest.TestCase):
    """refresh_last_values() must re-apply the same mux filter as the full
    scan (extract_signal_raw already does this given the item's mux geometry)
    -- a frame carrying a non-matching multiplexor value must not update a
    muxed signal's last_value."""

    _MUX_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 MsgMux: 8 ECU
 SG_ MuxSwitch M : 0|8@1+ (1,0) [0|255] "" ECU
 SG_ SigMuxed m1 : 8|8@1+ (1,0) [0|255] "unit" ECU
"""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self._MUX_DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)

    def tearDown(self):
        os.remove(self.path)

    def _item(self, items):
        return next(item for item in items if item.signal_name == "SigMuxed")

    def test_muxed_item_last_value_updates_when_new_frame_matches_mux(self):
        base_df = rows_to_df([_row(0.0, "100", 1, 10)])  # switch=1 (match), value=10
        items = build_signal_coverage_report(base_df, self.mgr)
        self.assertEqual(self._item(items).stats_all.last_value, 10.0)

        new_df = rows_to_df([_row(1.0, "100", 1, 42)])  # switch=1 (match), value=42
        updated = refresh_last_values(items, new_df)
        self.assertEqual(self._item(updated).stats_all.last_value, 42.0)

    def test_muxed_item_is_unaffected_by_frame_with_non_matching_mux(self):
        base_df = rows_to_df([_row(0.0, "100", 1, 10)])
        items = build_signal_coverage_report(base_df, self.mgr)

        new_df = rows_to_df([_row(1.0, "100", 0, 99)])  # switch=0 -- SigMuxed needs switch=1
        updated = refresh_last_values(items, new_df)
        self.assertEqual(self._item(updated).stats_all.last_value, 10.0)  # unchanged
        self.assertIs(self._item(updated), self._item(items))  # untouched -- same object


class ExportSignalCoverageCsvTests(unittest.TestCase):
    def test_writes_header_and_rows_in_given_order(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            export_signal_coverage_csv(["Parameter", "Value"], [["Speed", "42"], ["RPM", "1000"]], path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Universal-newline read translates the file's \r\n back to \n.
            self.assertEqual(content, "Parameter,Value\nSpeed,42\nRPM,1000\n")
        finally:
            os.remove(path)

    def test_no_rows_still_writes_header_only(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            export_signal_coverage_csv(["A", "B"], [], path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, "A,B\n")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
