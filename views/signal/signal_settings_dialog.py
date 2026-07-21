from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QPushButton, QTabWidget, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.plot_config import parse_signal_data
from viewmodels.view_signal import ViewSignal

from views.signal.tabs.decode_tab import DecodeTab
from views.signal.tabs.filter_tab import FilterTab
from views.signal.tabs.style_tab import StyleTab
from config.app_config import get_text


class SignalSettingsDialog(QDialog):
    def __init__(
        self,
        vm,
        view_signal: ViewSignal | None = None,
        parent=None,
        dbc_manager=None,
        default_color: QColor | None = None,
    ):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)

        self.vm = vm
        self.df = vm.df
        self.view_signal = view_signal
        self.dbc_manager = dbc_manager

        self.setWindowTitle(get_text("signal_settings_edit_title") if view_signal else get_text("signal_settings_add_title"))
        self.resize(750, 520)

        self.decode_tab = DecodeTab(self.df, dbc_manager=self.dbc_manager)
        self.filter_tab = FilterTab()
        if view_signal:
            initial_color = view_signal.color
        elif default_color is not None:
            initial_color = default_color
        else:
            initial_color = QColor("cyan")
        self.style_tab = StyleTab(initial_color=initial_color)

        self.result_action: str = "ok"  # "ok" | "duplicate" | "delete"

        self._build_ui()

        if self.view_signal:
            self._load_signal()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self.decode_tab, get_text("graph_settings_signal_tab"))
        tabs.addTab(self.decode_tab.dbc_panel, get_text("graph_settings_dbc_tab"))
        tabs.addTab(self.style_tab, get_text("graph_settings_graph_tab"))
        tabs.addTab(self.filter_tab, get_text("graph_settings_filters_tab"))

        layout.addWidget(tabs)

        bar = QHBoxLayout()

        if self.view_signal:
            del_btn = QPushButton(get_text("delete"))
            del_btn.clicked.connect(self._on_delete)
            dup_btn = QPushButton(get_text("duplicate"))
            dup_btn.clicked.connect(self._on_duplicate)
            bar.addWidget(del_btn)
            bar.addWidget(dup_btn)

        bar.addStretch()

        cancel_btn = QPushButton(get_text("cancel"))
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(get_text("ok"))
        ok_btn.setDefault(True)
        ok_btn.setAutoDefault(True)
        ok_btn.clicked.connect(self._on_ok_clicked)
        bar.addWidget(cancel_btn)
        bar.addWidget(ok_btn)

        layout.addLayout(bar)

    def _load_signal(self):
        self.decode_tab.load_signal(
            self.view_signal.signal,
            selector=getattr(self.view_signal, "selector", None),
        )
        self.filter_tab.load_signal(self.view_signal)
        self.style_tab.load_signal(self.view_signal)

    def _on_delete(self):
        self.result_action = "delete"
        self.accept()

    def _on_duplicate(self):
        self.result_action = "duplicate"
        self._on_ok_clicked()

    def _on_ok_clicked(self):
        name = self.decode_tab.get_name()

        # An empty name is allowed: get_signal() assigns a unique default.
        if name and name in self.vm.signals:
            if not self.view_signal or name != self.view_signal.signal.name:
                QMessageBox.warning(
                    self,
                    get_text("duplicate_signal_title"),
                    get_text("duplicate_signal_message").format(name=name),
                )
                return

        self.accept()

    def get_signal(self) -> ViewSignal:
        raw_data = self.decode_tab.get_signal_data()
        parsed = parse_signal_data(raw_data)

        sig = Signal(**parsed["signal"])
        if not (sig.name or "").strip():
            sig.name = self.vm._unique_signal_name("Signal")
        selector = FrameSelector(**parsed["selector"])

        filter_type, filter_params = self.filter_tab.get_filter()
        style = self.style_tab.get_style()

        return ViewSignal(
            signal=sig,
            selector=selector,
            filter_type=filter_type,
            filter_params=filter_params,
            internal_id=(self.view_signal.internal_id if self.view_signal else None),
            **style,
        )
