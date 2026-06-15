from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

"""Theme-aware loader for the bundled Lucide SVG icon set (assets/icons/).

Lucide icons use ``stroke="currentColor"``; we substitute that token with the
requested color before rendering so a single SVG adapts to light/dark themes.
"""


def _assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets"
    # views/icons.py -> project root is the parent of the 'views' package.
    return Path(__file__).resolve().parent.parent / "assets"


def _icons_dir() -> Path:
    return _assets_dir() / "icons"


def app_icon() -> QIcon:
    """Return the multi-resolution Canlytics application/window icon.

    Rendered from assets/canlytics.svg (fixed brand colors, not recolored) at a
    range of sizes so it stays crisp in the taskbar, title bar and shortcuts.
    """
    path = _assets_dir() / "canlytics.svg"
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pix)
    return result


def _default_color() -> str:
    app = QGuiApplication.instance()
    if app is not None:
        return app.palette().buttonText().color().name()
    return "#000000"


@lru_cache(maxsize=256)
def _render(name: str, color: str, size: int) -> QPixmap:
    path = _icons_dir() / f"{name}.svg"
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return QPixmap()
    svg = svg.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pix


def icon(name: str, *, color: str | None = None, size: int = 20) -> QIcon:
    """Return a QIcon for the named Lucide SVG, recolored to ``color``.

    Falls back to the theme's button-text color when ``color`` is None, and to
    an empty icon if the SVG is missing.
    """
    return QIcon(_render(name, color or _default_color(), size))
