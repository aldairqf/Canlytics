from __future__ import annotations

import numpy as np
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg

from viewmodels.candidate_interpretations_viewmodel import CandidateItem
from views.plot.time_axis import TimeAxisItem


def _time_label(timezone_mode: str) -> str:
    if timezone_mode in ("none", None, ""):
        return "Time — elapsed HH:MM:SS from start of recording"
    return f"Time — clock HH:MM:SS ({timezone_mode})"


def _time_to_abs(hours: int, minutes: int, seconds: int,
                 t_min: float, timezone_mode: str) -> float:
    if timezone_mode in ("none", None, ""):
        return t_min + hours * 3600 + minutes * 60 + seconds
    try:
        tz = dt_timezone.utc if timezone_mode == "UTC" else ZoneInfo(timezone_mode)
        ref_dt = datetime.fromtimestamp(t_min, dt_timezone.utc).astimezone(tz)
        target_dt = ref_dt.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
        return target_dt.timestamp()
    except (ZoneInfoNotFoundError, OSError, ValueError):
        return t_min + hours * 3600 + minutes * 60 + seconds


def _normalize(ys: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return (normalized 0-1, y_min, y_span). If span==0 returns zeros."""
    y_min = float(ys.min())
    y_max = float(ys.max())
    span = y_max - y_min
    if span == 0.0:
        return np.zeros_like(ys), y_min, 0.0
    return (ys - y_min) / span, y_min, span


class ConstraintSearchWindow(QMainWindow):
    def __init__(
        self,
        candidate_items: list[CandidateItem],
        timezone_mode: str = "none",
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Value at Time Search")
        self.resize(640, 500)

        self._items = candidate_items
        self._timezone_mode = timezone_mode

        all_ts = [ts for item in candidate_items for ts in item.timestamps]
        self._t_min = min(all_ts) if all_ts else 0.0

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        layout.addWidget(QLabel(_time_label(self._timezone_mode)))

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels([
            "Time (HH:MM:SS)",
            "Proportional value  (0.0 = min · 1.0 = max)",
            "",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(2, 70)
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
        params_form.addRow("Time precision:", prec_row)

        self._tol_spin = QDoubleSpinBox(self)
        self._tol_spin.setRange(0.1, 50.0)
        self._tol_spin.setDecimals(1)
        self._tol_spin.setValue(5.0)
        self._tol_spin.setSuffix(" % of range")
        params_form.addRow("Value tolerance:", self._tol_spin)

        layout.addWidget(params)

        btn_search = QPushButton("Search", self)
        btn_search.setFixedHeight(36)
        btn_search.clicked.connect(self._run_search)
        layout.addWidget(btn_search)

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        te = QTimeEdit(self)
        te.setDisplayFormat("HH:mm:ss")
        self._table.setCellWidget(row, 0, te)

        self._table.setItem(row, 1, QTableWidgetItem("0.5"))

        btn_del = QPushButton("Delete", self)
        btn_del.clicked.connect(lambda: self._delete_row(btn_del))
        self._table.setCellWidget(row, 2, btn_del)

    def _delete_row(self, btn: QPushButton) -> None:
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, 2) is btn:
                self._table.removeRow(row)
                return

    def _parse_constraints(self) -> list[tuple[float, float]] | None:
        result = []
        for row in range(self._table.rowCount()):
            te: QTimeEdit = self._table.cellWidget(row, 0)
            val_item = self._table.item(row, 1)
            if te is None or val_item is None:
                continue
            t = te.time()
            t_abs = _time_to_abs(t.hour(), t.minute(), t.second(),
                                  self._t_min, self._timezone_mode)
            try:
                norm_val = float(val_item.text())
            except ValueError:
                QMessageBox.warning(
                    self, "Invalid input",
                    f"Row {row + 1}: value must be a number between 0.0 and 1.0."
                )
                return None
            norm_val = max(0.0, min(1.0, norm_val))
            result.append((t_abs, norm_val))
        return result

    def _run_search(self) -> None:
        constraints = self._parse_constraints()
        if constraints is None:
            return
        if not constraints:
            QMessageBox.information(
                self, "No constraints",
                "Add at least one constraint before searching."
            )
            return

        precision = float(self._prec_slider.value())
        tol = self._tol_spin.value() / 100.0  # absolute on 0-1 scale

        # Each result: (item, list of (norm_actual, actual, y_min, span) per constraint)
        results: list[tuple[CandidateItem, list[tuple[float, float, float, float]]]] = []

        for item in self._items:
            xs = np.array(item.timestamps, dtype=float)
            ys = np.array(item.values, dtype=float)
            if len(xs) < 2:
                continue

            y_norm, y_min, y_span = _normalize(ys)
            if y_span == 0.0:
                continue

            hit_data: list[tuple[float, float, float, float]] = []
            ok = True
            for t_abs, v_norm_target in constraints:
                mask = (xs >= t_abs - precision) & (xs <= t_abs + precision)
                if not mask.any():
                    ok = False
                    break

                if xs[0] <= t_abs <= xs[-1]:
                    interp_norm = float(np.interp(t_abs, xs, y_norm))
                    interp_actual = float(np.interp(t_abs, xs, ys))
                else:
                    w_xs = xs[mask]
                    w_yn = y_norm[mask]
                    w_ys = ys[mask]
                    idx = int(np.argmin(np.abs(w_xs - t_abs)))
                    interp_norm = float(w_yn[idx])
                    interp_actual = float(w_ys[idx])

                if abs(interp_norm - v_norm_target) > tol:
                    ok = False
                    break

                hit_data.append((interp_norm, interp_actual, y_min, y_span))

            if ok:
                results.append((item, hit_data))

        win = ConstraintResultsWindow(
            results, constraints, self._t_min, self._timezone_mode, parent=self
        )
        win.show()


class ConstraintResultsWindow(QMainWindow):
    def __init__(
        self,
        results: list[tuple[CandidateItem, list[tuple[float, float, float, float]]]],
        constraints: list[tuple[float, float]],
        t_min: float,
        timezone_mode: str,
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

        self._build_ui()

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.addWidget(QLabel(f"{len(self._results)} matching signal(s)"))

        self._list = QListWidget(self)
        for item, hit_data in self._results:
            parts = [item.label]
            for i, ((_, v_norm_tgt), (norm_actual, actual, _, _)) in enumerate(
                zip(self._constraints, hit_data)
            ):
                diff = abs(norm_actual - v_norm_tgt) * 100
                parts.append(f"C{i+1}: {actual:.4g}  (Δ{diff:.1f}%)")
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

        item, hit_data = self._results[row]
        self._plot.plot(
            list(item.timestamps), list(item.values),
            pen=pg.mkPen("#00ffff", width=2),
        )

        for (t_abs, _), (_, actual, y_min, y_span) in zip(self._constraints, hit_data):
            # vertical line at constraint time
            self._plot.addItem(pg.InfiniteLine(
                pos=t_abs, angle=90,
                pen=pg.mkPen("#ff6b6b", width=1, style=Qt.DashLine),
            ))
            # horizontal line at the actual (denormalized) value for this signal
            self._plot.addItem(pg.InfiniteLine(
                pos=actual, angle=0,
                pen=pg.mkPen("#ffd93d", width=1, style=Qt.DashLine),
            ))
            # dot at the hit point
            self._plot.addItem(pg.ScatterPlotItem(
                [t_abs], [actual],
                size=10,
                pen=pg.mkPen("#ff6b6b"),
                brush=pg.mkBrush("#ff6b6b"),
            ))

        self._plot.enableAutoRange()
        self._plot.autoRange()
