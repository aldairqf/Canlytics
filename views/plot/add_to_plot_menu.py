from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QWidget

from config.app_config import get_text
from models.analysis_context import AnalysisContext
from models.frame_selector import FrameSelector
from models.signal import Signal
from viewmodels.view_signal import ViewSignal

if TYPE_CHECKING:
    from viewmodels.analysis_context_viewmodel import AnalysisContextViewModel


class PlotManager(Protocol):
    def add_view_signal(self, view_signal: ViewSignal, *, use_last: bool) -> object: ...


@dataclass(frozen=True)
class SendToAction:
    callback: Callable[[], None]
    enabled: bool = True


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


def show_send_to_menu(
    parent: QWidget,
    global_pos: object,
    destinations: dict[str, Callable[[], None] | SendToAction],
) -> None:
    """Display registered destinations and call only the selected action."""
    if not destinations:
        return
    menu = QMenu(parent)
    actions = {}
    for label, item in destinations.items():
        action = menu.addAction(label)
        if isinstance(item, SendToAction):
            action.setEnabled(item.enabled)
            callback = item.callback
        else:
            callback = item
        actions[action] = callback
    selected = menu.exec(global_pos)
    callback = actions.get(selected)
    if callback is not None:
        callback()


def plot_send_destinations(
    plot_manager: PlotManager | None,
    build_view_signal: Callable[[], ViewSignal | None],
    *,
    analysis_context_vm: AnalysisContextViewModel | None = None,
    context: AnalysisContext | None = None,
    source_window: str = "",
) -> dict[str, Callable[[], None]]:
    """Create the common-menu actions for creating or reusing a plot."""
    if plot_manager is None:
        return {}
    return {
        get_text("add_new_graph"): lambda: _send_plot(
            plot_manager, build_view_signal, False, analysis_context_vm, context, source_window
        ),
        get_text("add_last_graph"): lambda: _send_plot(
            plot_manager, build_view_signal, True, analysis_context_vm, context, source_window
        ),
    }


def analysis_send_destinations(
    analysis_context_vm: AnalysisContextViewModel,
    context: AnalysisContext,
    *,
    realtime_enabled: bool = False,
) -> dict[str, SendToAction]:
    """Build the shared tool destinations for a captured analysis context."""
    routes = (
        ("analysis_send_candidate", "candidate", context.can_id is not None),
        ("analysis_send_diff", "diff", context.can_id is not None),
        ("analysis_send_analyze", "analyze", True),
        ("analysis_send_realtime", "realtime", context.can_id is not None and realtime_enabled),
    )
    destinations = {
        get_text(label): SendToAction(
            lambda destination=destination: analysis_context_vm.send_to(destination, context),
            enabled=enabled,
        )
        for label, destination, enabled in routes
    }
    destinations[get_text("analysis_send_working_dbc")] = SendToAction(lambda: None, enabled=False)
    return destinations


def _send_plot(
    plot_manager: PlotManager,
    build_view_signal: Callable[[], ViewSignal | None],
    use_last: bool,
    analysis_context_vm: AnalysisContextViewModel | None,
    context: AnalysisContext | None,
    source_window: str,
) -> None:
    view_signal = build_view_signal()
    if view_signal is not None:
        if analysis_context_vm is not None:
            analysis_context_vm.send_to(
                "plot",
                context or analysis_context_for_view_signal(view_signal, source_window),
            )
        plot_manager.add_view_signal(view_signal, use_last=use_last)


def analysis_context_for_view_signal(view_signal: ViewSignal, source_window: str) -> AnalysisContext:
    """Capture the CAN evidence represented by a plotted signal."""
    signal = view_signal.signal
    return AnalysisContext.from_signal(
        can_id=signal.can_id or view_signal.selector.selected_id,
        start_bit=int(signal.start_bit),
        length=int(signal.length),
        little_endian=signal.le,
        source_window=source_window,
    )
