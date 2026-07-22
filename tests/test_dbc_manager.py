"""Characterization tests for services/dbc_manager (load + exact-mode resolution)."""

from __future__ import annotations

import os
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication

from services.dbc_manager import DbcManager

# DbcManager is a QObject; ensure an application object exists.
_app = QCoreApplication.instance() or QCoreApplication([])

MINIMAL_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 TestMsg: 8 ECU
 SG_ TestSig : 0|8@1+ (1,0) [0|255] "unit" ECU
"""


class DbcManagerTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(MINIMAL_DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self.path)

    def tearDown(self):
        os.remove(self.path)

    def test_one_entry_loaded(self):
        self.assertEqual(len(self.mgr.list_entries()), 1)

    def test_resolves_known_message_by_hex_id(self):
        self.assertEqual(self.mgr.resolve_message_name("100"), "TestMsg")

    def test_unknown_id_returns_none(self):
        self.assertIsNone(self.mgr.resolve_message_name("999"))

    def test_malformed_id_returns_none(self):
        self.assertIsNone(self.mgr.resolve_message_name("ZZ"))

    def test_empty_id_returns_none(self):
        self.assertIsNone(self.mgr.resolve_message_name(""))


UNIT_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 TestMsg: 8 ECU
 SG_ Temp : 0|8@1+ (1,-40) [-40|210] "°C" ECU
"""


class DbcEncodingDetectionTests(unittest.TestCase):
    """cantools defaults .dbc files to cp1252, mojibaking a genuinely UTF-8
    file's non-ASCII unit/comment text (e.g. "°C" -> "Â°C").
    cantools also silently substitutes replacement characters on a decode
    mismatch instead of raising, so detection must happen before calling it."""

    def _unit_of(self, encoding: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".dbc")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(UNIT_DBC.encode(encoding))
            mgr = DbcManager()
            mgr.load_dbc(path)
            name = next(iter(mgr._entries))
            message = mgr.get_messages(name)[0]
            return message.get_signal_by_name("Temp").unit
        finally:
            os.remove(path)

    def test_utf8_file_unit_not_mojibaked(self):
        self.assertEqual(self._unit_of("utf-8"), "°C")

    def test_cp1252_file_still_loads_correctly(self):
        self.assertEqual(self._unit_of("cp1252"), "°C")


class J1939StandardIdNotMatchedTests(unittest.TestCase):
    """resolve_message_name()'s j1939-mode PGN lookup must never match an
    11-bit standard-range id (<= 0x7FF) -- such an id has all-zero pf/ps/dp
    bits under the PGN formula, which used to resolve to PGN 0 for almost any
    short id, mislabeling unrelated non-J1939 traffic as whatever message
    owns PGN 0 (e.g. TSC1)."""

    def setUp(self):
        # priority 3, pf=0, ps=0 -> PGN 0 (TSC1's real-world PGN), same as a
        # real extended J1939 frame would look like.
        self.tsc1_id = (3 << 26)
        dbc_text = f"""VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ {self.tsc1_id | 0x80000000} TSC1: 8 ECU
 SG_ TSC1TransRate : 0|8@1+ (1,0) [0|255] "unit" ECU
"""
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dbc_text)
        self.mgr = DbcManager()
        entry = self.mgr.load_dbc(self.path)
        self.mgr.set_entry_mode(entry.name, "j1939")

    def tearDown(self):
        os.remove(self.path)

    def test_short_standard_ids_do_not_resolve_to_tsc1(self):
        for short_id in ("006", "007", "107", "207", "307", "407"):
            self.assertIsNone(self.mgr.resolve_message_name(short_id), short_id)

    def test_real_extended_pgn_zero_frame_still_resolves_to_tsc1(self):
        self.assertEqual(self.mgr.resolve_message_name(f"{self.tsc1_id:X}"), "TSC1")


if __name__ == "__main__":
    unittest.main()
