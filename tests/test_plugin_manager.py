from __future__ import annotations

import tempfile
import unittest
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from canlytics_sdk import PluginAPI, PluginDescriptor, SDK_API_VERSION
from services.plugin_manager import PluginManager


class PluginManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plugins = self.root / "plugins"
        self.plugins.mkdir()
        self.state = self.root / "state" / "plugins.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_plugin(self, plugin_id: str, source: str, *, api_version: int = SDK_API_VERSION) -> Path:
        folder = self.plugins / plugin_id
        folder.mkdir()
        (folder / "plugin.toml").write_text(
            "[plugin]\n"
            f'id = "{plugin_id}"\n'
            f'name = "{plugin_id.title()}"\n'
            'version = "1.0.0"\n'
            f"api_version = {api_version}\n"
            'entry_point = "plugin:register"\n',
            encoding="utf-8",
        )
        (folder / "plugin.py").write_text(source, encoding="utf-8")
        return folder

    def _manager(self, entry_points_provider=None) -> PluginManager:
        kwargs = {"entry_points_provider": entry_points_provider} if entry_points_provider is not None else {}
        manager = PluginManager(self.state, plugin_dirs=(self.plugins,), **kwargs)
        self.addCleanup(manager.shutdown)
        return manager

    def test_folder_plugins_start_disabled_and_load_registered_extensions(self) -> None:
        self._write_plugin(
            "sample",
            "def register(api, context):\n"
            "    api.register_log_exporter('csv', lambda df, path: path)\n",
        )
        manager = self._manager()
        records = manager.discover()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].enabled)
        self.assertEqual(manager.extensions("log_exporters"), {})

        enabled = manager.set_enabled("sample", True, context=object())
        self.assertTrue(enabled.loaded)
        self.assertEqual(
            list(manager.extensions("log_exporters")),
            ["sample:csv"],
        )

        disabled = manager.set_enabled("sample", False)
        self.assertFalse(disabled.enabled)
        self.assertEqual(manager.extensions("log_exporters"), {})

    def test_module_relative_imports_work_inside_plugin_folder(self) -> None:
        folder = self._write_plugin(
            "with-helper",
            "from .helper import VALUE\n"
            "def register(api, context):\n"
            "    api.register_dbc_source(VALUE, lambda: VALUE)\n",
        )
        (folder / "helper.py").write_text('VALUE = "helper-source"\n', encoding="utf-8")
        manager = self._manager()
        manager.discover()
        self.assertTrue(manager.set_enabled("with-helper", True, context=object()).loaded)
        self.assertEqual(list(manager.extensions("dbc_sources")), ["with-helper:helper-source"])

    def test_bad_api_version_is_reported_without_blocking_valid_plugins(self) -> None:
        self._write_plugin("old-api", "def register(api, context): pass\n", api_version=0)
        bool_api = self._write_plugin("bool-api", "def register(api, context): pass\n")
        manifest = bool_api / "plugin.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("api_version = 1", "api_version = true"), encoding="utf-8")
        self._write_plugin("good", "def register(api, context): pass\n")
        manager = self._manager()
        records = {record.id: record for record in manager.discover()}
        self.assertIn("Unsupported plugin API version", records["old-api"].error)
        self.assertIn("Unsupported plugin API version", records["bool-api"].error)
        self.assertEqual(records["good"].error, "")
        self.assertFalse(manager.set_enabled("good", True, context=object()).error)

    def test_plugin_registration_failure_is_isolated_and_persisted(self) -> None:
        self._write_plugin("broken", "def register(api, context): raise RuntimeError('bad plugin')\n")
        self._write_plugin(
            "healthy",
            "def register(api, context):\n"
            "    api.register_log_importer('sample', lambda path: path)\n",
        )
        manager = self._manager()
        manager.discover()
        failed = manager.set_enabled("broken", True, context=object())
        self.assertIn("bad plugin", failed.error)
        loaded = manager.set_enabled("healthy", True, context=object())
        self.assertTrue(loaded.loaded)

        restarted = self._manager()
        records = {record.id: record for record in restarted.discover()}
        self.assertTrue(records["broken"].enabled)
        self.assertTrue(records["healthy"].enabled)

    def test_entry_point_requires_matching_plugin_descriptor(self) -> None:
        callback = lambda api, context: None
        descriptor = PluginDescriptor("package-plugin", "Package Plugin", "2.0", SDK_API_VERSION, callback)
        entry_point = SimpleNamespace(name="package-plugin", value="plugins:entry", dist=SimpleNamespace(version="2.0"), load=lambda: descriptor)
        manager = self._manager(lambda: [entry_point])
        manager.discover()
        record = manager.set_enabled("package-plugin", True, context=object())
        self.assertTrue(record.loaded)

    def test_target_installed_packages_are_discovered_and_imported(self) -> None:
        dist_info = self.plugins / "sample_plugin-1.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: sample-plugin\nVersion: 1.0\n", encoding="utf-8")
        (dist_info / "entry_points.txt").write_text(
            "[canlytics.plugins]\npackage-plugin = package_plugin:PLUGIN\n",
            encoding="utf-8",
        )
        (self.plugins / "package_plugin.py").write_text(
            "from canlytics_sdk import PluginDescriptor, SDK_API_VERSION\n"
            "def register(api, context):\n"
            "    api.register_log_exporter('target', lambda df, path: path)\n"
            "PLUGIN = PluginDescriptor('package-plugin', 'Package Plugin', '1.0', SDK_API_VERSION, register)\n",
            encoding="utf-8",
        )
        manager = self._manager()
        self.assertEqual([record.id for record in manager.discover()], ["package-plugin"])
        self.assertTrue(manager.set_enabled("package-plugin", True, context=object()).loaded)
        self.assertEqual(list(manager.extensions("log_exporters")), ["package-plugin:target"])

    def test_entry_point_rejects_unsupported_descriptor(self) -> None:
        descriptor = PluginDescriptor("bad-package", "Bad Package", "1.0", 99, lambda api, context: None)
        entry_point = SimpleNamespace(name="bad-package", value="plugins:entry", dist=None, load=lambda: descriptor)
        manager = self._manager(lambda: [entry_point])
        manager.discover()
        record = manager.set_enabled("bad-package", True, context=object())
        self.assertIn("API version", record.error)

    def test_duplicate_extension_names_fail_plugin_activation(self) -> None:
        self._write_plugin(
            "duplicate",
            "def register(api, context):\n"
            "    api.register_dbc_source('same', lambda: None)\n"
            "    api.register_dbc_source('same', lambda: None)\n",
        )
        manager = self._manager()
        manager.discover()
        record = manager.set_enabled("duplicate", True, context=object())
        self.assertIn("already registered", record.error)
        self.assertEqual(manager.extensions("dbc_sources"), {})

    def test_interactive_extensions_and_live_chunks_are_removed_on_disable(self) -> None:
        self._write_plugin(
            "interactive",
            "def register(api, context):\n"
            "    api.register_window('viewer', lambda context: object())\n"
            "    api.register_send_to_action('inspect', lambda context: None)\n"
            "    api.register_context_action('annotate', lambda context: None)\n"
            "    api.register_live_chunk_listener(lambda chunk: None)\n",
        )
        manager = self._manager()
        manager.discover()
        self.assertTrue(manager.set_enabled("interactive", True, context=object()).loaded)
        self.assertEqual(set(manager.ui_extensions("windows")), {"interactive:viewer"})
        self.assertEqual(set(manager.ui_extensions("send_to_actions")), {"interactive:inspect"})
        self.assertEqual(set(manager.ui_extensions("context_actions")), {"interactive:annotate"})
        self.assertEqual(len(manager.live_chunk_listeners()), 1)

        manager.set_enabled("interactive", False)

        self.assertEqual(manager.ui_extensions("windows"), {})
        self.assertEqual(manager.live_chunk_listeners(), ())

    def test_import_folder_copies_plugin_into_configured_directory_disabled(self) -> None:
        source = self.root / "download" / "import-me"
        source.mkdir(parents=True)
        (source / "plugin.toml").write_text(
            '[plugin]\nid="imported-plugin"\nname="Imported"\nversion="1.0"\n'
            'api_version=1\nentry_point="plugin:register"\n',
            encoding="utf-8",
        )
        (source / "plugin.py").write_text("def register(api, context): pass\n", encoding="utf-8")
        manager = self._manager()

        record = manager.import_folder(source)

        installed = self.plugins / "imported-plugin"
        self.assertTrue((installed / "plugin.toml").is_file())
        self.assertTrue((installed / "plugin.py").is_file())
        self.assertTrue(record.valid)
        self.assertFalse(record.enabled)
        self.assertFalse(record.loaded)
        self.assertTrue(any(item.id == "imported-plugin" for item in manager.records()))

    def test_import_folder_rejects_missing_manifest_without_copying(self) -> None:
        source = self.root / "not-a-plugin"
        source.mkdir()
        manager = self._manager()

        with self.assertRaisesRegex(ValueError, "plugin.toml"):
            manager.import_folder(source)

        self.assertFalse((self.plugins / "not-a-plugin").exists())

    def test_import_archive_extracts_root_manifest_and_installs_disabled(self) -> None:
        archive_path = self.root / "bundle.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "plugin.toml",
                '[plugin]\nid="zip-plugin"\nname="ZIP Plugin"\nversion="1.0"\n'
                'api_version=1\nentry_point="plugin:register"\n',
            )
            archive.writestr("plugin.py", "def register(api, context): pass\n")
        manager = self._manager()

        record = manager.import_archive(archive_path)

        self.assertTrue((self.plugins / "zip-plugin" / "plugin.py").is_file())
        self.assertTrue(record.valid)
        self.assertFalse(record.enabled)

    def test_import_archive_rejects_path_traversal_and_symlinks(self) -> None:
        traversal = self.root / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr("../outside.py", "malicious = True")
        colon_path = self.root / "colon.zip"
        with zipfile.ZipFile(colon_path, "w") as archive:
            archive.writestr("folder/plugin:stream.py", "malicious = True")
        symlink = self.root / "symlink.zip"
        info = zipfile.ZipInfo("plugin/link")
        info.external_attr = stat.S_IFLNK << 16
        with zipfile.ZipFile(symlink, "w") as archive:
            archive.writestr(info, "../../outside")
        manager = self._manager()

        with self.assertRaisesRegex(ValueError, "unsafe path"):
            manager.import_archive(traversal)
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            manager.import_archive(colon_path)
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            manager.import_archive(symlink)
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_import_archive_rejects_excessive_members_and_expanded_size(self) -> None:
        archive_path = self.root / "oversized.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("plugin.toml", "1234")
            archive.writestr("plugin.py", "")
        manager = self._manager()

        with patch("services.plugin_manager._MAX_PLUGIN_ARCHIVE_MEMBERS", 1):
            with self.assertRaisesRegex(ValueError, "too many files"):
                manager.import_archive(archive_path)
        with patch("services.plugin_manager._MAX_PLUGIN_ARCHIVE_MEMBER_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "oversized file"):
                manager.import_archive(archive_path)
        with patch("services.plugin_manager._MAX_PLUGIN_ARCHIVE_TOTAL_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "too large"):
                manager.import_archive(archive_path)

    def test_failed_folder_copy_removes_staging_directory(self) -> None:
        source = self.root / "download" / "source"
        source.mkdir(parents=True)
        (source / "plugin.toml").write_text(
            '[plugin]\nid="source"\nname="Source"\nversion="1.0"\n'
            'api_version=1\nentry_point="plugin:register"\n',
            encoding="utf-8",
        )
        (source / "plugin.py").write_text("def register(api, context): pass\n", encoding="utf-8")
        manager = self._manager()

        def fail_after_creating_destination(_source, destination):
            Path(destination).mkdir()
            raise OSError("disk full")

        with patch("services.plugin_manager.shutil.copytree", side_effect=fail_after_creating_destination):
            with self.assertRaisesRegex(OSError, "disk full"):
                manager.import_folder(source)

        self.assertFalse((self.plugins / "source").exists())
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_import_folder_rejects_symbolic_links(self) -> None:
        source = self.root / "download" / "linked"
        source.mkdir(parents=True)
        (source / "plugin.toml").write_text(
            '[plugin]\nid="linked"\nname="Linked"\nversion="1.0"\n'
            'api_version=1\nentry_point="plugin:register"\n',
            encoding="utf-8",
        )
        plugin_module = source / "plugin.py"
        plugin_module.write_text("def register(api, context): pass\n", encoding="utf-8")
        manager = self._manager()
        with patch.object(Path, "is_symlink", lambda path: path == plugin_module):
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                manager.import_folder(source)
        self.assertFalse((self.plugins / "linked").exists())

    def test_import_folder_rejects_a_symbolic_link_as_the_source(self) -> None:
        source = self.root / "download" / "plugin"
        source.mkdir(parents=True)
        (source / "plugin.toml").write_text(
            '[plugin]\nid="linked-root"\nname="Linked Root"\nversion="1.0"\n'
            'api_version=1\nentry_point="plugin:register"\n',
            encoding="utf-8",
        )
        linked_source = self.root / "download" / "plugin-link"
        manager = self._manager()
        with patch.object(Path, "is_symlink", lambda path: path == linked_source):
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                manager.import_folder(linked_source)

    def test_state_write_failure_is_reported_without_crashing_plugin_load(self) -> None:
        self._write_plugin("persist-warning", "def register(api, context): pass\n")
        state_temp = self.state.with_suffix(self.state.suffix + ".tmp")
        state_temp.mkdir(parents=True)
        manager = self._manager()
        manager.discover()
        record = manager.set_enabled("persist-warning", True, context=object())
        self.assertTrue(record.loaded)
        self.assertIn("Could not save plugin preference", record.error)


if __name__ == "__main__":
    unittest.main()
