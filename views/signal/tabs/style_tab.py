from PySide6.QtWidgets import (
    QWidget, QFormLayout, QGroupBox,
    QPushButton, QComboBox, QSpinBox,
    QColorDialog
)
from PySide6.QtGui import QColor

from config.app_config import get_option, get_text

class StyleTab(QWidget):
    def __init__(self, initial_color: QColor | None = None):
        super().__init__()
        self.color = initial_color or QColor("cyan")
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.addWidget(self._build_style_group())

    def _build_style_group(self):
        box = QGroupBox(get_text("graph_style_title"))
        form = QFormLayout(box)

        self.color_btn = QPushButton(get_text("select_color"))
        self.color_btn.clicked.connect(self._select_color)

        self.line_style = QComboBox()
        self.line_style.addItems(get_option("line_styles", []))

        self.line_width = QSpinBox()
        self.line_width.setRange(1, 5)
        self.line_width.setValue(2)

        form.addRow(get_text("color_label"), self.color_btn)
        form.addRow(get_text("line_style_label"), self.line_style)
        form.addRow(get_text("line_width_label"), self.line_width)

        return box

    def _select_color(self):
        c = QColorDialog.getColor(self.color, self)
        if c.isValid():
            self.color = c

    def load_signal(self, view_signal):
        self.color = view_signal.color
        self.line_style.setCurrentText(view_signal.line_style)
        self.line_width.setValue(view_signal.line_width)

    def get_style(self):
        return {
            "color": self.color,
            "line_style": self.line_style.currentText(),
            "line_width": self.line_width.value(),
        }
