from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow


def build_main_menu(
    window: QMainWindow,
    *,
    on_load: Callable[[], None],
    on_append: Callable[[], None],
    on_clear: Callable[[], None],
    on_open_dbc: Callable[[], None],
    on_open_plot: Callable[[], None],
    on_time_config: Callable[[], None],
) -> None:
    menubar = window.menuBar()

    file_menu = menubar.addMenu("File")

    load_action = QAction("Load Log", window)
    load_action.triggered.connect(on_load)
    file_menu.addAction(load_action)

    append_action = QAction("Append Log", window)
    append_action.triggered.connect(on_append)
    file_menu.addAction(append_action)

    clear_action = QAction("Clear log", window)
    clear_action.triggered.connect(on_clear)
    file_menu.addAction(clear_action)

    load_dbc_action = QAction("Load DBC...", window)
    load_dbc_action.triggered.connect(on_open_dbc)
    file_menu.addAction(load_dbc_action)

    settings_menu = menubar.addMenu("Settings")
    time_cfg_action = QAction("TimeConfig...", window)
    time_cfg_action.triggered.connect(on_time_config)
    settings_menu.addAction(time_cfg_action)

    tools_menu = menubar.addMenu("Tools")
    add_plot = QAction("Add new graphic window", window)
    add_plot.triggered.connect(on_open_plot)
    tools_menu.addAction(add_plot)
