from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

"""Central theme system for Canlytics.

A theme is a flat set of design tokens (colors + a couple of metrics). From a
theme we derive both a QPalette (so native widgets and the SVG icon loader pick
up the right colors) and an application-wide QSS stylesheet. Adding a new theme
(e.g. a dense or high-contrast variant) is just another entry in THEMES.
"""


@dataclass(frozen=True)
class Theme:
    name: str
    is_dark: bool
    window: str          # app background
    surface: str         # inputs, tables, raised panels
    surface_alt: str     # alternate rows, hovered surfaces
    border: str
    text: str
    text_muted: str
    accent: str          # brand / primary action
    accent_hover: str
    accent_text: str     # text on top of accent
    selection: str
    selection_text: str
    radius: int = 6
    pad: int = 6


THEMES: dict[str, Theme] = {
    "Dark": Theme(
        name="Dark", is_dark=True,
        window="#1e1f22", surface="#2b2d30", surface_alt="#34373b",
        border="#3a3d41", text="#e4e6eb", text_muted="#9aa0a6",
        accent="#1E74E6", accent_hover="#3a86ec", accent_text="#ffffff",
        selection="#1E74E6", selection_text="#ffffff",
    ),
    "Light": Theme(
        name="Light", is_dark=False,
        window="#f3f4f6", surface="#ffffff", surface_alt="#e9ebef",
        border="#d3d7dd", text="#1c1e21", text_muted="#6b7280",
        accent="#1E74E6", accent_hover="#1660c8", accent_text="#ffffff",
        selection="#1E74E6", selection_text="#ffffff",
    ),
}

DEFAULT_THEME = "Dark"


def available_themes() -> list[str]:
    return list(THEMES.keys())


def get_theme(name: str | None) -> Theme:
    return THEMES.get(str(name or ""), THEMES[DEFAULT_THEME])


def build_palette(t: Theme) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t.window))
    p.setColor(QPalette.WindowText, QColor(t.text))
    p.setColor(QPalette.Base, QColor(t.surface))
    p.setColor(QPalette.AlternateBase, QColor(t.surface_alt))
    p.setColor(QPalette.Text, QColor(t.text))
    p.setColor(QPalette.Button, QColor(t.surface))
    p.setColor(QPalette.ButtonText, QColor(t.text))
    p.setColor(QPalette.BrightText, QColor(t.accent_text))
    p.setColor(QPalette.ToolTipBase, QColor(t.surface_alt))
    p.setColor(QPalette.ToolTipText, QColor(t.text))
    p.setColor(QPalette.Highlight, QColor(t.selection))
    p.setColor(QPalette.HighlightedText, QColor(t.selection_text))
    p.setColor(QPalette.PlaceholderText, QColor(t.text_muted))
    p.setColor(QPalette.Link, QColor(t.accent))
    disabled = QColor(t.text_muted)
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


def build_qss(t: Theme) -> str:
    r = t.radius
    return f"""
    QWidget {{ background-color: {t.window}; color: {t.text};
               font-size: 10pt; selection-background-color: {t.selection};
               selection-color: {t.selection_text}; }}
    QToolTip {{ background-color: {t.surface_alt}; color: {t.text};
                border: 1px solid {t.border}; padding: 4px; border-radius: 4px; }}

    QMenuBar {{ background-color: {t.window}; border-bottom: 1px solid {t.border}; }}
    QMenuBar::item {{ background: transparent; padding: 6px 10px; border-radius: 4px; }}
    QMenuBar::item:selected {{ background: {t.surface_alt}; }}
    QMenu {{ background-color: {t.surface}; border: 1px solid {t.border};
             border-radius: {r}px; padding: 4px; }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

    QToolBar {{ background-color: {t.window}; border: none; spacing: 4px; padding: 4px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent;
                   border-radius: {r}px; padding: 4px 6px; }}
    QToolButton:hover {{ background: {t.surface_alt}; }}
    QToolButton:checked {{ background: {t.accent}; color: {t.accent_text}; }}

    QPushButton {{ background-color: {t.surface}; color: {t.text};
                   border: 1px solid {t.border}; border-radius: {r}px;
                   padding: 6px 14px; }}
    QPushButton:hover {{ background-color: {t.surface_alt}; }}
    QPushButton:pressed {{ background-color: {t.border}; }}
    QPushButton:disabled {{ color: {t.text_muted}; }}
    QPushButton#primary {{ background-color: {t.accent}; color: {t.accent_text};
                           border: 1px solid {t.accent}; font-weight: 600; }}
    QPushButton#primary:hover {{ background-color: {t.accent_hover};
                                 border-color: {t.accent_hover}; }}

    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px; padding: 5px 8px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background-color: {t.surface};
        border: 1px solid {t.border}; selection-background-color: {t.accent};
        selection-color: {t.accent_text}; }}

    QTableView, QTreeView, QListView {{ background-color: {t.surface};
        alternate-background-color: {t.surface_alt}; gridline-color: {t.border};
        border: 1px solid {t.border}; border-radius: {r}px; }}
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
        background: {t.accent}; color: {t.accent_text}; }}
    QHeaderView::section {{ background-color: {t.surface_alt}; color: {t.text_muted};
        border: none; border-right: 1px solid {t.border};
        border-bottom: 1px solid {t.border}; padding: 6px 8px; font-weight: 600; }}
    QTableCornerButton::section {{ background-color: {t.surface_alt};
        border: 1px solid {t.border}; }}

    QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: {r}px; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {t.text_muted};
        padding: 7px 14px; border: 1px solid transparent; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    QTabBar::tab:hover {{ color: {t.text}; }}

    QGroupBox {{ border: 1px solid {t.border}; border-radius: {r}px;
        margin-top: 10px; padding-top: 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
        color: {t.text_muted}; }}

    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QCheckBox::indicator {{ border: 1px solid {t.border}; border-radius: 4px;
        background: {t.surface}; }}
    QRadioButton::indicator {{ border: 1px solid {t.border}; border-radius: 8px;
        background: {t.surface}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {t.accent}; border-color: {t.accent}; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
    QScrollBar::handle {{ background: {t.border}; border-radius: 5px; min-height: 28px;
        min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {t.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: {t.border}; }}
    QStatusBar {{ background: {t.window}; border-top: 1px solid {t.border};
        color: {t.text_muted}; }}
    QProgressBar {{ border: 1px solid {t.border}; border-radius: {r}px;
        text-align: center; background: {t.surface}; }}
    QProgressBar::chunk {{ background-color: {t.accent}; border-radius: {r}px; }}

    QWidget#RibbonBar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
    QPushButton#ribbon_tab {{
        background: transparent; border: none; border-radius: 0px;
        border-bottom: 2px solid transparent;
        color: {t.text_muted}; padding: 3px 12px; font-size: 9pt; }}
    QPushButton#ribbon_tab:hover {{ color: {t.text}; background: {t.surface_alt}; }}
    QPushButton#ribbon_tab[active="true"] {{
        color: {t.accent}; border-bottom: 2px solid {t.accent}; background: transparent; }}
    QToolButton#ribbonBtn {{
        background: transparent; border: 1px solid transparent;
        border-radius: {r}px; padding: 3px 1px;
        min-width: 54px; max-width: 68px; font-size: 8pt; }}
    QToolButton#ribbonBtn:hover {{ background: {t.surface_alt}; border-color: {t.border}; }}
    QToolButton#ribbonBtn:pressed {{ background: {t.selection}; color: {t.selection_text}; }}
    QToolButton#ribbonBtn:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QToolButton#ribbonBtn:checked:hover {{ background: {t.accent_hover}; }}
    QToolButton#ribbonBtn::menu-indicator {{ width: 0px; height: 0px; image: none; }}
    QLabel#ribbon_group_title {{ color: {t.text_muted}; font-size: 8pt; padding: 0px; }}
    QWidget#ribbon_sep {{ background: {t.border}; }}
    """


def apply_theme(app, name: str | None) -> Theme:
    """Apply a theme (palette + stylesheet) to the QApplication and return it."""
    theme = get_theme(name)
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_qss(theme))
    return theme
