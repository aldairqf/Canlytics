from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QWidget

from config.app_config import get_text
from models.frame_selector import FrameSelector
from models.signal import Signal
from viewmodels.view_signal import ViewSignal


def make_view_signal(
    signal: Signal,
    selector: FrameSelector,
    *,
    color: QColor | str = "cyan",
    line_style: str = "Solid",
    line_width: int = 2,
) -> ViewSignal:
    """Default styling shared by every "add to plot" call site -- only color varies."""
    return ViewSignal(
        signal=signal,
        selector=selector,
        color=QColor(color),
        line_style=line_style,
        line_width=line_width,
    )


def show_add_to_plot_menu(
    parent: QWidget,
    global_pos,
    plot_manager,
    build_view_signal: Callable[[], ViewSignal | None],
) -> None:
    """Shared 'Add new graph' / 'Add last graph' context menu, used by the
    main table, Candidate Interpretations, and Signal Scan windows so a
    signal/candidate/scanned row can be sent to a plot the same way from
    anywhere. build_view_signal is only called once the user actually picks
    an action -- returning None is a safe no-op.
    """
    if plot_manager is None:
        return

    menu = QMenu(parent)
    add_new = menu.addAction(get_text("add_new_graph"))
    add_last = menu.addAction(get_text("add_last_graph"))
    action = menu.exec(global_pos)
    if action not in (add_new, add_last):
        return

    view_signal = build_view_signal()
    if view_signal is None:
        return
    plot_manager.add_view_signal(view_signal, use_last=(action == add_last))
