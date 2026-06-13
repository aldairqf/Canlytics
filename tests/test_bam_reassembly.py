"""Characterization tests for services/bam_reassembly.assemble_bam_messages.

Synthetic J1939 BAM session: a TP.CM (announce) frame followed by two TP.DT
(data transfer) frames carrying 9 bytes total for PGN 0xFECA from source 0x00.
"""

from __future__ import annotations

import unittest

import polars as pl

from services.bam_reassembly import assemble_bam_messages

TARGET_PGN = 0xFECA
EXPECTED = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99])


def _session_df():
    return pl.DataFrame(
        {
            "TS": [0.0, 0.1, 0.2],
            "ID": ["18ECFF00", "18EBFF00", "18EBFF00"],
            "DATA": [
                "20090002FFCAFE00",  # TP.CM: BAM, 9 bytes, 2 packets, PGN=0xFECA
                "0111223344556677",  # TP.DT seq 1
                "028899AABBCCDDEE",  # TP.DT seq 2 (only first 2 data bytes used)
            ],
        }
    )


class AssembleBamMessagesTests(unittest.TestCase):
    def test_reassembles_full_message(self):
        messages = assemble_bam_messages(_session_df(), TARGET_PGN)
        self.assertEqual(len(messages), 1)
        msg = messages[0]
        self.assertEqual(msg.data, EXPECTED)
        self.assertEqual(msg.pgn, TARGET_PGN)
        self.assertEqual(msg.source_address, 0x00)
        self.assertAlmostEqual(msg.timestamp, 0.2)

    def test_source_address_filter_excludes_others(self):
        messages = assemble_bam_messages(_session_df(), TARGET_PGN, source_address=0x05)
        self.assertEqual(messages, [])

    def test_source_address_filter_matches(self):
        messages = assemble_bam_messages(_session_df(), TARGET_PGN, source_address=0x00)
        self.assertEqual(len(messages), 1)

    def test_non_matching_pgn_yields_nothing(self):
        self.assertEqual(assemble_bam_messages(_session_df(), 0x1234), [])

    def test_empty_df(self):
        self.assertEqual(assemble_bam_messages(pl.DataFrame(), TARGET_PGN), [])


if __name__ == "__main__":
    unittest.main()
