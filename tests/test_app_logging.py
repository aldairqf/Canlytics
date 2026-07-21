"""Characterization tests for services/app_logging.py (Debug Mode/Logging, Phase 1).

QtLogHandler multiply-inherits logging.Handler and QObject -- pinning that the
combination actually works under PySide6 (not just in theory) is the main risk
this module carries.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from services.app_logging import configure_logging, is_debug_enabled, set_debug_enabled

_app = QApplication.instance() or QApplication(sys.argv)


class ConfigureLoggingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # LIFO cleanup order: close/remove handlers (releases the file lock)
        # before removing the temp dir, or Windows refuses to delete the open file.
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._cleanup_handlers)
        self.handler = configure_logging(Path(self._tmp.name), level=logging.INFO)
        self.logger = logging.getLogger("test.app_logging")

    def _cleanup_handlers(self):
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

    def test_default_level_is_info(self):
        self.assertFalse(is_debug_enabled())

    def test_debug_message_is_dropped_below_debug_level(self):
        received = []
        self.handler.record_emitted.connect(received.append)
        self.logger.debug("should not appear")
        self.assertEqual(received, [])

    def test_info_message_passes_at_the_default_level(self):
        received = []
        self.handler.record_emitted.connect(received.append)
        self.logger.info("visible by default")
        self.assertEqual(len(received), 1)
        self.assertIn("visible by default", received[0])

    def test_set_debug_enabled_raises_the_root_level(self):
        set_debug_enabled(True)
        self.assertTrue(is_debug_enabled())
        received = []
        self.handler.record_emitted.connect(received.append)
        self.logger.debug("now visible")
        self.assertEqual(len(received), 1)
        self.assertIn("now visible", received[0])

    def test_set_debug_enabled_false_restores_info(self):
        set_debug_enabled(True)
        set_debug_enabled(False)
        self.assertFalse(is_debug_enabled())

    def test_record_written_to_rotating_file(self):
        self.logger.warning("goes to disk")
        log_path = Path(self._tmp.name) / "logs" / "canlytics.log"
        self.assertTrue(log_path.exists())
        self.assertIn("goes to disk", log_path.read_text(encoding="utf-8"))

    def test_qt_log_handler_receives_the_same_record_as_the_file(self):
        received = []
        self.handler.record_emitted.connect(received.append)
        self.logger.warning("mirrored")
        self.assertEqual(len(received), 1)
        self.assertIn("WARNING", received[0])
        self.assertIn("test.app_logging", received[0])


if __name__ == "__main__":
    unittest.main()
