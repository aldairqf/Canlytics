from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class RibbonButton(QToolButton):
    """Ribbon-style button: icon on top (28 px) with a short label below."""

    def __init__(
        self,
        icon_name: str,
        label: str,
        *,
        parent: QWidget | None = None,
        icon_size: int = 28,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self.setObjectName("ribbonBtn")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setFixedSize(QSize(60, 60))
        self.setText(label)
        self.reload_icon()

    def reload_icon(self) -> None:
        from views.icons import icon as _load  # late import — avoids circular at module load
        self.setIcon(_load(self._icon_name, size=self._icon_size))


class RibbonGroup(QWidget):
    """A horizontal strip of RibbonButtons with a centred group title below."""

    def __init__(self, title: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 0)
        outer.setSpacing(0)

        self._content = QWidget()
        self._content_layout = QHBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(2)
        outer.addWidget(self._content, 1)

        lbl = QLabel(title)
        lbl.setObjectName("ribbon_group_title")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(lbl)

    def add_button(self, btn: QToolButton) -> None:
        self._content_layout.addWidget(btn)


class RibbonTabButton(QPushButton):
    """Checkable tab selector used in the ribbon tab row."""

    def __init__(self, label: str, *, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.setObjectName("ribbon_tab")
        self.setCheckable(True)
        self.setFlat(True)
        self.setProperty("active", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
