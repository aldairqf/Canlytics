from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QCheckBox

from models.plugin import PluginRecord
from views.settings.plugins_dialog import PluginsDialog


class FakePluginViewModel(QObject):
    plugins_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.records = (
            PluginRecord("sample", "Sample Plugin", "1.0", "folder", False, False),
            PluginRecord("broken", "Broken Plugin", "1.0", "package", True, False, "ImportError: missing dependency"),
        )
        self.toggles: list[tuple[str, bool]] = []

    def refresh(self) -> tuple[PluginRecord, ...]:
        return self.records

    def plugin_directories(self) -> tuple[Path, ...]:
        return (Path("plugins"),)

    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[PluginRecord, ...]:
        self.toggles.append((plugin_id, enabled))
        self.records = tuple(
            PluginRecord(record.id, record.name, record.version, record.source, enabled, enabled)
            if record.id == plugin_id else record
            for record in self.records
        )
        self.plugins_changed.emit(self.records)
        return self.records


class PluginsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_plugins_show_status_and_toggle_through_viewmodel(self) -> None:
        vm = FakePluginViewModel()
        dialog = PluginsDialog(vm)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.table.item(0, 0).text(), "Sample Plugin")
        self.assertEqual(dialog.table.item(1, 3).text(), "ImportError: missing dependency")
        checkbox = dialog.table.cellWidget(0, 4).findChild(QCheckBox)
        checkbox.setChecked(True)
        self.assertEqual(vm.toggles, [("sample", True)])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
