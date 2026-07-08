from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.signal_coverage import SignalCoverageItem
from viewmodels.signal_coverage_viewmodel import SignalCoverageViewModel
from viewmodels.view_signal import ViewSignal
from views.icons import icon
from views.plot.add_to_plot_menu import make_view_signal, show_add_to_plot_menu
from views.settings.signal_coverage_filters_dialog import SignalCoverageFiltersDialog

if TYPE_CHECKING:
    from views.plot.plot_window_manager import PlotWindowManager

_COLUMN_KEYS = [
    "signal_coverage_col_parameter", "signal_coverage_col_message", "signal_coverage_col_dbc",
    "signal_coverage_col_can_id", "signal_coverage_col_pgn", "signal_coverage_col_unit",
    "signal_coverage_col_decoding", "signal_coverage_col_frames", "signal_coverage_col_unique",
    "signal_coverage_col_min", "signal_coverage_col_max", "signal_coverage_col_mean",
    "signal_coverage_col_description",
]
_DESCRIPTION_COL = len(_COLUMN_KEYS) - 1
_NUMERIC_COLS = {7: "frame_count", 8: "unique_count", 9: "min_value", 10: "max_value", 11: "mean_value"}


class _NumericItem(QTableWidgetItem):
    """Sorts by the underlying number instead of the displayed text."""

    def __init__(self, value: float, text: str):
        super().__init__(text)
        self._value = value

    def __lt__(self, other) -> bool:
        if isinstance(other, _NumericItem):
            return self._value < other._value
        return super().__lt__(other)


class SignalCoverageWindow(QMainWindow):
    def __init__(self, vm: SignalCoverageViewModel, *, plot_manager: PlotWindowManager | None = None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("signal_coverage_title"))
        self.resize(1200, 700)

        self._vm = vm
        self._plot_manager = plot_manager
        self._results: list[SignalCoverageItem] = []
        self._progress: QProgressDialog | None = None
        self._filters: dict[str, bool] = {
            "exclude_no_data": True,
            "only_changing": False,
            "byte_aligned_only": True,
            "hide_pdu1": False,
        }

        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)

        controls = QHBoxLayout()
        self.btn_analyze = QPushButton(get_text("signal_coverage_analyze"), self)
        self.btn_analyze.setObjectName("primary")
        self.btn_filters = QPushButton(icon("sliders-horizontal"), get_text("signal_coverage_filters_button"), self)
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText(get_text("signal_coverage_search_placeholder"))
        controls.addWidget(self.btn_analyze)
        controls.addWidget(self.btn_filters)
        controls.addWidget(self.search_box, 1)
        layout.addLayout(controls)

        self.status_label = QLabel(self)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(_COLUMN_KEYS), self)
        self.table.setHorizontalHeaderLabels([get_text(key) for key in _COLUMN_KEYS])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(_DESCRIPTION_COL, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        layout.addWidget(self.table, 1)

        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(120)
        layout.addWidget(self.detail)

        self.setCentralWidget(central)

    def _wire(self) -> None:
        self.btn_analyze.clicked.connect(self._analyze)
        self.btn_filters.clicked.connect(self._open_filters)
        self.search_box.textChanged.connect(self._render_table)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.customContextMenuRequested.connect(self._open_plot_context_menu)

        self._vm.analysis_started.connect(self._on_started)
        self._vm.analysis_finished.connect(self._on_finished)
        self._vm.analysis_failed.connect(self._on_failed)
        self._vm.results_changed.connect(self._on_results)
        self._vm.progress_changed.connect(self._on_progress)

    def _analyze(self) -> None:
        if self._vm.running:
            return
        self._vm.start_analysis()

    def _open_filters(self) -> None:
        dlg = SignalCoverageFiltersDialog(self._filters, parent=self)
        if dlg.exec():
            self._filters = dlg.get_filter_state()
            self._render_table()

    def _on_started(self) -> None:
        # Range starts at (0, 0) -- an indeterminate/busy bar -- until the first
        # progress_changed signal reports the real signal count and switches it
        # to a determinate percentage.
        self._progress = QProgressDialog(get_text("signal_coverage_loading"), get_text("cancel"), 0, 0, self)
        self._progress.setWindowTitle(get_text("signal_coverage_title"))
        self._progress.setWindowModality(Qt.ApplicationModal)
        self._progress.setMinimumDuration(0)
        self._progress.canceled.connect(self._vm.cancel_analysis)
        self._progress.show()
        self._set_controls_enabled(False)

    def _on_progress(self, done: int, total: int) -> None:
        # QProgressDialog.setValue() pumps the event loop internally, which can
        # deliver an already-queued "finished" signal and null self._progress
        # (via _on_finished) *during* this call -- snapshot it locally so the
        # rest of this method keeps using the (still-alive, just closed) dialog
        # instead of re-reading self._progress and crashing on None.
        dialog = self._progress
        if dialog is None:
            return
        dialog.setRange(0, total)
        dialog.setValue(done)
        dialog.setLabelText(f"{get_text('signal_coverage_loading')} ({done}/{total})")

    def _on_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_controls_enabled(True)

    def _on_failed(self, message: str) -> None:
        QMessageBox.warning(self, get_text("signal_coverage_title"), message)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.btn_analyze, self.btn_filters, self.search_box):
            widget.setEnabled(enabled)

    def _on_results(self, items: list[SignalCoverageItem]) -> None:
        self._results = list(items)
        self._render_table()

    def _render_table(self) -> None:
        # Full rebuild rather than show/hide rows: "exclude no data" doesn't
        # just hide rows, it changes WHICH stat set (stats_all vs stats_real)
        # is displayed for the rows that stay -- a pure setRowHidden() pass
        # can't do that, and none of these filters re-run the scan.
        exclude_no_data = self._filters["exclude_no_data"]
        only_changing = self._filters["only_changing"]
        byte_aligned_only = self._filters["byte_aligned_only"]
        hide_pdu1 = self._filters["hide_pdu1"]
        search = self.search_box.text().strip().lower()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        shown = 0
        for item in self._results:
            if exclude_no_data:
                if item.stats_real is None:
                    continue
                stats = item.stats_real
            else:
                stats = item.stats_all
            if only_changing and not stats.is_changing:
                continue
            if byte_aligned_only and not item.byte_aligned:
                continue
            if hide_pdu1 and item.is_pdu1:
                continue
            if search and search not in f"{item.signal_name} {item.message_name}".lower():
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                item.signal_name,
                item.message_name,
                item.dbc_name,
                item.can_id,
                item.pgn or "",
                item.unit,
                item.decoding_summary,
                (stats.frame_count, str(stats.frame_count)),
                (stats.unique_count, str(stats.unique_count)),
                (stats.min_value, f"{stats.min_value:g}"),
                (stats.max_value, f"{stats.max_value:g}"),
                (stats.mean_value, f"{stats.mean_value:g}"),
                item.description,
            ]
            for col, value in enumerate(values):
                if col in _NUMERIC_COLS:
                    numeric, text = value
                    cell = _NumericItem(numeric, text)
                else:
                    cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.UserRole, item)
                if col == _DESCRIPTION_COL and value:
                    cell.setToolTip(value)
                self.table.setItem(row, col, cell)
            shown += 1
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(_DESCRIPTION_COL, QHeaderView.Stretch)
        self.status_label.setText(
            get_text("signal_coverage_status").format(shown=shown, total=len(self._results))
        )

    def _open_plot_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        cell = self.table.item(row, 0)
        if cell is None:
            return
        item: SignalCoverageItem = cell.data(Qt.UserRole)
        show_add_to_plot_menu(
            self, self.table.viewport().mapToGlobal(pos), self._plot_manager,
            lambda: self._build_view_signal(item),
        )

    @staticmethod
    def _build_view_signal(item: SignalCoverageItem) -> ViewSignal:
        # can_id is the specific observed frame id (see services/signal_coverage.py),
        # not just the PGN -- setting it here makes j1939 items narrow the plot
        # to exactly the source this row represents, matching how the scan
        # itself keeps multiple sources of one PGN as separate rows/stats.
        signal = Signal(
            name=item.signal_name,
            can_id=item.can_id,
            start_bit=item.start_bit,
            length=item.length,
            le=item.byte_order == "little_endian",
            scale=item.scale,
            offset=item.offset,
            mux_start=item.mux_start,
            mux_bytes=item.mux_bytes,
            mux_value=item.mux_value,
            type_data=item.value_type,
        )
        pgn_int = int(item.pgn, 16) if item.pgn else None
        selector = FrameSelector(selected_id=item.can_id, mode=item.match_mode, pgn=pgn_int)
        return make_view_signal(signal, selector)

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail.setPlainText("")
            return
        item: SignalCoverageItem = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        id_line = f"DBC: {item.dbc_name}    Message: {item.message_name}    CAN ID: {item.can_id}"
        if item.pgn:
            id_line += f"    PGN: {item.pgn}"
        id_line += f" ({item.match_mode})"
        self.detail.setPlainText(
            "\n".join(
                [
                    id_line,
                    f"Decoding: {item.decoding_summary}",
                    f"Description: {item.description or '-'}",
                ]
            )
        )

    def closeEvent(self, event) -> None:
        self._vm.cancel_analysis()
        super().closeEvent(event)
