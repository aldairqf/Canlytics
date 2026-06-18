"""Characterization tests over the optional real DBC/log fixtures.

These exercise the real loaders against real files dropped under
``tests/fixtures/`` and assert format-agnostic invariants that hold for any
valid DBC / CAN log. When no fixtures are present every test skips, so the
suite stays green in a clean checkout. See tests/fixtures/README.md.
"""

from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from services.can_data_parser import FRAME_SCHEMA
from services.can_log import CANLog
from services.dbc_manager import DbcManager
from tests.fixture_paths import dbc_files, log_files

# DbcManager is a QObject; ensure an application object exists.
_app = QCoreApplication.instance() or QCoreApplication([])


@unittest.skipUnless(dbc_files(), "No DBC fixtures in tests/fixtures/dbc/")
class RealDbcFixtureTests(unittest.TestCase):
    def test_loads_with_messages(self):
        for path in dbc_files():
            with self.subTest(dbc=path.name):
                mgr = DbcManager()
                mgr.load_dbc(str(path))
                self.assertTrue(
                    mgr.list_entries(),
                    f"{path.name} loaded no DBC entries",
                )


@unittest.skipUnless(log_files(), "No log fixtures in tests/fixtures/logs/")
class RealLogFixtureTests(unittest.TestCase):
    def test_parses_to_frame_schema(self):
        for path in log_files():
            with self.subTest(log=path.name):
                df = CANLog(path).load()
                # Schema contract: every FRAME_SCHEMA column present, no extras.
                self.assertEqual(set(df.columns), set(FRAME_SCHEMA))
                self.assertFalse(
                    df.is_empty(),
                    f"{path.name} parsed to zero frames (format not recognized?)",
                )

    def test_ids_are_uppercase_hex(self):
        for path in log_files():
            with self.subTest(log=path.name):
                df = CANLog(path).load()
                if df.is_empty():
                    continue
                ids = df["ID"].to_list()
                for raw_id in ids[:200]:
                    self.assertEqual(raw_id, raw_id.upper())
                    int(raw_id, 16)  # raises if not valid hex

    def test_normalized_time_anchors_first_frame_to_zero(self):
        # load() subtracts the FIRST row's TS (not the min) and does not sort,
        # so the invariant is "first frame == 0", not "min == 0".
        for path in log_files():
            with self.subTest(log=path.name):
                df = CANLog(path).load(normalize_time=True)
                if df.is_empty():
                    continue
                self.assertAlmostEqual(float(df["TS"][0]), 0.0)


if __name__ == "__main__":
    unittest.main()
