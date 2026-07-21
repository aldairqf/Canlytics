from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from config.version import APP_VERSION
from views.icons import app_icon


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("about_dialog_title"))
        self.setWindowIcon(app_icon())
        self.setFixedSize(300, 220)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(28, 20, 28, 16)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(app_icon().pixmap(48, 48))
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(get_text("main_window_title"))
        name_lbl.setAlignment(Qt.AlignCenter)
        f = name_lbl.font()
        f.setPointSize(14)
        f.setBold(True)
        name_lbl.setFont(f)
        layout.addWidget(name_lbl)

        ver_lbl = QLabel(get_text("about_dialog_version_prefix").format(version=APP_VERSION))
        ver_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver_lbl)

        desc_lbl = QLabel(get_text("about_dialog_description"))
        desc_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_lbl)

        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
