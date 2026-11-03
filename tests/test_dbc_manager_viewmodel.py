from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from services.dbc_manager import DbcManager
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel


MINIMAL_DBC = '''VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 TestMsg: 8 ECU
 SG_ TestSig : 0|8@1+ (1,0) [0|255] "" ECU
'''


class DbcManagerViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_service_import_does_not_load_qt(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import services.dbc_manager; assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)",
            ],
            cwd=repository,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_adapter_emits_for_catalog_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dbc"
            path.write_text(MINIMAL_DBC, encoding="utf-8")
            manager = DbcManagerViewModel()
            notifications: list[bool] = []
            manager.entries_changed.connect(lambda: notifications.append(True))

            entry = manager.load_dbc(str(path))
            manager.set_active({entry.name})
            manager.set_entry_mode(entry.name, "exact")
            manager.update_entry_database(entry.name, DbcManager().load_database(str(path)))

        self.assertEqual(len(notifications), 4)
        self.assertEqual(manager.resolve_message_name("100"), "TestMsg")


if __name__ == "__main__":
    unittest.main()
