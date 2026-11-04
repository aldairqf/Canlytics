from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtWidgets import QApplication

from viewmodels.plugin_viewmodel import PluginViewModel, _PluginAnalysis, _PluginContext


class _Connection(QObject):
    chunk_ready = QtSignal(object)


class _StreamingHost(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.connection_vm = _Connection()


class _LifetimeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in tuple(self._callbacks):
            callback()


class _Lifetime:
    def __init__(self) -> None:
        self.destroyed = _LifetimeSignal()


class PluginViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_refresh_loads_persisted_enabled_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugins = root / "plugins"
            plugin = plugins / "persisted"
            plugin.mkdir(parents=True)
            (plugin / "plugin.toml").write_text(
                '[plugin]\nid="persisted"\nname="Persisted"\nversion="1.0"\n'
                'api_version=1\nentry_point="plugin:register"\n',
                encoding="utf-8",
            )
            (plugin / "plugin.py").write_text(
                "def register(api, context):\n"
                "    api.register_log_importer('loaded', lambda path: path)\n",
                encoding="utf-8",
            )
            (root / "plugins.json").write_text(json.dumps({"enabled": {"persisted": True}}), encoding="utf-8")
            host = SimpleNamespace(
                session_state=SimpleNamespace(root=root),
                analysis_context_vm=SimpleNamespace(
                    set_plugin_actions=lambda *_args: None,
                    set_marker_provider=lambda *_args: None,
                ),
            )
            with patch.dict(os.environ, {"CANLYTICS_PLUGINS_DIR": str(plugins)}):
                viewmodel = PluginViewModel(host)
                viewmodel.refresh()
                records = viewmodel._manager.records()
                self.assertTrue(records[0].loaded)
                self.assertEqual(list(viewmodel._manager.extensions("log_importers")), ["persisted:loaded"])
                viewmodel.shutdown()

    def test_summary_filters_frames_to_the_requested_can_id(self) -> None:
        dataframe = pl.DataFrame({
            "TS": [0.0, 1.0],
            "Bus": ["can0", "can0"],
            "ID": ["123", "456"],
            "DATA": ["01", "02"],
            "LEN": [1, 1],
            "D0": [1, 2],
        })
        summary = _PluginAnalysis().summarize(dataframe, "123")
        self.assertEqual(summary["Frames"], 1)

    def test_chunk_subscription_disconnects_when_its_lifetime_ends(self) -> None:
        host = _StreamingHost()
        context = _PluginContext(host).scoped("sample")
        lifetime = _Lifetime()
        seen = []
        chunk = pl.DataFrame({"ID": ["123"]})
        context.subscribe_live_chunks(seen.append, lifetime=lifetime)

        host.connection_vm.chunk_ready.emit(chunk)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].to_dicts(), chunk.to_dicts())
        self.assertIsNot(seen[0], chunk)

        lifetime.destroyed.emit()
        host.connection_vm.chunk_ready.emit(chunk)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
