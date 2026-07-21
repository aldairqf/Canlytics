"""Characterization tests for services/pgn_scanner.py.

available_bam_pgns() used to scan every row in Python to test one PDU-format
byte -- slow enough to freeze the UI on a real multi-million-row log for a
single combo-box population. Pins that the vectorized Polars pre-filter finds
the same PGNs as the old row-by-row scan would have.
"""

from __future__ import annotations

import unittest

from services.can_data_parser import frame_dict, rows_to_df
from services.pgn_scanner import available_bam_pgns, available_j1939_pgns


def _bam_announce_data(target_pgn: int) -> bytes:
    return bytes([0x20, 0x09, 0x00, 0x02, 0xFF, target_pgn & 0xFF, (target_pgn >> 8) & 0xFF, (target_pgn >> 16) & 0xFF])


class AvailableJ1939PgnsTests(unittest.TestCase):
    def test_extracts_pgn_from_extended_ids(self):
        rows = [frame_dict(ts=0.0, bus="b", can_id="18FEF100", data=bytes(8))]
        self.assertEqual(available_j1939_pgns(rows_to_df(rows)), [0xFEF1])

    def test_empty_dataframe_returns_empty(self):
        self.assertEqual(available_j1939_pgns(rows_to_df([])), [])

    def test_standard_ids_are_excluded(self):
        rows = [frame_dict(ts=0.0, bus="b", can_id="100", data=bytes(8))]
        self.assertEqual(available_j1939_pgns(rows_to_df(rows)), [])


class AvailableBamPgnsTests(unittest.TestCase):
    def test_finds_pgn_announced_by_a_bam_frame(self):
        rows = [frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=_bam_announce_data(0xFEE9))]
        self.assertEqual(available_bam_pgns(rows_to_df(rows)), [0xFEE9])

    def test_non_cm_pdu_format_is_excluded(self):
        # Same control byte / payload, but the CAN id's PDU format isn't 0xEC (CM).
        rows = [frame_dict(ts=0.0, bus="b", can_id="18FEF100", data=_bam_announce_data(0xFEE9))]
        self.assertEqual(available_bam_pgns(rows_to_df(rows)), [])

    def test_cm_frame_with_a_different_control_byte_is_not_a_bam_announce(self):
        data = bytearray(_bam_announce_data(0xFEE9))
        data[0] = 0x11  # not TP.CM_BAM's 0x20
        rows = [frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=bytes(data))]
        self.assertEqual(available_bam_pgns(rows_to_df(rows)), [])

    def test_multiple_bam_frames_are_deduplicated_and_sorted(self):
        rows = [
            frame_dict(ts=0.0, bus="b", can_id="18ECFF00", data=_bam_announce_data(0xFEE9)),
            frame_dict(ts=1.0, bus="b", can_id="18ECFF00", data=_bam_announce_data(0xFEE9)),
            frame_dict(ts=2.0, bus="b", can_id="18ECFF00", data=_bam_announce_data(0xFD00)),
        ]
        self.assertEqual(available_bam_pgns(rows_to_df(rows)), [0xFD00, 0xFEE9])

    def test_empty_dataframe_returns_empty(self):
        self.assertEqual(available_bam_pgns(rows_to_df([])), [])

    def test_no_matching_frames_returns_empty(self):
        rows = [frame_dict(ts=0.0, bus="b", can_id="18FEF100", data=bytes(8))]
        self.assertEqual(available_bam_pgns(rows_to_df(rows)), [])


if __name__ == "__main__":
    unittest.main()
