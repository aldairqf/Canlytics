from __future__ import annotations

import logging
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.app_logging import configure_logging
from services.app_paths import resolve_state_dir
from services.session_state import SessionStateStore
from tests import TEST_STATE_DIR


def _migration_enabled(test: unittest.TestCase) -> None:
    test.enterContext(patch.dict(os.environ, {"CANLYTICS_STATE_MIGRATION": "1"}))


class DefaultStateDirectoryTests(unittest.TestCase):
    def test_test_suite_state_root_is_isolated_under_its_temp_directory(self) -> None:
        resolved = resolve_state_dir()
        self.assertTrue(resolved.is_relative_to(TEST_STATE_DIR))

    def test_default_store_and_logging_do_not_use_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary) / "arbitrary"
            cwd.mkdir()
            state = Path(temporary) / "user-state"
            root_logger = logging.getLogger()
            previous_handlers = list(root_logger.handlers)
            with patch.dict(os.environ, {"CANLYTICS_STATE_DIR": str(state)}):
                with patch("pathlib.Path.cwd", return_value=cwd):
                    store = SessionStateStore()
                    handler = configure_logging(store.root)
            try:
                self.assertEqual(store.root, state)
                self.assertTrue((state / "logs" / "canlytics.log").exists())
                self.assertFalse((cwd / ".canlytics_state").exists())
            finally:
                for log_handler in list(root_logger.handlers):
                    if log_handler not in previous_handlers:
                        root_logger.removeHandler(log_handler)
                        log_handler.close()

    def test_environment_directory_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "configured"
            with patch.dict(os.environ, {"CANLYTICS_STATE_DIR": str(target), "APPDATA": str(Path(temporary) / "roaming")}):
                self.assertEqual(resolve_state_dir(), target)

    def test_windows_uses_appdata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            appdata = Path(temporary) / "Roaming"
            with patch.dict(os.environ, {"APPDATA": str(appdata), "CANLYTICS_STATE_MIGRATION": "0"}, clear=True):
                with patch("services.app_paths.sys.platform", "win32"):
                    self.assertEqual(resolve_state_dir(), appdata / "Canlytics" / "state")

    def test_migration_copies_legacy_without_removing_it_and_runs_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / ".canlytics_state"
            old.mkdir()
            (old / "session.json").write_text("{}", encoding="utf-8")
            target = base / "new-state"
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(old,)):
                    self.assertEqual(resolve_state_dir(), target)
                    self.assertEqual(resolve_state_dir(), target)
            self.assertTrue((old / "session.json").exists())
            self.assertEqual((target / "session.json").read_text(encoding="utf-8"), "{}")

    def test_existing_empty_destination_migrates_legacy_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / ".canlytics_state"
            old.mkdir()
            (old / "session.json").write_text('{"theme": "Light"}', encoding="utf-8")
            target = base / "new-state"
            target.mkdir()
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(old,)):
                    self.assertEqual(resolve_state_dir(), target)
            self.assertEqual(json.loads((target / "session.json").read_text(encoding="utf-8")), {"theme": "Light"})
            self.assertTrue((old / "session.json").exists())

    def test_existing_session_file_is_never_overwritten_or_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / ".canlytics_state"
            old.mkdir()
            (old / "session.json").write_text('{"theme": "Light"}', encoding="utf-8")
            target = base / "new-state"
            target.mkdir()
            (target / "session.json").write_text('{"theme": "Dark"}', encoding="utf-8")
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(old,)):
                    self.assertEqual(resolve_state_dir(), target)
            self.assertEqual(json.loads((target / "session.json").read_text(encoding="utf-8")), {"theme": "Dark"})
            self.assertFalse((target / "unused.txt").exists())
            self.assertTrue((old / "session.json").exists())

    def test_migration_selects_newest_session_candidate_and_caches_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            logs_only = base / "cwd" / ".canlytics_state"
            logs_only.joinpath("logs").mkdir(parents=True)
            (logs_only / "logs" / "canlytics.log").write_text("old log", encoding="utf-8")
            executable_state = base / "exe" / ".canlytics_state"
            executable_state.mkdir(parents=True)
            (executable_state / "session.json").write_text('{"theme": "Light"}', encoding="utf-8")
            target = base / "new-state"
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(logs_only, executable_state)):
                    self.assertEqual(resolve_state_dir(), target)
                self.assertEqual(json.loads((target / "session.json").read_text(encoding="utf-8")), {"theme": "Light"})
                self.assertFalse((target / "logs" / "canlytics.log").exists())
                marker = json.loads((target / "migration.json").read_text(encoding="utf-8"))
                self.assertEqual(Path(marker["source"]), executable_state)
                with patch("services.app_paths._legacy_state_roots", side_effect=AssertionError("reran migration")):
                    self.assertEqual(resolve_state_dir(), target)
                from services import app_paths

                app_paths._RESOLVED_ROOTS.pop(str(target), None)
                with patch("services.app_paths._legacy_state_roots", side_effect=AssertionError("marker ignored")):
                    self.assertEqual(resolve_state_dir(), target)

    def test_migration_rewrites_legacy_dbc_paths_and_copies_files_without_tree_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            legacy = base / "legacy" / ".canlytics_state"
            dbc = legacy / "dbcs" / "engine.dbc"
            dbc.parent.mkdir(parents=True)
            dbc.write_text('VERSION ""', encoding="utf-8")
            (legacy / "session.json").write_text(
                json.dumps({"dbcs": [{"path": str(dbc), "name": "Engine"}]}), encoding="utf-8"
            )
            target = base / "new-state"
            expected_dbc = target / "dbcs" / "engine.dbc"
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(legacy,)):
                    with patch("services.app_paths.shutil.copytree", side_effect=AssertionError("tree staging")):
                        resolve_state_dir()
            state = json.loads((target / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(state["dbcs"][0]["path"]), expected_dbc)
            self.assertTrue(expected_dbc.exists())
            self.assertEqual(dbc.read_text(encoding="utf-8"), 'VERSION ""')

    def test_newest_valid_legacy_session_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            older = base / "older" / ".canlytics_state"
            newer = base / "newer" / ".canlytics_state"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "session.json").write_text('{"theme": "Light"}', encoding="utf-8")
            (newer / "session.json").write_text('{"theme": "Dark"}', encoding="utf-8")
            os.utime(older / "session.json", (1_000_000_000, 1_000_000_000))
            os.utime(newer / "session.json", (1_700_000_000, 1_700_000_000))
            target = base / "new-state"
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(older, newer)):
                    resolve_state_dir()
            marker = json.loads((target / "migration.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(marker["source"]), newer)
            self.assertEqual(json.loads((target / "session.json").read_text(encoding="utf-8")), {"theme": "Dark"})

    def test_failed_legacy_file_copy_skips_session_but_records_partial_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            legacy = base / "legacy"
            legacy.mkdir()
            (legacy / "session.json").write_text("{}", encoding="utf-8")
            (legacy / "cannot-copy.bin").write_bytes(b"legacy")
            target = base / "new-state"
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._legacy_state_roots", return_value=(legacy,)):
                    with patch("services.app_paths.shutil.copy2", side_effect=OSError("copy denied")):
                        resolve_state_dir()
            self.assertFalse((target / "session.json").exists())
            marker = json.loads((target / "migration.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "partial")
            self.assertEqual((legacy / "cannot-copy.bin").read_bytes(), b"legacy")

    def test_concurrent_resolvers_run_only_one_migration(self) -> None:
        from services import app_paths

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new-state"
            entered_migration = threading.Event()
            release_migration = threading.Event()
            candidate_calls = []

            def blocked_find(destination: Path) -> None:
                candidate_calls.append(destination)
                entered_migration.set()
                release_migration.wait(timeout=2)
                return None

            errors = []
            _migration_enabled(self)
            with patch("services.app_paths._default_state_root", return_value=target):
                with patch("services.app_paths._find_legacy_state", side_effect=blocked_find):
                    first = threading.Thread(target=lambda: self._capture_resolution(errors))
                    first.start()
                    self.assertTrue(entered_migration.wait(timeout=2))
                    second = threading.Thread(target=lambda: self._capture_resolution(errors))
                    second.start()
                    second.join(timeout=1)
                    self.assertFalse(second.is_alive())
                    release_migration.set()
                    first.join(timeout=2)
            self.assertEqual(errors, [])
            self.assertEqual(len(candidate_calls), 1)
            self.assertTrue((target / "migration.json").exists())

    def _capture_resolution(self, errors: list[Exception]) -> None:
        try:
            resolve_state_dir()
        except Exception as exc:
            errors.append(exc)

    def test_migration_is_disabled_in_test_environment(self) -> None:
        self.assertEqual(os.environ.get("CANLYTICS_STATE_MIGRATION"), "0")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / "legacy"
            old.mkdir()
            (old / "session.json").write_text("{}", encoding="utf-8")
            target = base / "new-state"
            with patch.dict(os.environ, {"CANLYTICS_STATE_MIGRATION": "0", "CANLYTICS_STATE_DIR": str(target)}):
                with patch("services.app_paths._legacy_state_roots", return_value=(old,)):
                    self.assertEqual(resolve_state_dir(), target)
            self.assertFalse((target / "session.json").exists())
            marker = json.loads((target / "migration.json").read_text(encoding="utf-8"))
            self.assertIsNone(marker["source"])

    def test_resolution_survives_default_path_discovery_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch("services.app_paths._default_state_root", side_effect=OSError("no home")):
                with patch("services.app_paths.tempfile.gettempdir", return_value=temporary):
                    resolved = resolve_state_dir()
            self.assertTrue(resolved.is_dir())

    def test_uncreatable_selected_directory_uses_temp_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "blocked"
            original_mkdir = Path.mkdir

            def guarded_mkdir(path: Path, *args: object, **kwargs: object) -> None:
                if path == selected:
                    raise PermissionError("blocked")
                original_mkdir(path, *args, **kwargs)

            with patch("services.app_paths._default_state_root", return_value=selected):
                with patch("services.app_paths.Path.mkdir", guarded_mkdir):
                    with patch("services.app_paths.tempfile.gettempdir", return_value=temporary):
                        result = resolve_state_dir()
            self.assertNotEqual(result, selected)
            self.assertTrue(result.is_dir())


if __name__ == "__main__":
    unittest.main()
