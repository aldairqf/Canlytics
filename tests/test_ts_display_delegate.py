from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from views.table.ts_display_delegate import TsDisplayDelegate


class TsDisplayDelegateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_epoch_timestamp_uses_three_decimals(self) -> None:
        delegate = TsDisplayDelegate("none")

        self.assertEqual(delegate.displayText(12.3, None), "12.300")
        self.assertEqual(delegate.displayText("12.3456789", None), "12.346")

    def test_timezone_timestamp_uses_three_decimals(self) -> None:
        delegate = TsDisplayDelegate("UTC")

        self.assertEqual(
            delegate.displayText(1.234567, None),
            "00:00:01.235",
        )

    def test_none_timestamp_is_blank(self) -> None:
        delegate = TsDisplayDelegate("none")

        self.assertEqual(delegate.displayText(None, None), "")
