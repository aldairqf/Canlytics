from PySide6.QtWidgets import (
    QWidget, QFormLayout, QGroupBox,
    QComboBox, QSpinBox, QDoubleSpinBox, QLabel
)

from config.app_config import get_option, get_text

class FilterTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.addWidget(self._build_filter_group())

    def _build_filter_group(self):
        box = QGroupBox(get_text("signal_filter_title"))
        form = QFormLayout(box)

        self.filter_type = QComboBox()
        self.filter_type.addItems(get_option("filter_types", []))

        self.filter_window = QSpinBox()
        self.filter_window.setRange(1, 10000)
        self.filter_window.setValue(10)

        self.filter_alpha = QDoubleSpinBox()
        self.filter_alpha.setRange(0.001, 1.0)
        self.filter_alpha.setSingleStep(0.05)
        self.filter_alpha.setValue(0.2)

        self.filter_sigma = QDoubleSpinBox()
        self.filter_sigma.setRange(0.1, 100.0)
        self.filter_sigma.setSingleStep(0.1)
        self.filter_sigma.setValue(1.0)

        self.filter_polyorder = QSpinBox()
        self.filter_polyorder.setRange(1, 5)
        self.filter_polyorder.setValue(2)

        form.addRow(get_text("filter_type_label"), self.filter_type)
        form.addRow(get_text("window_label"), self.filter_window)
        form.addRow(get_text("alpha_label"), self.filter_alpha)
        form.addRow(get_text("sigma_label"), self.filter_sigma)
        form.addRow(get_text("polyorder_label"), self.filter_polyorder)

        self.filter_type.currentTextChanged.connect(self._on_filter_changed)
        self._on_filter_changed(self.filter_type.currentText())

        return box

    def _on_filter_changed(self, text: str):
        window_types = set(get_option("filter_window_types", []))
        self.filter_window.setEnabled(text in window_types)
        self.filter_alpha.setEnabled(text == get_option("filter_alpha_type", "Exponential Moving Average"))
        self.filter_sigma.setEnabled(text == get_option("filter_sigma_type", "Gaussian"))
        self.filter_polyorder.setEnabled(text == get_option("filter_polyorder_type", "Savitzky-Golay"))

    def load_signal(self, view_signal):
        none_type = get_option("filter_none_type", "None")
        self.filter_type.setCurrentText(view_signal.filter_type or none_type)
        params = view_signal.filter_params or {}

        if "window" in params:
            self.filter_window.setValue(params["window"])
        if "alpha" in params:
            self.filter_alpha.setValue(params["alpha"])
        if "sigma" in params:
            self.filter_sigma.setValue(params["sigma"])
        if "polyorder" in params:
            self.filter_polyorder.setValue(params["polyorder"])

    def get_filter(self):
        filter_type = self.filter_type.currentText()
        filter_params = {}

        if filter_type in get_option("filter_window_types", []):
            filter_params["window"] = self.filter_window.value()
        if filter_type == get_option("filter_alpha_type", "Exponential Moving Average"):
            filter_params["alpha"] = self.filter_alpha.value()
        if filter_type == get_option("filter_sigma_type", "Gaussian"):
            filter_params["sigma"] = self.filter_sigma.value()
        if filter_type == get_option("filter_polyorder_type", "Savitzky-Golay"):
            filter_params["polyorder"] = self.filter_polyorder.value()

        if filter_type == get_option("filter_none_type", "None"):
            filter_type = None

        return filter_type, filter_params
