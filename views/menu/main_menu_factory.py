from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMainWindow

from config.app_config import get_text
from config.theme import available_themes

def build_main_menu(
    window: QMainWindow,
    *,
    on_load: Callable[[], None],
    on_append: Callable[[], None],
    on_save: Callable[[], None],
    on_clear: Callable[[], None],
    on_open_dbc: Callable[[], None],
    on_open_plot: Callable[[], None],
    on_analyze_data: Callable[[], None],
    on_candidate_interpretations: Callable[[], None],
    on_mux_detection: Callable[[], None],
    on_signal_coverage: Callable[[], None],
    on_hmi_video_extractor: Callable[[], None],
    on_time_config: Callable[[], None],
    on_time_filter: Callable[[], None],
    on_connection: Callable[[], None],
    on_set_theme: Callable[[str], None],
    current_theme: str = "Dark",
) -> dict[str, object]:
    menubar = window.menuBar()

    file_menu = menubar.addMenu(get_text("menu_file"))

    load_action = QAction(get_text("menu_load_log"), window)
    load_action.setShortcut(QKeySequence.StandardKey.Open)
    load_action.triggered.connect(on_load)
    file_menu.addAction(load_action)

    append_action = QAction(get_text("menu_append_log"), window)
    append_action.triggered.connect(on_append)
    file_menu.addAction(append_action)

    save_action = QAction(get_text("menu_save_log"), window)
    save_action.setShortcut(QKeySequence.StandardKey.Save)
    save_action.triggered.connect(on_save)
    file_menu.addAction(save_action)

    file_menu.addSeparator()

    load_dbc_action = QAction(get_text("menu_load_dbc"), window)
    load_dbc_action.triggered.connect(on_open_dbc)
    file_menu.addAction(load_dbc_action)

    file_menu.addSeparator()

    clear_action = QAction(get_text("menu_clear_log"), window)
    clear_action.triggered.connect(on_clear)
    file_menu.addAction(clear_action)

    settings_menu = menubar.addMenu(get_text("menu_settings"))
    time_cfg_action = QAction(get_text("menu_time_config"), window)
    time_cfg_action.triggered.connect(on_time_config)
    settings_menu.addAction(time_cfg_action)

    time_filter_action = QAction(get_text("menu_time_filter"), window)
    time_filter_action.triggered.connect(on_time_filter)
    settings_menu.addAction(time_filter_action)

    theme_menu = settings_menu.addMenu(get_text("menu_theme"))
    theme_group = QActionGroup(window)
    theme_group.setExclusive(True)
    for theme_name in available_themes():
        theme_action = QAction(theme_name, window, checkable=True)
        theme_action.setChecked(theme_name == current_theme)
        theme_action.triggered.connect(lambda _checked=False, n=theme_name: on_set_theme(n))
        theme_group.addAction(theme_action)
        theme_menu.addAction(theme_action)

    tools_menu = menubar.addMenu(get_text("menu_tools"))
    add_plot = QAction(get_text("menu_add_plot"), window)
    add_plot.triggered.connect(on_open_plot)
    tools_menu.addAction(add_plot)

    analyze_data = QAction(get_text("menu_analyze_data"), window)
    analyze_data.triggered.connect(on_analyze_data)
    tools_menu.addAction(analyze_data)

    candidate_interpretations = QAction(get_text("menu_candidate_interpretations"), window)
    candidate_interpretations.triggered.connect(on_candidate_interpretations)
    tools_menu.addAction(candidate_interpretations)

    mux_detection = QAction(get_text("menu_mux_detection"), window)
    mux_detection.triggered.connect(on_mux_detection)
    tools_menu.addAction(mux_detection)

    signal_coverage = QAction(get_text("menu_signal_coverage"), window)
    signal_coverage.triggered.connect(on_signal_coverage)
    tools_menu.addAction(signal_coverage)

    hmi_video_extractor = QAction(get_text("menu_hmi_video_extractor"), window)
    hmi_video_extractor.triggered.connect(on_hmi_video_extractor)
    tools_menu.addAction(hmi_video_extractor)

    connection_action = QAction(get_text("menu_connection"), window)
    connection_action.triggered.connect(on_connection)
    tools_menu.addAction(connection_action)

    return {
        "file_menu": file_menu,
        "settings_menu": settings_menu,
        "tools_menu": tools_menu,
        "load_action": load_action,
        "append_action": append_action,
        "save_action": save_action,
        "load_dbc_action": load_dbc_action,
    }
