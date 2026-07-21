from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg

from config.app_config import get_text
from services.candidate_interpretations import CandidateItem
from services.constraint_search import Constraint, SearchExclusions, SearchResult, clamp_target, time_to_abs
from viewmodels.constraint_search_viewmodel import ConstraintSearchViewModel
from views.plot.time_axis import TimeAxisItem
from views.widgets.eta_progress_dialog import EtaProgressDialog


def _time_label(timezone_mode: str) -> str:
    if timezone_mode in ("none", None, ""):
        return "Time — elapsed HH:MM:SS from start of recording"
    return f"Time — clock HH:MM:SS ({timezone_mode})"


class ConstraintSearchWindow(QMainWindow):
    def __init__(
        self,
        candidate_items: list[CandidateItem],
        timezone_mode: str = "none",
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("constraint_search_title"))
        self.resize(640, 500)

        self._items = candidate_items
        self._timezone_mode = timezone_mode
        self._vm = ConstraintSearchViewModel(candidate_items, parent=self)
        self._progress: EtaProgressDialog | None = None
        self._last_constraints: list[Constraint] = []

        all_ts = [ts for item in candidate_items for ts in item.timestamps]
        self._t_min = min(all_ts) if all_ts else 0.0

        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        layout.addWidget(QLabel(_time_label(self._timezone_mode)))

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels([
            "Time (HH:MM:SS)",
            get_text("constraint_search_day_label"),
            "Proportional value  (0.0 = min · 1.0 = max)",
            "",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self._table.setColumnWidth(3, 70)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        btn_add = QPushButton("+ Add constraint", self)
        btn_add.clicked.connect(self._add_row)
        layout.addWidget(btn_add)

        params = QGroupBox("Search parameters", self)
        params_form = QFormLayout(params)

        prec_row = QHBoxLayout()
        self._prec_slider = QSlider(Qt.Horizontal, self)
        self._prec_slider.setRange(1, 300)
        self._prec_slider.setValue(10)
        self._prec_lbl = QLabel("±10 s", self)
        self._prec_lbl.setMinimumWidth(55)
        self._prec_slider.valueChanged.connect(
            lambda v: self._prec_lbl.setText(f"±{v} s")
        )
        prec_row.addWidget(self._prec_slider)
        prec_row.addWidget(self._prec_lbl)
        params_form.addRow(get_text("constraint_search_precision_label"), prec_row)

        self._tol_spin = QDoubleSpinBox(self)
        self._tol_spin.setRange(0.1, 50.0)
        self._tol_spin.setDecimals(1)
        self._tol_spin.setValue(5.0)
        self._tol_spin.setSuffix(" % of range")
        params_form.addRow(get_text("constraint_search_tolerance_label"), self._tol_spin)

        layout.addWidget(params)

        self.btn_search = QPushButton(get_text("constraint_search_button"), self)
        self.btn_search.setFixedHeight(36)
        self.btn_search.clicked.connect(self._run_search)
        layout.addWidget(self.btn_search)

    def _wire(self) -> None:
        self._vm.search_started.connect(self._on_search_started)
        self._vm.progress_changed.connect(self._on_progress)
        self._vm.search_finished.connect(self._on_search_finished)
        self._vm.search_canceled.connect(self._on_search_canceled)
        self._vm.search_failed.connect(self._on_search_failed)
        self._vm.results_changed.connect(self._on_results)

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        te = QTimeEdit(self)
        te.setDisplayFormat("HH:mm:ss")
        self._table.setCellWidget(row, 0, te)

        day_spin = QSpinBox(self)
        day_spin.setRange(0, 365)
        day_spin.setValue(0)
        day_spin.setToolTip(get_text("constraint_search_day_tooltip"))
        self._table.setCellWidget(row, 1, day_spin)

        self._table.setItem(row, 2, QTableWidgetItem("0.5"))

        btn_del = QPushButton(get_text("delete"), self)
        btn_del.clicked.connect(lambda: self._delete_row(btn_del))
        self._table.setCellWidget(row, 3, btn_del)

    def _delete_row(self, btn: QPushButton) -> None:
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, 3) is btn:
                self._table.removeRow(row)
                return

    def _parse_constraints(self) -> list[Constraint] | None:
        result: list[Constraint] = []
        clamped_rows: list[int] = []
        for row in range(self._table.rowCount()):
            te: QTimeEdit = self._table.cellWidget(row, 0)
            day_spin: QSpinBox = self._table.cellWidget(row, 1)
            val_item = self._table.item(row, 2)
            if te is None or val_item is None:
                continue
            t = te.time()
            day_offset = day_spin.value() if day_spin is not None else 0
            t_abs = time_to_abs(t.hour(), t.minute(), t.second(),
                                 self._t_min, self._timezone_mode, day_offset=day_offset)
            try:
                raw_val = float(val_item.text())
            except ValueError:
                QMessageBox.warning(
                    self,
                    get_text("constraint_search_invalid_input_title"),
                    get_text("constraint_search_invalid_input_message").format(row=row + 1),
                )
                return None
            norm_val, was_clamped = clamp_target(raw_val)  # B-22
            if was_clamped:
                clamped_rows.append(row + 1)
            result.append(Constraint(time_abs=t_abs, target_norm=norm_val, was_clamped=was_clamped))

        if clamped_rows:  # B-22: warn instead of clamping silently
            QMessageBox.warning(
                self,
                get_text("constraint_search_clamped_title"),
                get_text("constraint_search_clamped_message").format(
                    rows=", ".join(str(r) for r in clamped_rows)
                ),
            )
        return result

    def _run_search(self) -> None:
        if self._vm.running:
            return
        constraints = self._parse_constraints()
        if constraints is None:
            return
        if not constraints:
            QMessageBox.information(
                self,
                get_text("constraint_search_no_constraints_title"),
                get_text("constraint_search_no_constraints_message"),
            )
            return

        precision = float(self._prec_slider.value())
        tolerance = self._tol_spin.value() / 100.0  # absolute on 0-1 scale
        self._last_constraints = constraints
        self._vm.run(constraints, precision=precision, tolerance=tolerance)

    def _on_search_started(self) -> None:
        self._progress = EtaProgressDialog(get_text("constraint_search_loading"), get_text("cancel"), self)
        self._progress.setWindowTitle(get_text("constraint_search_title"))
        self._progress.canceled.connect(self._vm.cancel)
        self._progress.start()
        self.btn_search.setEnabled(False)

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress.report_progress(done, total)

    def _on_search_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self.btn_search.setEnabled(True)

    def _on_search_canceled(self) -> None:
        pass

    def _on_search_failed(self, message: str) -> None:
        QMessageBox.critical(self, get_text("constraint_search_title"), message)

    def _on_results(self, results: list[SearchResult], exclusions: SearchExclusions) -> None:
        if not results:  # B-24: explain why, instead of opening an empty results window
            message = get_text("constraint_search_no_results_message")
            if exclusions.total:
                message += "\n\n" + get_text("constraint_search_exclusions_summary").format(
                    too_few_samples=exclusions.too_few_samples,
                    zero_variance=exclusions.zero_variance,
                    no_data_near_constraint=exclusions.no_data_near_constraint,
                    outside_tolerance=exclusions.outside_tolerance,
                )
            QMessageBox.information(self, get_text("constraint_search_no_results_title"), message)
            return

        win = ConstraintResultsWindow(
            results, self._last_constraints, self._t_min, self._timezone_mode, exclusions, parent=self
        )
        win.show()

    def closeEvent(self, event) -> None:
        self._vm.shutdown()
        super().closeEvent(event)


class ConstraintResultsWindow(QMainWindow):
    def __init__(
        self,
        results: list[SearchResult],
        constraints: list[Constraint],
        t_min: float,
        timezone_mode: str,
        exclusions: SearchExclusions | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(f"Search Results — {len(results)} match(es)")
        self.resize(1000, 600)

        self._results = results
        self._constraints = constraints
        self._t_min = t_min
        self._timezone_mode = timezone_mode
        self._exclusions = exclusions

        self._build_ui()

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        summary = f"{len(self._results)} matching signal(s)"
        if self._exclusions and self._exclusions.total:
            summary += "\n" + get_text("constraint_search_exclusions_summary").format(
                too_few_samples=self._exclusions.too_few_samples,
                zero_variance=self._exclusions.zero_variance,
                no_data_near_constraint=self._exclusions.no_data_near_constraint,
                outside_tolerance=self._exclusions.outside_tolerance,
            )
        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        left_layout.addWidget(summary_label)

        self._list = QListWidget(self)
        for result in self._results:
            parts = [result.item.label]
            for i, (constraint, hit) in enumerate(zip(self._constraints, result.hits)):
                diff = abs(hit.norm_actual - constraint.target_norm) * 100
                parts.append(f"C{i+1}: {hit.actual:.4g}  (Δ{diff:.1f}%)")
            self._list.addItem(QListWidgetItem("  |  ".join(parts)))

        self._list.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self._list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        time_axis = TimeAxisItem(timezone_mode=self._timezone_mode, orientation="bottom")
        self._plot = pg.PlotWidget(axisItems={"bottom": time_axis})
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)
        right_layout.addWidget(self._plot, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        if self._results:
            self._list.setCurrentRow(0)

    def _on_select(self, row: int) -> None:
        self._plot.clear()
        if row < 0 or row >= len(self._results):
            return

        result = self._results[row]
        item = result.item
        self._plot.plot(
            list(item.timestamps), list(item.values),
            pen=pg.mkPen("#00ffff", width=2),
        )

        for constraint, hit in zip(self._constraints, result.hits):
            # vertical line at constraint time
            self._plot.addItem(pg.InfiniteLine(
                pos=constraint.time_abs, angle=90,
                pen=pg.mkPen("#ff6b6b", width=1, style=Qt.DashLine),
            ))
            # horizontal line at the actual (denormalized) value for this signal
            self._plot.addItem(pg.InfiniteLine(
                pos=hit.actual, angle=0,
                pen=pg.mkPen("#ffd93d", width=1, style=Qt.DashLine),
            ))
            # dot at the hit point
            self._plot.addItem(pg.ScatterPlotItem(
                [constraint.time_abs], [hit.actual],
                size=10,
                pen=pg.mkPen("#ff6b6b"),
                brush=pg.mkBrush("#ff6b6b"),
            ))

        self._plot.enableAutoRange()
        self._plot.autoRange()
