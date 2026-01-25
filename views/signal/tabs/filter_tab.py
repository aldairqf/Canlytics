from PySide6.QtWidgets import (
    QWidget, QFormLayout, QGroupBox,
    QComboBox, QSpinBox, QDoubleSpinBox, QLabel
)

class FilterTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.addWidget(self._build_filter_group())

    def _build_filter_group(self):
        box = QGroupBox("Signal filter")
        form = QFormLayout(box)

        self.filter_type = QComboBox()
        self.filter_type.addItems([
            "None",
            "Moving Average",
            "Exponential Moving Average",
            "Median",
            "Gaussian",
            "Savitzky-Golay",
        ])

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

        form.addRow("Filter type", self.filter_type)
        form.addRow("Window (MA/Median/SG)", self.filter_window)
        form.addRow("Alpha (EMA)", self.filter_alpha)
        form.addRow("Sigma (Gaussian)", self.filter_sigma)
        form.addRow("Polyorder (Savitzky-Golay)", self.filter_polyorder)

        self.filter_type.currentTextChanged.connect(self._on_filter_changed)
        self._on_filter_changed(self.filter_type.currentText())

        return box

    def _on_filter_changed(self, text: str):
        self.filter_window.setEnabled(text in ["Moving Average", "Median", "Savitzky-Golay"])
        self.filter_alpha.setEnabled(text == "Exponential Moving Average")
        self.filter_sigma.setEnabled(text == "Gaussian")
        self.filter_polyorder.setEnabled(text == "Savitzky-Golay")

    def load_signal(self, view_signal):
        self.filter_type.setCurrentText(view_signal.filter_type or "None")
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

        if filter_type in ["Moving Average", "Median", "Savitzky-Golay"]:
            filter_params["window"] = self.filter_window.value()
        if filter_type == "Exponential Moving Average":
            filter_params["alpha"] = self.filter_alpha.value()
        if filter_type == "Gaussian":
            filter_params["sigma"] = self.filter_sigma.value()
        if filter_type == "Savitzky-Golay":
            filter_params["polyorder"] = self.filter_polyorder.value()

        if filter_type == "None":
            filter_type = None

        return filter_type, filter_params
