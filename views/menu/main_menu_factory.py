from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMainWindow

from viewmodels.data_viewmodel import LogDataViewModel


def build_main_menu(
    window: QMainWindow,
    *,
    data_vm: LogDataViewModel,
    on_load: Callable[[], None],
    on_append: Callable[[], None],
    on_clear: Callable[[], None],
    on_open_dbc: Callable[[], None],
    on_open_plot: Callable[[], None],
    set_timezone: Callable[[str], None],
    get_timezone: Callable[[], str],
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
    normalize = QAction("Normalize timestamp", window, checkable=True)
    normalize.triggered.connect(data_vm.set_normalize)
    settings_menu.addAction(normalize)

    time_menu = settings_menu.addMenu("Time axis")
    time_group = QActionGroup(window)
    time_group.setExclusive(True)

    raw_action = QAction("Raw seconds", window, checkable=True)
    raw_action.triggered.connect(lambda: set_timezone("none"))
    time_group.addAction(raw_action)
    time_menu.addAction(raw_action)

    utc_action = QAction("UTC", window, checkable=True)
    utc_action.triggered.connect(lambda: set_timezone("UTC"))
    time_group.addAction(utc_action)
    time_menu.addAction(utc_action)

    lima_action = QAction("America / Lima", window, checkable=True)
    lima_action.triggered.connect(lambda: set_timezone("America/Lima"))
    time_group.addAction(lima_action)
    time_menu.addAction(lima_action)

    tokyo_action = QAction("Asia / Tokyo", window, checkable=True)
    tokyo_action.triggered.connect(lambda: set_timezone("Asia/Tokyo"))
    time_group.addAction(tokyo_action)
    time_menu.addAction(tokyo_action)

    action_map = {
        "none": raw_action,
        "UTC": utc_action,
        "America/Lima": lima_action,
        "Asia/Tokyo": tokyo_action,
    }
    action_map.get(get_timezone(), raw_action).setChecked(True)

    tools_menu = menubar.addMenu("Tools")
    add_plot = QAction("Add new graphic window", window)
    add_plot.triggered.connect(on_open_plot)
    tools_menu.addAction(add_plot)

