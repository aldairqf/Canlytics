"""Characterization tests for services/can_decoder.decode_signal.

Expected values are computed by hand to pin the current bit-extraction behaviour.
"""

from __future__ import annotations

import unittest

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_data_parser import frame_dict, rows_to_df
from services.can_decoder import (
    decode_signal,
    decode_signal_raw,
    extract_signal_raw,
    extract_signals_raw_batch,
    filter_frames_for_signal,
    partition_by_id,
    partition_by_pgn,
    with_data_int,
    with_id_columns,
)


def _df(*frames):
    """frames: iterable of (ts, can_id, data_bytes)."""
    rows = [frame_dict(ts=ts, bus="b", can_id=cid, data=data) for ts, cid, data in frames]
    return rows_to_df(rows)


EXACT = FrameSelector(mode="exact")


class DecodeSignalTests(unittest.TestCase):
    def test_empty_df_returns_empty(self):
        sig = Signal(name="s", can_id="100", start_bit=0, length=8)
        ts, vals = decode_signal(rows_to_df([]), sig, EXACT)
        self.assertEqual((ts, vals), ([], []))

    def test_little_endian_uint16(self):
        # D0=0x34, D1=0x12 -> DATA_INT=0x1234=4660; LE bits 0..15 -> 4660
        df = _df((0.0, "100", bytes([0x34, 0x12])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True)
        ts, vals = decode_signal(df, sig, EXACT)
        self.assertEqual(ts, [0.0])
        self.assertEqual(vals, [4660.0])

    def test_scale_and_offset(self):
        df = _df((0.0, "100", bytes([0x34, 0x12])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True, scale=0.5, offset=10.0)
        _, vals = decode_signal(df, sig, EXACT)
        self.assertEqual(vals, [2340.0])  # 4660 * 0.5 + 10

    def test_big_endian_byte0_only(self):
        # D0=0xFF only; BE len8 start0 reads bit0 into MSB position -> 128
        df = _df((0.0, "100", bytes([0xFF])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=8, le=False)
        _, vals = decode_signal(df, sig, EXACT)
        self.assertEqual(vals, [128.0])

    def test_signed_int(self):
        # raw 0xFF over 8 bits -> -1 when interpreted as signed int
        df = _df((0.0, "100", bytes([0xFF])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=8, le=True, type_data="int")
        _, vals = decode_signal(df, sig, EXACT)
        self.assertEqual(vals, [-1.0])

    def test_float32(self):
        # little-endian IEEE-754 for 1.0 is 00 00 80 3F
        df = _df((0.0, "100", bytes([0x00, 0x00, 0x80, 0x3F])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=32, le=True, type_data="float32")
        _, vals = decode_signal(df, sig, EXACT)
        self.assertAlmostEqual(vals[0], 1.0, places=5)

    def test_mux_filters_non_matching_frames(self):
        # mux byte is D0; only frames with D0==2 are kept. Signal reads D1 (bits 8..15).
        df = _df(
            (0.0, "100", bytes([0x02, 0x0A])),  # mux match -> value 10
            (1.0, "100", bytes([0x01, 0xFF])),  # mux mismatch -> dropped
        )
        sig = Signal(
            name="s", can_id="100", start_bit=8, length=8, le=True,
            mux_bytes=1, mux_start=0, mux_value=2,
        )
        ts, vals = decode_signal(df, sig, EXACT)
        self.assertEqual(ts, [0.0])
        self.assertEqual(vals, [10.0])


# Synthetic J1939 BAM session, same fixture shape as tests/test_bam_reassembly.py:
# a TP.CM (announce) frame followed by two TP.DT frames reassembling to 9 bytes
# for PGN 0xFECA from source 0x00.
_BAM_PGN = 0xFECA


def _bam_session_df():
    return rows_to_df(
        [
            frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=bytes.fromhex("20090002FFCAFE00")),
            frame_dict(ts=0.1, bus="b", can_id="18EBFF00", data=bytes.fromhex("0111223344556677")),
            frame_dict(ts=0.2, bus="b", can_id="18EBFF00", data=bytes.fromhex("028899AABBCCDDEE")),
        ]
    )


def _bam_session_df_all_ones():
    # 4 payload bytes of 0xFF -> reassembles to the NaN float32 bit pattern.
    return rows_to_df(
        [
            frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=bytes.fromhex("20040001FFCAFE00")),
            frame_dict(ts=0.1, bus="b", can_id="18EBFF00", data=bytes.fromhex("01FFFFFFFF000000")),
        ]
    )


def _bam_session_df_truncated():
    # total_bytes=1 -> reassembles to a single byte (0x02), shorter than a 3-byte mux field.
    return rows_to_df(
        [
            frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=bytes.fromhex("20010001FFCAFE00")),
            frame_dict(ts=0.1, bus="b", can_id="18EBFF00", data=bytes.fromhex("0102000000000000")),
        ]
    )


class DecodeSignalRawTests(unittest.TestCase):
    """decode_signal_raw() must return the bit pattern before type interpretation
    and before scale/offset -- decode_signal() builds its output from exactly this."""

    def test_empty_df_returns_empty(self):
        sig = Signal(name="s", can_id="100", start_bit=0, length=8)
        ts, raw = decode_signal_raw(rows_to_df([]), sig, EXACT)
        self.assertEqual((ts, raw), ([], []))

    def test_raw_is_unscaled(self):
        df = _df((0.0, "100", bytes([0x34, 0x12])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True, scale=0.5, offset=10.0)
        ts, raw = decode_signal_raw(df, sig, EXACT)
        self.assertEqual(raw, [4660])  # decode_signal() would scale this to 2340.0

    def test_signed_all_ones_raw_stays_unsigned(self):
        # decode_signal() converts this to -1.0 (see test_signed_int); the raw
        # bit pattern must stay the unsigned 255 so a "not available" (all-ones)
        # check works the same regardless of type_data.
        df = _df((0.0, "100", bytes([0xFF])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=8, le=True, type_data="int")
        ts, raw = decode_signal_raw(df, sig, EXACT)
        self.assertEqual(raw, [255])

    def test_float32_all_ones_raw_is_the_uint32_bit_pattern(self):
        # decode_signal() reinterprets this as a NaN float32 and zeroes it via
        # nan_to_num; the raw form must preserve the actual bit pattern.
        df = _df((0.0, "100", bytes([0xFF, 0xFF, 0xFF, 0xFF])))
        sig = Signal(name="s", can_id="100", start_bit=0, length=32, le=True, type_data="float32")
        ts, raw = decode_signal_raw(df, sig, EXACT)
        self.assertEqual(raw, [0xFFFFFFFF])

    def test_mux_filters_non_matching_frames(self):
        df = _df(
            (0.0, "100", bytes([0x02, 0x0A])),
            (1.0, "100", bytes([0x01, 0xFF])),
        )
        sig = Signal(
            name="s", can_id="100", start_bit=8, length=8, le=True,
            mux_bytes=1, mux_start=0, mux_value=2,
        )
        ts, raw = decode_signal_raw(df, sig, EXACT)
        self.assertEqual(ts, [0.0])
        self.assertEqual(raw, [10])

    def test_bam_raw_matches_reassembled_payload_byte(self):
        sig = Signal(name="s", can_id="18ECFF00", start_bit=0, length=8, le=True)
        selector = FrameSelector(selected_id="18ECFF00", mode="bam", pgn=_BAM_PGN)
        ts, raw = decode_signal_raw(_bam_session_df(), sig, selector)
        self.assertEqual(raw, [0x11])

    def test_bam_decode_signal_still_applies_scale_offset(self):
        sig = Signal(name="s", can_id="18ECFF00", start_bit=0, length=8, le=True, scale=2.0, offset=1.0)
        selector = FrameSelector(selected_id="18ECFF00", mode="bam", pgn=_BAM_PGN)
        _, values = decode_signal(_bam_session_df(), sig, selector)
        self.assertEqual(values, [0x11 * 2.0 + 1.0])

    def test_bam_float32_nan_is_zeroed(self):
        # BAM scalar path must zero NaN float32 like the exact/j1939 vectorized path does.
        sig = Signal(name="s", can_id="18ECFF00", start_bit=0, length=32, le=True, type_data="float32")
        selector = FrameSelector(selected_id="18ECFF00", mode="bam", pgn=_BAM_PGN)
        _, values = decode_signal(_bam_session_df_all_ones(), sig, selector)
        self.assertEqual(values, [0.0])

    def test_bam_mux_with_truncated_payload_keeps_high_order_weight(self):
        # Reassembled payload is 1 byte (0x02); a 3-byte mux field missing its
        # trailing bytes must still weigh the present byte as the high-order one.
        sig = Signal(
            name="s", can_id="18ECFF00", start_bit=0, length=8, le=True,
            mux_start=0, mux_bytes=3, mux_value=0x02 << 16,
        )
        selector = FrameSelector(selected_id="18ECFF00", mode="bam", pgn=_BAM_PGN)
        ts, raw = decode_signal_raw(_bam_session_df_truncated(), sig, selector)
        self.assertEqual(raw, [2])


class J1939PgnFilterTests(unittest.TestCase):
    """Pins _filter_by_selector's j1939-mode PGN matching (PDU1 vs PDU2 split)
    ahead of vectorizing it -- these must keep passing unchanged."""

    def test_pdu2_broadcast_pgn_includes_group_extension(self):
        # pf=0xFE (>=240, PDU2) -- the PS byte is a group extension and IS part
        # of the PGN, so only frames with matching PS qualify.
        df = _df(
            (0.0, "18FEE300", bytes([0x11])),  # PGN 0xFEE3 -- matches
            (1.0, "18FEE400", bytes([0x22])),  # PGN 0xFEE4 -- does not match
        )
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        ts, raw = decode_signal_raw(df, sig, FrameSelector(mode="j1939", pgn=0xFEE3))
        self.assertEqual(ts, [0.0])
        self.assertEqual(raw, [0x11])

    def test_pdu1_pgn_ignores_destination_address(self):
        # pf=0xEF (<240, PDU1) -- the PS byte is a destination address, not
        # part of the PGN, so different destinations still share one PGN.
        df = _df(
            (0.0, "18EF0A0B", bytes([0x44])),  # PGN 0xEF00, dest 0x0B
            (1.0, "18EF140C", bytes([0x55])),  # PGN 0xEF00, dest 0x0C -- still matches
            (2.0, "18F00A0D", bytes([0x66])),  # pf=0xF0 -> different PGN -- excluded
        )
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        ts, raw = decode_signal_raw(df, sig, FrameSelector(mode="j1939", pgn=0xEF00))
        self.assertEqual(raw, [0x44, 0x55])

    def test_chosen_id_narrows_pgn_match_to_one_source(self):
        df = _df(
            (0.0, "18EF0A0B", bytes([0x44])),
            (1.0, "18EF140C", bytes([0x55])),
        )
        sig = Signal(name="s", can_id="18EF0A0B", start_bit=0, length=8, le=True)
        ts, raw = decode_signal_raw(df, sig, FrameSelector(mode="j1939", pgn=0xEF00))
        self.assertEqual(raw, [0x44])

    def test_pgn_derived_from_selected_id_when_not_given(self):
        df = _df((0.0, "18FEE300", bytes([0x77])))
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        ts, raw = decode_signal_raw(df, sig, FrameSelector(mode="j1939", selected_id="18FEE300"))
        self.assertEqual(raw, [0x77])


class StandardIdExcludedFromJ1939Tests(unittest.TestCase):
    """J1939 is always carried on 29-bit extended frames. An 11-bit
    standard-range id (<= 0x7FF) has all-zero pf/ps/dp bits under the PGN
    formula, which used to resolve to PGN 0 (e.g. TSC1) for almost any such
    id -- silently matching unrelated non-J1939 traffic to whatever message
    owns PGN 0 (reported by the user: short ids like 006/007/107 showing up
    as TSC1 in Signal Scan)."""

    def test_standard_range_ids_do_not_match_pgn_zero(self):
        df = _df(
            (0.0, "006", bytes([0xAA])),
            (1.0, "007", bytes([0xBB])),
            (2.0, "107", bytes([0xDD])),
            (3.0, "C000000", bytes([0xCC])),  # priority 3, pf=0, ps=0 -> real PGN-0 frame
        )
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        ts, raw = decode_signal_raw(df, sig, FrameSelector(mode="j1939", pgn=0))
        self.assertEqual(ts, [3.0])
        self.assertEqual(raw, [0xCC])

    def test_with_id_columns_leaves_pgn_null_for_standard_range_ids(self):
        df = _df((0.0, "407", bytes([0x01])))
        precomputed = with_id_columns(df)
        self.assertEqual(precomputed["_PGN"].to_list(), [None])


class ManualDecodeStepsTests(unittest.TestCase):
    """filter_frames_for_signal() + with_data_int() + extract_signal_raw(), called
    by hand, must produce exactly decode_signal_raw()'s result -- this is the
    contract a caller decoding many signals of one message relies on to filter
    and build DATA_INT once instead of once per signal (see signal_coverage.py)."""

    def test_manual_pipeline_matches_decode_signal_raw(self):
        df = _df(
            (0.0, "100", bytes([0x34, 0x12])),
            (1.0, "200", bytes([0xFF, 0xFF])),  # different id -- must be filtered out
        )
        sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True)

        expected_ts, expected_raw = decode_signal_raw(df, sig, EXACT)

        prepared = with_data_int(filter_frames_for_signal(df, sig, EXACT))
        ts, raw = extract_signal_raw(prepared, sig)

        self.assertEqual((ts, raw), (expected_ts, expected_raw))
        self.assertEqual(raw, [4660])

    def test_prepared_frame_is_reusable_across_signals_of_one_message(self):
        # Two signals reading different bits of the SAME message share one
        # filter_frames_for_signal()/with_data_int() call.
        df = _df((0.0, "100", bytes([0x34, 0x12])))
        sig_a = Signal(name="a", can_id="100", start_bit=0, length=8, le=True)
        sig_b = Signal(name="b", can_id="100", start_bit=8, length=8, le=True)

        prepared = with_data_int(filter_frames_for_signal(df, sig_a, EXACT))
        _, raw_a = extract_signal_raw(prepared, sig_a)
        _, raw_b = extract_signal_raw(prepared, sig_b)

        self.assertEqual(raw_a, [0x34])
        self.assertEqual(raw_b, [0x12])

    def test_precomputed_id_columns_are_reused_not_recomputed(self):
        # Same decode, but the caller precomputes _ID_INT/_PGN once up front
        # (as services/signal_coverage.py does for a whole scan) instead of
        # letting each filter_frames_for_signal() call reparse the ID column.
        df = _df(
            (0.0, "18FEE300", bytes([0x11])),
            (1.0, "18FEE400", bytes([0x22])),
        )
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        selector = FrameSelector(mode="j1939", pgn=0xFEE3)

        expected_ts, expected_raw = decode_signal_raw(df, sig, selector)

        precomputed = with_id_columns(df)
        self.assertIn("_ID_INT", precomputed.columns)
        self.assertIn("_PGN", precomputed.columns)
        prepared = with_data_int(filter_frames_for_signal(precomputed, sig, selector))
        ts, raw = extract_signal_raw(prepared, sig)

        self.assertEqual((ts, raw), (expected_ts, expected_raw))
        self.assertEqual(raw, [0x11])

    def test_with_id_columns_is_idempotent(self):
        df = _df((0.0, "100", bytes([0x34])))
        once = with_id_columns(df)
        twice = with_id_columns(once)
        self.assertEqual(once["_ID_INT"].to_list(), twice["_ID_INT"].to_list())
        self.assertEqual(once["_PGN"].to_list(), twice["_PGN"].to_list())

    def test_batch_extraction_matches_individual_calls(self):
        # Byte 0, byte 1, and a 16-bit signal spanning both -- all non-muxed,
        # all reading the same message.
        df = _df((0.0, "100", bytes([0x34, 0x12])), (1.0, "100", bytes([0xAB, 0xCD])))
        prepared = with_data_int(filter_frames_for_signal(df, Signal(name="x", can_id="100"), EXACT))
        sig_a = Signal(name="a", can_id="100", start_bit=0, length=8, le=True)
        sig_b = Signal(name="b", can_id="100", start_bit=8, length=8, le=True)
        sig_c = Signal(name="c", can_id="100", start_bit=0, length=16, le=True)

        individual = [extract_signal_raw(prepared, sig) for sig in (sig_a, sig_b, sig_c)]
        batched = extract_signals_raw_batch(prepared, [sig_a, sig_b, sig_c])

        self.assertEqual(batched, individual)
        self.assertEqual(batched[0][1], [0x34, 0xAB])
        self.assertEqual(batched[1][1], [0x12, 0xCD])
        self.assertEqual(batched[2][1], [0x1234, 0xCDAB])

    def test_batch_extraction_of_empty_list_returns_empty(self):
        prepared = with_data_int(_df((0.0, "100", bytes([1]))))
        self.assertEqual(extract_signals_raw_batch(prepared, []), [])


class WithDataIntCachingTests(unittest.TestCase):
    """with_data_int() must be idempotent, and the D0..D7 fast path must match the old re-parse-DATA-hex result."""

    def test_idempotent_when_data_int_already_present(self):
        df = _df((0.0, "100", bytes([1, 2, 3, 4, 5, 6, 7, 8])))
        once = with_data_int(df)
        twice = with_data_int(once)
        self.assertIs(twice, once)  # truly a no-op, not just equal values

    def test_d_columns_fast_path_matches_hex_reparse_fallback(self):
        df = _df((0.0, "100", bytes([1, 2, 3, 4, 5, 6, 7, 8])))
        fast = with_data_int(df)  # D0..D7 present -- takes the fast path
        no_d_columns = df.drop([f"D{i}" for i in range(8)])
        fallback = with_data_int(no_d_columns)  # forces the DATA-hex re-parse path
        self.assertEqual(fast["DATA_INT"].to_list(), fallback["DATA_INT"].to_list())

    def test_fast_path_value_is_little_endian_of_the_bytes(self):
        df = _df((0.0, "100", bytes([0xFF, 0, 0, 0, 0, 0, 0, 0])))
        prepared = with_data_int(df)
        self.assertEqual(prepared["DATA_INT"].to_list(), [0xFF])

    def test_truncated_payload_treats_missing_bytes_as_zero(self):
        df = _df((0.0, "100", bytes([1])))  # 1-byte frame, D1..D7 padded to 0
        prepared = with_data_int(df)
        self.assertEqual(prepared["DATA_INT"].to_list(), [1])


class PartitionTests(unittest.TestCase):
    """partition_by_pgn()/partition_by_id() must split the log into exactly the
    row sets a per-message filter_frames_for_signal() call would produce --
    services/signal_coverage.py relies on this to look a message's frames up
    once for the whole scan instead of re-filtering the log per message."""

    def test_partition_by_pgn_matches_manual_filter(self):
        df = _df(
            (0.0, "18FEE300", bytes([0x11])),
            (1.0, "18FEE400", bytes([0x22])),
            (2.0, "18FEE301", bytes([0x33])),  # same PGN 0xFEE3, different source
        )
        sig = Signal(name="s", start_bit=0, length=8, le=True)
        selector = FrameSelector(mode="j1939", pgn=0xFEE3)

        expected_ts, expected_raw = decode_signal_raw(df, sig, selector)

        group = partition_by_pgn(df)[0xFEE3]
        ts, raw = extract_signal_raw(with_data_int(group), sig)

        self.assertEqual((ts, raw), (expected_ts, expected_raw))
        self.assertEqual(raw, [0x11, 0x33])

    def test_partition_by_pgn_has_no_entry_for_absent_pgn(self):
        df = _df((0.0, "18FEE300", bytes([0x11])))
        self.assertNotIn(0xABCD, partition_by_pgn(df))

    def test_partition_by_id_matches_manual_filter(self):
        df = _df(
            (0.0, "100", bytes([0x34, 0x12])),
            (1.0, "200", bytes([0xFF, 0xFF])),
        )
        sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True)

        expected_ts, expected_raw = decode_signal_raw(df, sig, EXACT)

        group = partition_by_id(df)[0x100]
        ts, raw = extract_signal_raw(with_data_int(group), sig)

        self.assertEqual((ts, raw), (expected_ts, expected_raw))
        self.assertEqual(raw, [4660])

    def test_partitions_carry_precomputed_id_columns(self):
        df = _df((0.0, "18FEE300", bytes([0x11])))
        for group in partition_by_pgn(df).values():
            self.assertIn("_ID_INT", group.columns)
            self.assertIn("_PGN", group.columns)


if __name__ == "__main__":
    unittest.main()
