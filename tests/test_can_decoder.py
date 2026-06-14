"""Characterization tests for services/can_decoder.decode_signal.

Expected values are computed by hand to pin the current bit-extraction behaviour.
"""

from __future__ import annotations

import unittest

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_data_parser import frame_dict, rows_to_df
from services.can_decoder import decode_signal


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


if __name__ == "__main__":
    unittest.main()
