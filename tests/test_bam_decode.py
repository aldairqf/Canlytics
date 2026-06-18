"""Characterization tests for services/bam_decode.

Covers the guard/early-return branches, the pure ``_find_last_bam_pgn`` lookup,
and the happy path of ``decode_bam_frame`` driven by a stub DBC manager (no
cantools file needed).
"""

from __future__ import annotations

import unittest

import polars as pl

from services.bam_decode import _find_last_bam_pgn, decode_bam_frame

TARGET_PGN = 0xFECA


def _session_df():
    # TP.CM announce (PF 0xEC) + two TP.DT (PF 0xEB), source 0x00, PGN 0xFECA.
    return pl.DataFrame(
        {
            "TS": [0.0, 0.1, 0.2],
            "ID": ["18ECFF00", "18EBFF00", "18EBFF00"],
            "DATA": [
                "20090002FFCAFE00",  # BAM, 9 bytes, 2 packets, PGN=0xFECA
                "0111223344556677",
                "028899AABBCCDDEE",
            ],
        }
    )


class _FakeSignal:
    def __init__(self, name, unit=""):
        self.name = name
        self.unit = unit


class _FakeMessage:
    name = "EngineData"

    def __init__(self):
        self.length = 9
        self.signals = [_FakeSignal("Rpm", "rpm"), _FakeSignal("Temp", "degC")]

    def decode(self, data_bytes, decode_choices=False):
        return {"Rpm": 1500, "Temp": 90}


class _FakeEntry:
    name = "MyDbc"


class _FakeDbcManager:
    def __init__(self, message=None):
        self._message = message

    def get_message_by_pgn(self, pgn):
        if self._message is None:
            return None
        return (_FakeEntry(), self._message)

    def get_signal_definition(self, dbc_name, msg_name, signal_name, scaled=True):
        return {"name": signal_name}


class FindLastBamPgnTests(unittest.TestCase):
    def test_finds_announced_pgn(self):
        self.assertEqual(_find_last_bam_pgn(_session_df(), source=0x00, ts=0.2), TARGET_PGN)

    def test_wrong_source_returns_none(self):
        self.assertIsNone(_find_last_bam_pgn(_session_df(), source=0x05, ts=0.2))

    def test_stops_at_ts_before_announce(self):
        # ts cutoff before the TP.CM frame at 0.0 still includes it (row_ts <= ts);
        # a cutoff below 0.0 excludes it.
        self.assertIsNone(_find_last_bam_pgn(_session_df(), source=0x00, ts=-1.0))

    def test_empty_df(self):
        self.assertIsNone(_find_last_bam_pgn(pl.DataFrame(), source=0x00, ts=1.0))


class DecodeBamFrameGuardTests(unittest.TestCase):
    def test_empty_df(self):
        self.assertEqual(decode_bam_frame(pl.DataFrame(), 0, _FakeDbcManager()), [])

    def test_none_df(self):
        self.assertEqual(decode_bam_frame(None, 0, _FakeDbcManager()), [])

    def test_out_of_range_index(self):
        self.assertEqual(decode_bam_frame(_session_df(), 99, _FakeDbcManager()), [])
        self.assertEqual(decode_bam_frame(_session_df(), -1, _FakeDbcManager()), [])

    def test_invalid_id_returns_empty(self):
        df = pl.DataFrame({"TS": [0.0], "ID": ["ZZZZ"], "DATA": ["20090002FFCAFE00"]})
        self.assertEqual(decode_bam_frame(df, 0, _FakeDbcManager()), [])

    def test_non_bam_frame_returns_empty(self):
        # PF 0xFE is neither 0xEC nor 0xEB -> no target PGN.
        df = pl.DataFrame({"TS": [0.0], "ID": ["18FEF100"], "DATA": ["0011223344556677"]})
        self.assertEqual(decode_bam_frame(df, 0, _FakeDbcManager(_FakeMessage())), [])

    def test_unknown_pgn_returns_empty(self):
        # Valid TP.CM frame but the DBC manager resolves nothing.
        self.assertEqual(decode_bam_frame(_session_df(), 0, _FakeDbcManager(None)), [])


class DecodeBamFrameHappyPathTests(unittest.TestCase):
    def test_decodes_signals_from_announce_frame(self):
        items = decode_bam_frame(_session_df(), 0, _FakeDbcManager(_FakeMessage()))
        names = [it["name"] for it in items]
        self.assertEqual(names, ["Rpm", "Temp"])
        self.assertEqual(items[0]["value"], "1500")
        self.assertEqual(items[0]["unit"], "rpm")
        self.assertEqual(items[0]["signal_def"], {"name": "Rpm"})

    def test_decode_from_data_transfer_frame(self):
        # row_index points at a TP.DT frame (PF 0xEB); the PGN is recovered by
        # scanning back for the announce.
        items = decode_bam_frame(_session_df(), 1, _FakeDbcManager(_FakeMessage()))
        self.assertEqual([it["name"] for it in items], ["Rpm", "Temp"])


if __name__ == "__main__":
    unittest.main()
