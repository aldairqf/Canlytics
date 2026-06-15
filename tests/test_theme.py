"""Characterization tests for config/theme.py.

Rules pinned here:
- font-size in the QSS must use pt units, never px — Qt stores px-based fonts
  with pointSize() == -1, which causes pyqtgraph to call setPointSize(-1) and
  emit "Point size <= 0 (-1)" warnings when drawing axis labels.
- Every THEMES entry must expose valid hex colors and numeric design tokens.
- build_qss() must include every required widget selector so the stylesheet is
  self-contained.
"""
from __future__ import annotations

import re
import unittest

from config.theme import (
    DEFAULT_THEME,
    THEMES,
    available_themes,
    build_qss,
    build_palette,
    get_theme,
)


class ThemeRegistryTests(unittest.TestCase):
    def test_default_theme_exists(self):
        self.assertIn(DEFAULT_THEME, THEMES)

    def test_available_themes_returns_all_keys(self):
        self.assertEqual(set(available_themes()), set(THEMES.keys()))

    def test_get_theme_unknown_falls_back_to_default(self):
        t = get_theme("NonExistent")
        self.assertEqual(t.name, DEFAULT_THEME)

    def test_get_theme_none_falls_back_to_default(self):
        t = get_theme(None)
        self.assertEqual(t.name, DEFAULT_THEME)

    def test_all_themes_have_required_color_fields(self):
        hex_re = re.compile(r'^#[0-9a-fA-F]{6}$')
        required = [
            "window", "surface", "surface_alt", "border",
            "text", "text_muted", "accent", "accent_hover",
            "accent_text", "selection", "selection_text",
        ]
        for name, t in THEMES.items():
            for field in required:
                val = getattr(t, field)
                self.assertRegex(
                    val, hex_re,
                    msg=f"Theme '{name}' field '{field}' = {val!r} is not a valid hex color",
                )

    def test_all_themes_have_positive_design_tokens(self):
        for name, t in THEMES.items():
            self.assertGreater(t.radius, 0, msg=f"Theme '{name}': radius must be > 0")
            self.assertGreater(t.pad, 0, msg=f"Theme '{name}': pad must be > 0")

    def test_dark_theme_is_dark(self):
        self.assertTrue(THEMES["Dark"].is_dark)

    def test_light_theme_is_not_dark(self):
        self.assertFalse(THEMES["Light"].is_dark)


class QssStructureTests(unittest.TestCase):
    """Pin structural invariants of the generated QSS."""

    def _qss(self, theme_name: str = DEFAULT_THEME) -> str:
        return build_qss(get_theme(theme_name))

    def test_font_size_uses_pt_not_px_all_themes(self):
        """font-size must be in pt for every theme so Qt stores a valid pointSize().

        If px is used instead, QFont.pointSize() returns -1 and pyqtgraph
        calls setPointSize(-1), printing "Point size <= 0 (-1)" warnings
        every time a plot window or cursor is initialised.
        """
        px_font_re = re.compile(r'font-size\s*:\s*\d+px', re.IGNORECASE)
        for name in available_themes():
            qss = build_qss(get_theme(name))
            matches = px_font_re.findall(qss)
            self.assertEqual(
                matches, [],
                msg=f"Theme '{name}' QSS contains pixel-based font-size: {matches}",
            )

    def test_font_size_pt_present(self):
        qss = self._qss()
        self.assertRegex(qss, r'font-size\s*:\s*\d+pt',
                         msg="QSS should declare font-size in pt units")

    def test_qss_contains_required_selectors(self):
        qss = self._qss()
        required = ["QWidget", "QMenuBar", "QToolBar", "QPushButton",
                    "QLineEdit", "QTableView", "QTabWidget", "QScrollBar"]
        for sel in required:
            self.assertIn(sel, qss, msg=f"QSS missing selector: {sel}")

    def test_qss_generated_for_all_themes(self):
        for name in available_themes():
            qss = build_qss(get_theme(name))
            self.assertIsInstance(qss, str)
            self.assertGreater(len(qss), 100)

    def test_qss_interpolates_theme_colors(self):
        dark_qss = self._qss("Dark")
        light_qss = self._qss("Light")
        # Background colors differ between themes
        self.assertNotEqual(dark_qss, light_qss)
        self.assertIn(THEMES["Dark"].window, dark_qss)
        self.assertIn(THEMES["Light"].window, light_qss)


class PaletteTests(unittest.TestCase):
    """build_palette must not raise and must return a QPalette."""

    def test_build_palette_returns_for_all_themes(self):
        try:
            from PySide6.QtGui import QPalette
        except ImportError:
            self.skipTest("PySide6 not available")

        for name, t in THEMES.items():
            palette = build_palette(t)
            self.assertIsInstance(
                palette, QPalette,
                msg=f"build_palette returned unexpected type for theme '{name}'",
            )


class ApplyThemeTests(unittest.TestCase):
    """apply_theme must set palette + stylesheet without raising."""

    @classmethod
    def setUpClass(cls):
        cls._app = None
        try:
            import sys
            from PySide6.QtWidgets import QApplication
            existing = QApplication.instance()
            if isinstance(existing, QApplication):
                cls._app = existing
            elif existing is None:
                cls._app = QApplication(sys.argv[:1])
            # else: a QCoreApplication is already running — skip these tests
        except ImportError:
            pass

    def setUp(self):
        if self._app is None:
            self.skipTest("QApplication not available (QCoreApplication already running)")

    def test_apply_theme_returns_theme_object(self):
        from config.theme import apply_theme
        for name in available_themes():
            result = apply_theme(self._app, name)
            self.assertEqual(result.name, name)

    def test_apply_theme_unknown_name_returns_default(self):
        from config.theme import apply_theme
        result = apply_theme(self._app, "DoesNotExist")
        self.assertEqual(result.name, DEFAULT_THEME)

    def test_apply_theme_sets_non_empty_stylesheet(self):
        from config.theme import apply_theme
        apply_theme(self._app, DEFAULT_THEME)
        self.assertGreater(len(self._app.styleSheet()), 100)

    def test_apply_theme_font_has_valid_point_size(self):
        """After apply_theme the app font must have pointSize() > 0.

        Regression guard: if font-size is ever changed back to px units,
        QFont.pointSize() returns -1 and pyqtgraph emits 'Point size <= 0'
        warnings on every plot/cursor initialisation.
        """
        from config.theme import apply_theme
        apply_theme(self._app, DEFAULT_THEME)
        point_size = self._app.font().pointSize()
        self.assertGreater(
            point_size, 0,
            msg=(
                f"app.font().pointSize() == {point_size}; "
                "font-size in QSS must use pt units, not px"
            ),
        )


if __name__ == "__main__":
    unittest.main()
