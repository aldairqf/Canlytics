from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from config.app_config import get_text

def build_main_menu(
    window: QMainWindow,
    *,
    on_load: Callable[[], None],
    on_append: Callable[[], None],
    on_clear: Callable[[], None],
    on_open_dbc: Callable[[], None],
    on_open_plot: Callable[[], None],
    on_time_config: Callable[[], None],
    on_ssh_connection: Callable[[], None],
) -> None:
    menubar = window.menuBar()

    file_menu = menubar.addMenu(get_text("menu_file"))

    load_action = QAction(get_text("menu_load_log"), window)
    load_action.triggered.connect(on_load)
    file_menu.addAction(load_action)

    append_action = QAction(get_text("menu_append_log"), window)
    append_action.triggered.connect(on_append)
    file_menu.addAction(append_action)

    clear_action = QAction(get_text("menu_clear_log"), window)
    clear_action.triggered.connect(on_clear)
    file_menu.addAction(clear_action)

    load_dbc_action = QAction(get_text("menu_load_dbc"), window)
    load_dbc_action.triggered.connect(on_open_dbc)
    file_menu.addAction(load_dbc_action)

    settings_menu = menubar.addMenu(get_text("menu_settings"))
    time_cfg_action = QAction(get_text("menu_time_config"), window)
    time_cfg_action.triggered.connect(on_time_config)
    settings_menu.addAction(time_cfg_action)

    tools_menu = menubar.addMenu(get_text("menu_tools"))
    add_plot = QAction(get_text("menu_add_plot"), window)
    add_plot.triggered.connect(on_open_plot)
    tools_menu.addAction(add_plot)

    ssh_action = QAction(get_text("menu_ssh_connection"), window)
    ssh_action.triggered.connect(on_ssh_connection)
    tools_menu.addAction(ssh_action)
