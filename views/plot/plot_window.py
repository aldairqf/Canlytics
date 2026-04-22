from PySide6.QtWidgets import QMainWindow, QMenu, QFileDialog
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
import pyqtgraph as pg

from views.signal.signal_settings_dialog import GraphSettingsDialog
from .plot_items import ClickableViewBox
from .plot_renderer import PlotRenderer
from .plot_interaction import PlotInteraction
from .time_axis import TimeAxisItem
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.settings.time_config_dialog import TimeConfigDialog


class PlotWindow(QMainWindow):
    closed = Signal()

    def __init__(self, graph_vm, dbc_manager=None, timezone_mode="none"):
        super().__init__()
        self.vm = graph_vm
        self.dbc_manager = dbc_manager
        self.interaction = PlotInteraction()

        self.normalize_time = False
        self.timezone_mode = timezone_mode

        self.time_axis = TimeAxisItem(timezone_mode=self.timezone_mode, orientation="bottom")

        self._time_vm = TimeConfigViewModel(
            normalize=self.normalize_time,
            timezone=self.timezone_mode,
            parent=self,
        )
        self._time_vm.normalize_changed.connect(self._on_normalize_time_toggled)
        self._time_vm.timezone_changed.connect(self._set_timezone)

        self._setup_ui()

        self.renderer = PlotRenderer(
            self.plot,
            on_select=self._on_select_signal,
            on_context=self._open_context_menu,
            on_edit=self._edit_selected_by_name,
        )

        if hasattr(self.view_box, "sigRangeChangedManually"):
            self.view_box.sigRangeChangedManually.connect(self._on_view_changed_manually)

        self.vm.data_changed.connect(self._redraw)

    def _on_normalize_time_toggled(self, checked: bool):
        self.normalize_time = checked

        if checked:
            self.time_axis.set_timezone("none")
            self.plot.setLabel("bottom", "Time (s)")

        self._redraw()

    def _on_view_changed_manually(self, *args):
        if hasattr(self, "renderer") and self.renderer:
            self.renderer.lock_autorange()

    def _setup_menu_bar(self):
        menu_plot = self.menuBar().addMenu("Settings")
        action = menu_plot.addAction("Time settings...")
        action.triggered.connect(self._open_time_settings)

    def _open_time_settings(self):
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _set_timezone(self, tz: str):
        self.timezone_mode = tz

        if tz not in ("none", None):
            self.normalize_time = False

        self.time_axis.set_timezone(tz)

        self.plot.setAxisItems({"bottom": self.time_axis})

        if tz in ("none", None):
            self.plot.setLabel("bottom", "Time (s)")
        else:
            self.plot.setLabel("bottom", f"Time ({tz})")

        self.plot.repaint()
        self._redraw()

    def _setup_ui(self):
        self.setWindowTitle("CAN Plot")
        self.resize(900, 600)

        self.view_box = ClickableViewBox(
            on_left_click=self._clear_selection,
            on_right_click=self._open_context_menu,
        )

        self.plot = pg.PlotWidget(
            viewBox=self.view_box,
            axisItems={"bottom": self.time_axis},
        )
        self.plot.setLabel("bottom", "Time (s)" if self.timezone_mode in ("none", None) else f"Time ({self.timezone_mode})")
        self.plot.setLabel("left", "Value")
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)

        self.setCentralWidget(self.plot)

        self._setup_menu_bar()

    def _edit_selected_by_name(self, name: str):
        if not name or name not in self.vm.signals:
            return

        self.interaction.select(name)
        self.renderer.highlight(name)
        self._edit_selected()

    def _on_select_signal(self, name: str):
        self.interaction.select(name)
        self.renderer.highlight(name)

    def _clear_selection(self):
        self.interaction.clear()
        self.renderer.highlight(None)

    def _open_context_menu(self):
        menu = QMenu(self)

        edit_action = None
        remove_action = None
        duplicate_action = None

        if self.interaction.selected:
            edit_action = menu.addAction("Edit selected signal")
            remove_action = menu.addAction("Remove selected signal")
            duplicate_action = menu.addAction("Duplicate selected signal")
            menu.addSeparator()

        add_action = menu.addAction("Add signal")
        clear_action = menu.addAction("Remove all signals")
        menu.addSeparator()

        save_action = menu.addAction("Save config signals")
        load_action = menu.addAction("Load config signals")
        append_action = menu.addAction("Append config signals")
        menu.addSeparator()

        rescale_action = menu.addAction("Rescale view")

        action = menu.exec(QCursor.pos())

        if action == edit_action:
            self._edit_selected()
        elif action == remove_action:
            self._remove_selected()
        elif action == duplicate_action:
            self._duplicate_selected()
        elif action == add_action:
            self._add_signal()
        elif action == clear_action:
            self._reset()
        elif action == save_action:
            self._save_config()
        elif action == load_action:
            self._load_config()
        elif action == append_action:
            self._append_config()
        elif action == rescale_action:
            self.renderer.request_autorange()

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save signal configuration",
            "",
            "Signal config (*.conf)",
        )
        if not path:
            return
        self.vm.save_config(path)

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load signal configuration",
            "",
            "Signal config (*.conf)",
        )
        if not path:
            return

        self.interaction.clear()
        self.vm.load_config(path)

    def _append_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Append signal configuration",
            "",
            "Signal config (*.conf)",
        )
        if not path:
            return

        self.interaction.clear()
        self.vm.append_config(path)

    def _add_signal(self):
        dlg = GraphSettingsDialog(
            self.vm,
            parent=self,
            dbc_manager=self.dbc_manager,
        )
        if dlg.exec():
            self.vm.upsert_signal(dlg.get_signal())

    def _edit_selected(self):
        old_name = self.interaction.selected
        if not old_name or old_name not in self.vm.signals:
            return

        dlg = GraphSettingsDialog(
            self.vm,
            view_signal=self.vm.signals[old_name],
            parent=self,
            dbc_manager=self.dbc_manager,
        )
        if dlg.exec():
            new_vs = dlg.get_signal()
            new_name = new_vs.signal.name

            if new_name != old_name:
                self.vm.remove_signal(old_name)

            self.vm.upsert_signal(new_vs)
            self.interaction.select(new_name)

    def _remove_selected(self):
        name = self.interaction.selected
        if not name:
            return
        self.vm.remove_signal(name)
        self.interaction.clear()

    def _reset(self):
        self.interaction.clear()
        self.vm.clear()

    def _duplicate_selected(self):
        name = self.interaction.selected
        if not name:
            return

        new_name = self.vm.duplicate_signal(name)
        if new_name:
            self.interaction.select(new_name)

    def _redraw(self):
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        self.renderer.render(plot_data)
        self.renderer.highlight(self.interaction.selected)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
