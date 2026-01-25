from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QTabWidget, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from core.signal import Signal
from views.signal.signal_view import ViewSignal

from views.signal.tabs.decode_tab import DecodeTab
from views.signal.tabs.filter_tab import FilterTab
from views.signal.tabs.style_tab import StyleTab


class GraphSettingsDialog(QDialog):
    def __init__(
        self,
        vm,
        view_signal: ViewSignal | None = None,
        parent=None,
        dbc_manager=None,
    ):
        super().__init__(parent)

        self.vm = vm
        self.df = vm.df
        self.view_signal = view_signal
        self.dbc_manager = dbc_manager

        self.setWindowTitle("Graph settings")
        self.resize(600, 500)

        self.decode_tab = DecodeTab(self.df, dbc_manager=self.dbc_manager)
        self.filter_tab = FilterTab()
        self.style_tab = StyleTab(
            initial_color=view_signal.color if view_signal else QColor("cyan")
        )

        self._build_ui()

        if self.view_signal:
            self._load_signal()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self.decode_tab, "Signal")
        tabs.addTab(self.style_tab, "Graph")
        tabs.addTab(self.filter_tab, "Filters")

        layout.addWidget(tabs)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok_clicked)
        layout.addWidget(ok_btn, alignment=Qt.AlignRight)

    def _load_signal(self):
        self.decode_tab.load_signal(self.view_signal.signal)
        self.filter_tab.load_signal(self.view_signal)
        self.style_tab.load_signal(self.view_signal)

    def _on_ok_clicked(self):
        name = self.decode_tab.get_name()

        if not name:
            QMessageBox.warning(self, "Invalid name", "Signal name cannot be empty.")
            return

        if name in self.vm.signals:
            if not self.view_signal or name != self.view_signal.signal.name:
                QMessageBox.warning(
                    self,
                    "Duplicate signal",
                    f"A signal named '{name}' already exists.",
                )
                return

        self.accept()

    def get_signal(self) -> ViewSignal:
        raw_data = self.decode_tab.get_signal_data()
        sig_data = self.vm.parse_signal_data(raw_data)
        sig = Signal(**sig_data)
        filter_type, filter_params = self.filter_tab.get_filter()
        style = self.style_tab.get_style()

        return ViewSignal(
            signal=sig,
            filter_type=filter_type,
            filter_params=filter_params,
            **style,
        )
