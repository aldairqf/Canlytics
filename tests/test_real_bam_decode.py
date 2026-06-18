"""End-to-end decode tests over the real candump fixture + j1939_clean.dbc.

The sample log (tests/fixtures/logs/) carries both J1939 multi-packet (BAM)
sessions and ordinary single-frame PGNs. With the J1939 database loaded in
``j1939`` mode this exercises the full real decode path: log parse -> PGN match
-> BAM reassembly / single-frame decode -> signal formatting.

Skips when either fixture is absent. See tests/fixtures/README.md.
"""

from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from services.bam_decode import decode_bam_frame
from services.can_log import CANLog
from services.dbc_manager import DbcManager
from tests.fixture_paths import dbc_file, log_files
from utils.can_id import can_id_to_int

# DbcManager is a QObject; ensure an application object exists.
_app = QCoreApplication.instance() or QCoreApplication([])

_DBC = dbc_file("j1939_clean.dbc")
_LOGS = log_files()


def _pf(raw_id: str) -> int:
    return (can_id_to_int(raw_id) >> 16) & 0xFF


@unittest.skipUnless(_DBC and _LOGS, "Needs j1939_clean.dbc + a log fixture")
class RealJ1939DecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mgr = DbcManager()
        cls.mgr.load_dbc(str(_DBC))
        # J1939 PGN matching (and BAM) only kicks in for entries in j1939 mode.
        cls.mgr.set_entry_mode(cls.mgr.list_entries()[0].name, "j1939")
        cls.df = CANLog(_LOGS[0]).load()

    def test_log_has_frames(self):
        self.assertGreater(self.df.height, 0)

    def test_log_contains_a_bam_session(self):
        pfs = {_pf(self.df["ID"][i]) for i in range(self.df.height)}
        self.assertIn(0xEC, pfs, "no TP.CM (BAM announce) frame in the log")
        self.assertIn(0xEB, pfs, "no TP.DT (BAM data) frame in the log")

    def test_decodes_a_bam_session(self):
        # First TP.CM (announce) row drives BAM reassembly + decode.
        bam_idx = next(
            (i for i in range(self.df.height) if _pf(self.df["ID"][i]) == 0xEC),
            None,
        )
        self.assertIsNotNone(bam_idx, "no TP.CM row found")
        items = decode_bam_frame(self.df, bam_idx, self.mgr)
        self.assertTrue(items, "BAM session decoded to zero signals")
        first = items[0]
        self.assertEqual(set(first), {"name", "value", "unit", "signal_def"})
        self.assertTrue(first["name"])

    def test_decodes_a_normal_frame(self):
        # Find the first ordinary (non-BAM) frame that the DBC can decode.
        decoded = None
        for i in range(self.df.height):
            raw_id = self.df["ID"][i]
            if _pf(raw_id) in (0xEC, 0xEB):
                continue
            result = self.mgr.decode_frame(raw_id, self.df["DATA"][i])
            if result:
                decoded = (raw_id, result)
                break
        self.assertIsNotNone(decoded, "no single-frame PGN in the log decoded")
        self.assertTrue(decoded[1][0].get("name"))


if __name__ == "__main__":
    unittest.main()
