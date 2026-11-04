from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LiveInspector(QWidget):
    def __init__(self, context):
        super().__init__()
        self.setWindowTitle("Live Inspector")
        self._count = 0
        self._status = QLabel("Waiting for live frames")
        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        context.subscribe_live_chunks(self._on_chunk, lifetime=self)

    def _on_chunk(self, chunk):
        self._count += chunk.height
        self._status.setText(f"Received {self._count:,} frames")


def register(api, context):
    api.register_window("live-inspector", LiveInspector)
    api.register_send_to_action(
        "summarize-session",
        lambda analysis_context: context.analysis.summarize(
            context.get_frames(), analysis_context.can_id
        ),
    )
    api.register_context_action(
        "inspect-markers",
        lambda analysis_context: context.list_session_markers(),
    )
