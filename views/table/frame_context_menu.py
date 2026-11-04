from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu, QWidget

from config.app_config import get_text
from models.analysis_context import AnalysisContext
from models.frame_selector import FrameSelector
from models.signal import Signal
from utils.can_bytes import parse_hex_bytes
from views.plot.add_to_plot_menu import make_view_signal
from viewmodels.view_signal import ViewSignal


def _payload_bytes(data_hex: object) -> bytes:
    return parse_hex_bytes("".join(str(data_hex or "").split()))


def format_copied_frame(row_record: dict[str, object]) -> str:
    can_id = str(row_record.get("ID") or "")
    payload = _payload_bytes(row_record.get("DATA"))
    bus = str(row_record.get("Bus") or "").strip()
    frame = f"{can_id}#{payload.hex().upper()}"
    return f"{bus} {frame}".strip()


def build_byte_view_signal(can_id: str, byte_index: int) -> ViewSignal:
    signal = Signal(
        name=f"{can_id}.B{byte_index}",
        can_id=can_id,
        start_bit=byte_index * 8,
        length=8,
        le=True,
        type_data="uint",
    )
    selector = FrameSelector(selected_id=can_id, mode="exact")
    return make_view_signal(signal, selector)


def show_frame_context_menu(
    parent: QWidget,
    global_pos: object,
    row_record: dict[str, object],
    *,
    plot_manager: object,
    candidate_manager: object,
    analysis_context_vm=None,
) -> None:
    can_id = str(row_record.get("ID") or "")
    data_hex = str(row_record.get("DATA") or "")
    payload = _payload_bytes(data_hex)
    menu = QMenu(parent)
    copy_id = menu.addAction(get_text("frame_context_copy_id"))
    copy_id.setEnabled(bool(can_id))
    copy_frame = menu.addAction(get_text("frame_context_copy_frame"))
    copy_frame.setEnabled(bool(can_id))
    plot_menu = menu.addMenu(get_text("frame_context_plot_byte"))
    plot_menu.setEnabled(bool(can_id and payload and plot_manager is not None))
    plot_actions = {
        plot_menu.addAction(get_text("frame_context_byte_item").format(index=index)): index
        for index in range(len(payload))
    }
    save_menu = menu.addMenu(get_text("frame_context_save_signal"))
    save_menu.setEnabled(bool(can_id and payload and analysis_context_vm is not None))
    save_actions = {
        save_menu.addAction(get_text("frame_context_byte_item").format(index=index)): index
        for index in range(len(payload))
    }
    open_candidate = menu.addAction(get_text("frame_context_open_candidate"))
    open_candidate.setEnabled(bool(can_id and candidate_manager is not None))

    context = AnalysisContext(
        can_id=can_id or None,
        source_window=get_text("analysis_source_main_table"),
    )
    plugin_actions = {}
    if analysis_context_vm is not None:
        context_actions = analysis_context_vm.plugin_context_actions(context)
        plugin_menu = menu.addMenu(get_text("plugins_context_menu")) if context_actions else None
        for label, callback in context_actions.items():
            plugin_actions[plugin_menu.addAction(label)] = callback

    action = menu.exec(global_pos)
    if action is copy_id:
        QGuiApplication.clipboard().setText(can_id)
    elif action is copy_frame:
        QGuiApplication.clipboard().setText(format_copied_frame(row_record))
    elif action in plot_actions:
        byte_index = plot_actions[action]
        plot_manager.add_view_signal(build_byte_view_signal(can_id, byte_index), use_last=True)
    elif action in save_actions:
        byte_index = save_actions[action]
        analysis_context_vm.send_to(
            "working_dbc",
            AnalysisContext(
                can_id=can_id,
                byte_indices=(byte_index,),
                source_window=get_text("analysis_source_main_table"),
            ),
        )
    elif action is open_candidate:
        candidate_manager.open_window_for_can_id(
            can_id, source=get_text("frame_context_candidate_source")
        )
    elif action in plugin_actions:
        plugin_actions[action]()
