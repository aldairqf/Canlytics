from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import pyqtgraph as pg

from config.theme import THEMES, apply_theme
from views.candidate_interpretations_window import _category_color
from views.signal.derived_signal_dialog import _formula_reference_html
from views.plot.cursor_controller import CursorController
from services.candidate_interpretations import SignalCategory


class SemanticThemeTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_cursor_controller_disconnects_theme_signal_on_dispose(self) -> None:
        plot = pg.PlotWidget()
        controller = CursorController(plot, get_plot_data=lambda: [], format_time=str)
        self.assertIsNotNone(controller._theme_app)
        controller.dispose()
        self.assertIsNone(controller._theme_app)
        apply_theme(self.app, "Light")
        apply_theme(self.app, "Dark")
        self.assertTrue(controller.cursor_line.isVisible() is False)
        plot.close()

    def test_candidate_category_and_formula_reference_use_active_theme_tokens(self) -> None:
        for name, theme in THEMES.items():
            apply_theme(self.app, name)
            self.assertEqual(_category_color(SignalCategory.COUNTER), theme.candidate_counter)
            self.assertEqual(_category_color(SignalCategory.BINARY), theme.candidate_binary)
            html = _formula_reference_html()
            self.assertIn(theme.code_bg, html)
            self.assertIn(theme.code_keyword, html)
            self.assertNotIn("@@CODE_", html)

    def test_cursor_lines_follow_cursor_tokens_in_each_theme(self) -> None:
        plot = pg.PlotWidget()
        controller = CursorController(plot, get_plot_data=lambda: [], format_time=str)
        for name, theme in THEMES.items():
            apply_theme(self.app, name)
            self.assertEqual(controller.cursor_line.pen.color().name(), theme.plot_cursor_a)
            self.assertEqual(controller.cursor_line_b.pen.color().name(), theme.plot_cursor_b)
        controller.dispose()
        plot.close()


if __name__ == "__main__":
    unittest.main()
