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


if __name__ == "__main__":
    unittest.main()
