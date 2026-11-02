from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from models.mux_config import MuxConfigEntry
from services.session_state import SessionStateStore
from viewmodels.main_window_viewmodel import MainWindowViewModel
from viewmodels.mux_configuration_viewmodel import MuxConfigurationViewModel


class MuxConfigurationViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SessionStateStore(root=Path(self._tmp.name))

    def test_restores_saved_configuration_and_returns_a_copy(self) -> None:
        expected = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))]
        self.store.set_mux_configuration(expected)

        vm = MuxConfigurationViewModel(self.store)
        configs = vm.configs
        configs.clear()

        self.assertEqual(vm.configs, expected)

    def test_updates_persist_before_emitting_shared_state(self) -> None:
        vm = MuxConfigurationViewModel(self.store)
        published = []
        vm.configuration_changed.connect(published.append)
        expected = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0, 1))]

        vm.set_configuration(expected)

        self.assertEqual(published, [expected])
        self.assertEqual(self.store.get_mux_configuration(), expected)

    def test_rejects_invalid_configuration_without_changing_saved_state(self) -> None:
        original = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))]
        self.store.set_mux_configuration(original)
        vm = MuxConfigurationViewModel(self.store)

        with self.assertRaises(ValueError):
            vm.set_configuration([MuxConfigEntry(can_id="XYZ", length=8, mux_bytes=(0,))])

        self.assertEqual(vm.configs, original)
        self.assertEqual(self.store.get_mux_configuration(), original)

    def test_rejects_conflicting_rules_for_same_id_and_length(self) -> None:
        vm = MuxConfigurationViewModel(self.store)

        with self.assertRaises(ValueError):
            vm.set_configuration([
                MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,)),
                MuxConfigEntry(can_id="100", length=8, mux_bytes=(1,)),
            ])

        self.assertEqual(vm.configs, [])
        self.assertEqual(self.store.get_mux_configuration(), [])

    def test_rejects_fractional_length_and_mux_indexes(self) -> None:
        vm = MuxConfigurationViewModel(self.store)

        for config in (
            MuxConfigEntry(can_id="100", length=1.5, mux_bytes=(0,)),
            MuxConfigEntry(can_id="100", length=8, mux_bytes=(0.5,)),
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                vm.set_configuration([config])

        self.assertEqual(vm.configs, [])

    def test_main_window_publishes_one_configuration_to_all_consumers(self) -> None:
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=self.store):
            root = MainWindowViewModel()
        expected = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))]
        try:
            root.mux_configuration_vm.set_configuration(expected)
            self.assertEqual(root.real_time_analysis_vm.mux_configs, expected)
            self.assertEqual(root.analyze_data_vm.mux_configs, expected)
            self.assertEqual(root.candidate_interpretations_vm.mux_configs, expected)
            self.assertEqual(root.range_diff_vm.mux_configs, expected)
        finally:
            root.shutdown()


if __name__ == "__main__":
    unittest.main()
