from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_option, get_text
from config.theme import Theme, get_active_theme
from models.analysis_context import AnalysisContext
from services.bit_activity import BitActivitySnapshot, BitSignalSuggestion
from utils.can_id import can_id_sort_key
from views.plot.add_to_plot_menu import analysis_send_destinations, show_send_to_menu
from viewmodels.bit_activity_viewmodel import BitActivityViewModel
from views.widgets.eta_progress_dialog import EtaProgressDialog

if TYPE_CHECKING:
    from viewmodels.analysis_context_viewmodel import AnalysisContextViewModel

_BIT_COUNT = 64
_CLASS_TEXT = {
    "physical": "bit_activity_class_physical",
    "counter": "bit_activity_class_counter",
    "crc": "bit_activity_class_crc",
    "constant": "bit_activity_class_constant",
    "insufficient": "bit_activity_class_insufficient",
}


class BitActivityWindow(QMainWindow):
    def __init__(
        self,
        vm: BitActivityViewModel,
        *,
        analysis_context_vm: AnalysisContextViewModel | None = None,
        is_live: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("bit_activity_title"))
        self.resize(1500, 850)
        self._vm = vm
        self._analysis_context_vm = analysis_context_vm
        self._is_live = is_live or (lambda: False)
        self._snapshots: dict[str, BitActivitySnapshot] = {}
        self._row_by_id: dict[str, int] = {}
        self._selected_id: str | None = None
        self._pending: dict[str, BitActivitySnapshot] = {}
        self._progress: EtaProgressDialog | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(int(get_option("bit_activity_ui_refresh_ms", 400)))
        self._refresh_timer.timeout.connect(self._flush_pending)
        self._build_ui()
        self._wire()
        app = QApplication.instance()
        self._theme_app = app
        if app is not None:
            app.paletteChanged.connect(self._apply_theme)
        if vm.results:
            self._on_results(vm.results, True)

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        controls = QHBoxLayout()
        self.btn_refresh = QPushButton(get_text("bit_activity_refresh"), self)
        self.btn_refresh.setObjectName("primary")
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText(get_text("bit_activity_search"))
        self.status_label = QLabel(self)
        controls.addWidget(self.btn_refresh)
        controls.addWidget(self.search_box, 1)
        controls.addWidget(self.status_label)
        controls.addWidget(QLabel("0%", self))
        self.legend_bar = QFrame(self)
        self.legend_bar.setFixedSize(110, 14)
        controls.addWidget(self.legend_bar)
        controls.addWidget(QLabel("100%", self))
        layout.addLayout(controls)

        self.note_label = QLabel(get_text("bit_activity_heuristic_note"), self)
        self.note_label.setObjectName("panel_header")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)
        self.bit_detail = QLabel(get_text("bit_activity_cell_hint"), self)
        layout.addWidget(self.bit_detail)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.matrix = QTableWidget(0, _BIT_COUNT + 1, splitter)
        self.matrix.setHorizontalHeaderLabels([
            get_text("bit_activity_can_id"),
            *(f"b{bit}" for bit in range(_BIT_COUNT)),
        ])
        self.matrix.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.matrix.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.matrix.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.matrix.verticalHeader().setVisible(False)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.matrix.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.matrix.setColumnWidth(0, 92)
        for column in range(1, _BIT_COUNT + 1):
            self.matrix.setColumnWidth(column, 23)
        self.matrix.verticalHeader().setDefaultSectionSize(24)
        self.matrix.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        splitter.addWidget(self.matrix)

        self.details = QTabWidget(splitter)
        self.details.setMinimumWidth(320)
        self.segments = QTableWidget(0, 4, self.details)
        self.segments.setHorizontalHeaderLabels([
            get_text("bit_activity_start_bit"),
            get_text("bit_activity_length"),
            get_text("bit_activity_class"),
            get_text("bit_activity_samples"),
        ])
        self.segments.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.segments.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.segments.verticalHeader().setVisible(False)
        self.segments.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        segment_panel = QWidget(self.details)
        segment_layout = QVBoxLayout(segment_panel)
        segment_actions = QHBoxLayout()
        segment_actions.addStretch(1)
        self.btn_send_segment = QPushButton(get_text("bit_activity_send_to"), segment_panel)
        self.btn_send_segment.setEnabled(False)
        segment_actions.addWidget(self.btn_send_segment)
        segment_layout.addLayout(segment_actions)
        segment_layout.addWidget(self.segments, 1)
        self.segment_detail = QLabel(get_text("bit_activity_segment_hint"), segment_panel)
        segment_layout.addWidget(self.segment_detail)
        self.details.addTab(segment_panel, get_text("bit_activity_segments"))

        histogram_panel = QWidget(self.details)
        histogram_layout = QVBoxLayout(histogram_panel)
        histogram_controls = QHBoxLayout()
        histogram_controls.addWidget(QLabel(get_text("bit_activity_byte"), histogram_panel))
        self.byte_selector = QComboBox(histogram_panel)
        for index in range(8):
            self.byte_selector.addItem(f"D{index}", index)
        histogram_controls.addWidget(self.byte_selector)
        histogram_layout.addLayout(histogram_controls)
        self.histogram_plot = pg.PlotWidget(histogram_panel)
        self.histogram_plot.setLabel("bottom", get_text("bit_activity_byte_value"))
        self.histogram_plot.setLabel("left", get_text("bit_activity_frequency"))
        self.histogram_plot.setXRange(-1, 256)
        self.histogram_plot.setMouseEnabled(x=False, y=False)
        self.histogram_note = QLabel(get_text("bit_activity_no_histogram"), histogram_panel)
        histogram_layout.addWidget(self.histogram_note)
        histogram_layout.addWidget(self.histogram_plot, 1)
        self.details.addTab(histogram_panel, get_text("bit_activity_histogram"))
        splitter.addWidget(self.details)
        splitter.setSizes([1120, 360])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self._apply_theme()

    def _wire(self) -> None:
        self.btn_refresh.clicked.connect(self._refresh)
        self.search_box.textChanged.connect(self._render_matrix)
        self.matrix.currentCellChanged.connect(self._on_current_cell_changed)
        self.matrix.cellClicked.connect(self._on_cell_clicked)
        self.segments.itemSelectionChanged.connect(self._on_segment_selection_changed)
        self.btn_send_segment.clicked.connect(self._send_selected_segment)
        self.byte_selector.currentIndexChanged.connect(self._render_histogram)
        self._vm.analysis_started.connect(self._on_started)
        self._vm.analysis_finished.connect(self._on_finished)
        self._vm.analysis_failed.connect(self._on_failed)
        self._vm.progress_changed.connect(self._on_progress)
        self._vm.results_changed.connect(self._on_results)

    def _refresh(self) -> None:
        if not self._vm.running:
            self._vm.start_analysis()

    def _on_started(self) -> None:
        self._progress = EtaProgressDialog(get_text("bit_activity_loading"), get_text("cancel"), self)
        self._progress.setWindowTitle(get_text("bit_activity_title"))
        self._progress.canceled.connect(self._vm.cancel_analysis)
        self._progress.start()
        self.btn_refresh.setEnabled(False)

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress.report_progress(done, total)

    def _on_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self.btn_refresh.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        QMessageBox.warning(self, get_text("bit_activity_title"), message)

    def _on_results(self, snapshots: tuple[BitActivitySnapshot, ...], reset: bool) -> None:
        if reset:
            self._pending.clear()
            self._refresh_timer.stop()
            self._snapshots = {item.can_id: item for item in snapshots}
            self._render_matrix()
            return
        self._pending.update({item.can_id: item for item in snapshots})
        if self._pending and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _flush_pending(self) -> None:
        if not self._pending:
            self._refresh_timer.stop()
            return
        self._refresh_timer.stop()
        current = self._selected_id
        has_new_id = False
        for can_id, item in self._pending.items():
            self._snapshots[can_id] = item
            row = self._row_by_id.get(can_id)
            if row is None and self._matches_search(can_id):
                has_new_id = True
            elif row is not None:
                self._render_row(row, item)
        self._pending.clear()
        if has_new_id:
            self._render_matrix(preserve_selection=True)
        self._update_status()
        if current and current in self._snapshots:
            self._selected_id = current
            self._render_details(self._snapshots[current], preserve_selection=True)
            row = self._row_by_id.get(current)
            if row is not None:
                self._render_cell_detail(row, self.matrix.currentColumn())

    def _render_matrix(self, *_args: object, preserve_selection: bool = False) -> None:
        previous = self._selected_id if preserve_selection else None
        search = self.search_box.text().strip().upper()
        can_ids = [
            can_id for can_id in self._snapshots
            if not search or search in can_id
        ]
        can_ids.sort(key=can_id_sort_key)
        self.matrix.setSortingEnabled(False)
        self.matrix.setRowCount(len(can_ids))
        self._row_by_id = {can_id: row for row, can_id in enumerate(can_ids)}
        for row, can_id in enumerate(can_ids):
            self._render_row(row, self._snapshots[can_id])
        self.matrix.setSortingEnabled(False)
        if can_ids:
            selected = previous if previous in self._row_by_id else can_ids[0]
            self._selected_id = selected
            row = self._row_by_id[selected]
            self.matrix.setCurrentCell(row, 0)
            self._render_details(self._snapshots[selected], preserve_selection=preserve_selection)
        else:
            self._selected_id = None
            self._render_details(None)
        self._update_status()

    def _render_row(self, row: int, snapshot: BitActivitySnapshot) -> None:
        id_item = self.matrix.item(row, 0) or QTableWidgetItem()
        id_item.setText(snapshot.can_id)
        id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        id_item.setToolTip(get_text("bit_activity_frames_tooltip").format(count=snapshot.frame_count))
        self.matrix.setItem(row, 0, id_item)
        theme = get_active_theme()
        boundaries = set(snapshot.boundaries)
        for bit in range(_BIT_COUNT):
            rate = snapshot.flip_rates[bit] if bit < len(snapshot.flip_rates) else None
            item = self.matrix.item(row, bit + 1) or QTableWidgetItem()
            item.setText("·" if rate is None else "│" if bit in boundaries else "")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setBackground(_heat_color(rate, theme))
            item.setForeground(QColor(theme.text))
            if rate is None:
                tooltip = get_text("bit_activity_no_comparisons")
            else:
                flips = snapshot.bit_flip_counts[bit]
                comparisons = snapshot.bit_comparison_counts[bit]
                tooltip = get_text("bit_activity_cell_tooltip").format(
                    can_id=snapshot.can_id,
                    bit=bit,
                    rate=rate * 100.0,
                    flips=flips,
                    comparisons=comparisons,
                )
            if bit in boundaries:
                tooltip += "\n" + get_text("bit_activity_boundary_tooltip")
            item.setToolTip(tooltip)
            self.matrix.setItem(row, bit + 1, item)

    def _on_current_cell_changed(self, row: int, _column: int, _previous_row: int, _previous_column: int) -> None:
        if row < 0:
            self.bit_detail.setText(get_text("bit_activity_cell_hint"))
            return
        id_item = self.matrix.item(row, 0)
        if id_item is None:
            return
        can_id = id_item.text()
        previous_id = self._selected_id
        self._selected_id = can_id
        if previous_id != can_id:
            self._render_details(self._snapshots.get(can_id))
        self._render_cell_detail(row, _column)

    def _render_details(self, snapshot: BitActivitySnapshot | None, *, preserve_selection: bool = False) -> None:
        selected_start = None
        if preserve_selection:
            selected_rows = self.segments.selectionModel().selectedRows()
            if selected_rows:
                selected_item = self.segments.item(selected_rows[0].row(), 0)
                suggestion = selected_item.data(Qt.ItemDataRole.UserRole) if selected_item else None
                selected_start = suggestion.start_bit if isinstance(suggestion, BitSignalSuggestion) else None
        selected_byte = self.byte_selector.currentIndex() if preserve_selection else 0
        self.segments.setRowCount(0)
        self.segment_detail.setText(get_text("bit_activity_segment_hint"))
        self.histogram_plot.clear()
        if snapshot is None:
            self._render_histogram()
            return
        self.segments.setRowCount(len(snapshot.suggestions))
        for row, suggestion in enumerate(snapshot.suggestions):
            values = (
                str(suggestion.start_bit),
                str(suggestion.length),
                get_text(_CLASS_TEXT[suggestion.kind]),
                str(suggestion.sample_count),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, suggestion)
                self.segments.setItem(row, column, item)
        if snapshot.suggestions:
            selected_row = next((
                row for row, suggestion in enumerate(snapshot.suggestions)
                if suggestion.start_bit == selected_start
            ), 0)
            self.segments.selectRow(selected_row)
        self.byte_selector.setCurrentIndex(min(selected_byte, self.byte_selector.count() - 1))
        self._render_histogram()

    def _render_histogram(self, *_args: object) -> None:
        self.histogram_plot.clear()
        self.histogram_note.setText(get_text("bit_activity_no_histogram"))
        self.histogram_note.setVisible(True)
        if self._selected_id is None:
            return
        snapshot = self._snapshots.get(self._selected_id)
        byte_index = self.byte_selector.currentData()
        if snapshot is None or byte_index is None or byte_index >= len(snapshot.byte_histograms):
            return
        histogram = snapshot.byte_histograms[int(byte_index)]
        self.histogram_note.setText(get_text("bit_activity_histogram_samples").format(
            count=histogram.sample_count
        ))
        self.histogram_note.setVisible(histogram.sample_count > 0)
        color = get_active_theme().accent
        self.histogram_plot.addItem(pg.BarGraphItem(
            x=list(range(256)), height=list(histogram.counts), width=0.85, brush=pg.mkColor(color)
        ))
        self.histogram_plot.setYRange(0, max(1, max(histogram.counts)))

    def _update_status(self) -> None:
        total_frames = sum(item.frame_count for item in self._snapshots.values())
        if total_frames:
            self.status_label.setText(get_text("bit_activity_status").format(
                ids=len(self._snapshots), frames=total_frames
            ))
        else:
            self.status_label.setText(get_text("bit_activity_empty"))

    def _on_cell_clicked(self, row: int, column: int) -> None:
        self._render_cell_detail(row, column)

    def _render_cell_detail(self, row: int, column: int) -> None:
        if column <= 0:
            self.bit_detail.setText(get_text("bit_activity_cell_hint"))
            return
        id_item = self.matrix.item(row, 0)
        if id_item is None:
            return
        snapshot = self._snapshots.get(id_item.text())
        bit = column - 1
        if snapshot is None or bit >= len(snapshot.flip_rates):
            self.bit_detail.setText(get_text("bit_activity_cell_hint"))
            return
        rate = snapshot.flip_rates[bit]
        if rate is None:
            self.bit_detail.setText(get_text("bit_activity_no_comparisons"))
            return
        magnitude = snapshot.magnitudes[bit]
        self.bit_detail.setText(get_text("bit_activity_cell_detail").format(
            can_id=snapshot.can_id,
            bit=bit,
            rate=rate * 100.0,
            flips=snapshot.bit_flip_counts[bit],
            comparisons=snapshot.bit_comparison_counts[bit],
            magnitude=f"{magnitude:.3f}" if magnitude is not None else "−∞",
        ))

    def _on_segment_selection_changed(self) -> None:
        selected = self.segments.selectionModel().selectedRows()
        self.btn_send_segment.setEnabled(bool(selected) and self._analysis_context_vm is not None)
        if not selected:
            return
        row = selected[0].row()
        item = self.segments.item(row, 0)
        if item is None:
            return
        suggestion = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggestion, BitSignalSuggestion):
            return
        self.segment_detail.setText(get_text("bit_activity_segment_detail").format(
            start=suggestion.start_bit,
            end=suggestion.start_bit + suggestion.length - 1,
            kind=get_text(_CLASS_TEXT[suggestion.kind]),
            samples=suggestion.sample_count,
        ))

    def _send_selected_segment(self) -> None:
        selected = self.segments.selectionModel().selectedRows()
        if not selected or self._analysis_context_vm is None or self._selected_id is None:
            return
        item = self.segments.item(selected[0].row(), 0)
        suggestion = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(suggestion, BitSignalSuggestion):
            return
        context = AnalysisContext.from_signal(
            can_id=self._selected_id,
            start_bit=suggestion.start_bit,
            length=suggestion.length,
            little_endian=True,
            source_window=get_text("bit_activity_title"),
        )
        destinations = analysis_send_destinations(
            self._analysis_context_vm,
            context,
            realtime_enabled=self._is_live(),
        )
        point = self.btn_send_segment.mapToGlobal(QPoint(0, self.btn_send_segment.height()))
        show_send_to_menu(self, point, destinations)

    def _matches_search(self, can_id: str) -> bool:
        search = self.search_box.text().strip().upper()
        return not search or search in can_id

    def _apply_theme(self, *_args: object) -> None:
        theme = get_active_theme()
        self.histogram_plot.setBackground(theme.plot_bg)
        self.legend_bar.setStyleSheet(
            "QFrame { border: 1px solid " + theme.border + "; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 " + theme.surface_alt + ", stop:0.5 " + theme.accent + ", stop:1 " + theme.warn + "); }"
        )
        for axis_name in ("left", "bottom"):
            axis = self.histogram_plot.getAxis(axis_name)
            axis.setTextPen(theme.plot_axis)
            axis.setPen(theme.border)
        self.histogram_plot.getPlotItem().getViewBox().setBackgroundColor(theme.plot_bg)
        if hasattr(self, "matrix"):
            self._render_matrix(preserve_selection=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._theme_app is not None:
            try:
                self._theme_app.paletteChanged.disconnect(self._apply_theme)
            except (RuntimeError, TypeError):
                pass
        self._vm.deactivate()
        self._refresh_timer.stop()
        super().closeEvent(event)


def _heat_color(rate: float | None, theme: Theme) -> QColor:
    if rate is None:
        return QColor(theme.surface)
    if rate <= 0.5:
        return _mix(QColor(theme.surface_alt), QColor(theme.accent), rate / 0.5)
    return _mix(QColor(theme.accent), QColor(theme.warn), (rate - 0.5) / 0.5)


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    amount = min(max(float(amount), 0.0), 1.0)
    return QColor(*(
        round(left + (right - left) * amount)
        for left, right in zip(first.getRgb()[:3], second.getRgb()[:3])
    ))
