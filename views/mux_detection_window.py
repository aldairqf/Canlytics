from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from config.app_config import get_text
from config.theme import get_active_theme
from config.defaults import (MUX_SENSITIVITY_MAX_VALUES_HIGH, MUX_SENSITIVITY_MAX_VALUES_LOW,
                             MUX_SENSITIVITY_MIN_GAIN_HIGH, MUX_SENSITIVITY_MIN_GAIN_LOW)
from views.widgets.eta_progress_dialog import EtaProgressDialog


class MuxDetectionWindow(QDialog):
    def __init__(self, vm, *, time_config_vm=None, timezone_mode="none", time_range_vm=None, candidate_manager=None, session_state=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._candidate_manager = candidate_manager
        self._session_state = session_state
        self.setWindowTitle(get_text("mux_detection_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        self.detect_button = QPushButton(get_text("mux_detect_button"))
        self.only_mux = QCheckBox(get_text("mux_only_with_mux"))
        self.only_mux.setChecked(True)
        self.only_mux.toggled.connect(lambda _checked: self._set_results(self._vm.results))
        self.summary = QLabel(get_text("mux_summary").format(muxed=0, total=0))
        self.empty_state = QLabel(get_text("mux_result_empty_intro"))
        self.empty_state.setWordWrap(True)
        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels([
            get_text("mux_result_id"), get_text("mux_result_selector"),
            get_text("mux_result_values"), get_text("mux_result_confidence"),
            get_text("mux_result_status"),
        ])
        self.results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.verticalHeader().setVisible(False)
        for column in (0, 1, 2, 3):
            self.results.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.advanced_toggle = QCheckBox(get_text("mux_advanced"))
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        self.selector_chips = QWidget()
        self.selector_chips_layout = QHBoxLayout(self.selector_chips)
        self.selector_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.discard_reasons = QLabel()
        self.discard_reasons.setWordWrap(True)
        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity_value = QLabel()
        self.values = QTableWidget(0, 6)
        self.values.setHorizontalHeaderLabels([
            get_text("mux_include_value"), get_text("mux_value"), get_text("mux_value_n"),
            get_text("mux_value_period"), get_text("mux_value_cv"), get_text("mux_value_dlc"),
        ])
        self.values.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        advanced_layout.addWidget(QLabel(get_text("mux_selector_bytes")))
        advanced_layout.addWidget(self.selector_chips)
        advanced_layout.addWidget(QLabel(get_text("mux_sensitivity")))
        advanced_layout.addWidget(self.sensitivity_value)
        advanced_layout.addWidget(self.sensitivity)
        advanced_layout.addWidget(self.discard_reasons)
        advanced_layout.addWidget(self.values)
        self.advanced.setVisible(False)
        self.advanced_toggle.setChecked(bool((session_state.get_window_prefs("mux_detection") if session_state else {}).get("advanced", False)))
        self.advanced.setVisible(self.advanced_toggle.isChecked())
        apply_row = QHBoxLayout()
        self.apply_button = QPushButton(get_text("mux_apply"))
        self.candidate_button = QPushButton(get_text("mux_candidate"))
        self.apply_button.setEnabled(False)
        self.candidate_button.setEnabled(False)
        apply_row.addWidget(self.apply_button)
        apply_row.addWidget(self.candidate_button)
        layout.addWidget(self.detect_button)
        layout.addWidget(self.summary)
        layout.addWidget(self.only_mux)
        layout.addWidget(self.empty_state)
        layout.addWidget(self.results)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced)
        layout.addLayout(apply_row)
        self._progress = None
        self._sensitivity_timer = QTimer(self)
        self._sensitivity_timer.setSingleShot(True)
        self._sensitivity_timer.setInterval(350)
        self.detect_button.clicked.connect(self._detect)
        self.advanced_toggle.toggled.connect(self._set_advanced)
        self.sensitivity.setValue(50)
        self._sensitivity_changed(50)
        self.sensitivity.valueChanged.connect(self._sensitivity_changed)
        self._sensitivity_timer.timeout.connect(lambda: self._vm.start_analysis(options={"sensitivity": self.sensitivity.value()}))
        self.results.currentCellChanged.connect(self._select_row)
        self.apply_button.clicked.connect(self._apply)
        self._vm.results_changed.connect(self._set_results)
        self._vm.analysis_started.connect(self._start_progress)
        self._vm.progress_changed.connect(self._update_progress)
        self._vm.analysis_finished.connect(self._end_progress)
        self._vm.analysis_failed.connect(self._error)
        self._vm.configuration_apply_blocked.connect(self._apply_blocked)
        self.candidate_button.clicked.connect(self._open_candidate)
        self._has_detected = False
        self._vm.results_changed.connect(self._on_results_changed)
        self._refresh_theme_tokens()
        self._set_results(self._vm.results)

    def _set_advanced(self, enabled):
        self.advanced.setVisible(enabled)
        if self._session_state is not None:
            prefs = self._session_state.get_window_prefs("mux_detection")
            prefs["advanced"] = bool(enabled)
            self._session_state.set_window_prefs("mux_detection", prefs)

    def _detect(self):
        self._vm.start_analysis(options={"sensitivity": self.sensitivity.value()})

    def _sensitivity_changed(self, value):
        sensitivity = int(value) / 100
        gain = MUX_SENSITIVITY_MIN_GAIN_LOW + sensitivity * (MUX_SENSITIVITY_MIN_GAIN_HIGH - MUX_SENSITIVITY_MIN_GAIN_LOW)
        max_values = int(round(MUX_SENSITIVITY_MAX_VALUES_LOW + sensitivity * (
            MUX_SENSITIVITY_MAX_VALUES_HIGH - MUX_SENSITIVITY_MAX_VALUES_LOW
        )))
        self.sensitivity_value.setText(get_text("mux_sensitivity_values").format(
            gain=gain,
            max_values=max_values,
        ))
        if self._vm.results:
            self._sensitivity_timer.start()

    def _start_progress(self):
        self._progress = EtaProgressDialog(get_text("mux_detecting"), get_text("cancel"), self)
        self._progress.canceled.connect(self._vm.cancel_analysis)
        self._progress.start()

    def _update_progress(self, done, total):
        if self._progress:
            self._progress.report_progress(done, total)

    def _end_progress(self):
        if self._progress:
            self._progress.close()
            self._progress = None

    def _on_results_changed(self, results):
        self._has_detected = True
        self._set_results(results)

    def _set_results(self, results):
        current_item = self.results.item(self.results.currentRow(), 0)
        current_data = current_item.data(Qt.ItemDataRole.UserRole) if current_item else None
        current_id = current_data.get("can_id") if current_data else None
        confidence_order = {"high": 0, "medium": 1, "low": 2, None: 3}
        ordered = sorted(
            results,
            key=lambda result: (
                not bool(result.get("has_mux")),
                confidence_order.get(result.get("confidence"), 3),
                str(result.get("can_id", "")),
            ),
        )
        muxed_count = sum(bool(result.get("has_mux")) for result in ordered)
        self.summary.setText(get_text("mux_summary").format(muxed=muxed_count, total=len(ordered)))
        visible = [result for result in ordered if not self.only_mux.isChecked() or result.get("has_mux")]
        self.results.setRowCount(len(visible))
        for row, result in enumerate(visible):
            selector = tuple(result.get("selector", ()))
            selector_label = get_text("mux_selector_byte").format(index=selector[0]) if len(selector) == 1 else (
                get_text("mux_selector_byte_range").format(start=selector[0], end=selector[-1])
                if selector else get_text("mux_none")
            )
            id_item = QTableWidgetItem(str(result.get("can_id", "")))
            id_item.setData(Qt.ItemDataRole.UserRole, result)
            self.results.setItem(row, 0, id_item)
            self.results.setItem(row, 1, QTableWidgetItem(selector_label))
            self.results.setItem(row, 2, QTableWidgetItem(get_text("mux_values_count").format(
                count=len(result.get("values", []))
            )))
            confidence = result.get("confidence") if result.get("has_mux") else None
            if confidence:
                badge = QLabel(get_text(f"mux_confidence_{confidence}"))
                badge.setObjectName("mux_confidence_badge")
                badge.setProperty("confidence", confidence)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.results.setCellWidget(row, 3, badge)
            else:
                self.results.setItem(row, 3, QTableWidgetItem("—"))
            applied = self._is_applied(result)
            status = QLabel(get_text("mux_applied")) if applied else QLabel("")
            status.setObjectName("mux_applied_badge")
            status.setProperty("applied", applied)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results.setCellWidget(row, 4, status)
        self.empty_state.setText(
            get_text("mux_result_empty_none") if self._has_detected else get_text("mux_result_empty_intro")
        )
        self.empty_state.setVisible(not visible)
        self.results.setVisible(bool(visible))
        target_row = next((row for row, result in enumerate(visible) if result.get("can_id") == current_id), None)
        if target_row is None and visible:
            target_row = next((row for row, result in enumerate(visible) if result.get("has_mux")), 0)
        if target_row is not None:
            self.results.setCurrentCell(target_row, 0)
            self.results.selectRow(target_row)
            self._select_row(target_row, 0, -1, -1)
        else:
            self._select_row(-1, -1, -1, -1)
        self._refresh_theme_tokens()

    def _select_row(self, row, _column, _previous_row, _previous_column):
        self.values.setRowCount(0)
        while self.selector_chips_layout.count():
            widget = self.selector_chips_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        if row < 0 or row >= self.results.rowCount():
            self.discard_reasons.clear()
            self.apply_button.setEnabled(False)
            self.candidate_button.setEnabled(False)
            return
        result = self.results.item(row, 0).data(Qt.ItemDataRole.UserRole)
        can_id = str(result["can_id"])
        selected = tuple(result.get("selector", ()))
        has_mux = bool(result.get("has_mux"))
        self.apply_button.setEnabled(has_mux)
        self.candidate_button.setEnabled(has_mux and self._candidate_manager is not None)
        if not has_mux:
            self.discard_reasons.setText(get_text("mux_discard_for_id").format(
                can_id=can_id,
                reasons=get_text("mux_discard_summary").format(
                    counter=int(result.get("discarded", {}).get("counter", 0)),
                    dlc=int(result.get("discarded", {}).get("dlc", 0))
                    + int(bool(result.get("variable_dlc"))),
                    hierarchy=int(result.get("discarded", {}).get("hierarchy", 0))
                    + int(bool(result.get("hierarchy_suspected"))),
                    threshold=int(result.get("discarded", {}).get("filters", 0)),
                ),
            ))
            return
        for byte in range(8):
            chip = QCheckBox(f"B{byte}")
            chip.setChecked(byte in selected)
            low, high = (min(selected), max(selected)) if selected else (byte, byte)
            may_add = len(selected) < 4 and (byte == low - 1 or byte == high + 1)
            may_remove = len(selected) > 1 and byte in (low, high)
            chip.setEnabled((byte in selected and may_remove) or (byte not in selected and may_add))
            chip.toggled.connect(lambda checked, index=byte: self._change_selector(can_id, selected, index, checked))
            self.selector_chips_layout.addWidget(chip)
        discarded = result.get("discarded", {})
        self.discard_reasons.setText(get_text("mux_discard_for_id").format(
            can_id=can_id,
            reasons=get_text("mux_discard_summary").format(
                counter=int(discarded.get("counter", 0)),
                dlc=int(discarded.get("dlc", 0)) + int(bool(result.get("variable_dlc"))),
                hierarchy=int(discarded.get("hierarchy", 0)) + int(bool(result.get("hierarchy_suspected"))),
                threshold=int(discarded.get("filters", 0)),
            ),
        ))
        for row, value in enumerate(result.get("values", [])):
            self.values.insertRow(row)
            include = QCheckBox()
            include.setChecked(value.get("value") not in result.get("excluded_values", []))
            include.setToolTip(get_text("mux_include_value"))
            include.toggled.connect(lambda checked, value_key=value.get("value"), selected_result=result:
                                    self._set_value_included(selected_result, value_key, checked))
            self.values.setCellWidget(row, 0, include)
            for col, key in enumerate(("value", "n", "period_median", "cv", "dlc"), start=1):
                item_value = value.get(key)
                if key == "period_median" and item_value is not None:
                    item_value = float(item_value) * 1000.0
                rendered = (
                    f"{item_value:.3f}" if isinstance(item_value, float)
                    else "-" if item_value is None else str(item_value)
                )
                self.values.setItem(row, col, QTableWidgetItem(rendered))

    def _is_applied(self, result):
        return bool(
            result.get("has_mux")
            and hasattr(self._vm, "is_result_applied")
            and self._vm.is_result_applied(str(result["can_id"]), tuple(result.get("selector", ())))
        )

    def _refresh_theme_tokens(self):
        theme = get_active_theme()
        for row in range(self.results.rowCount()):
            confidence = self.results.cellWidget(row, 3)
            if confidence is not None:
                level = confidence.property("confidence")
                color = theme.success if level == "high" else theme.warn if level == "medium" else theme.error
                confidence.setStyleSheet(
                    f"color: {color}; background: {theme.surface_alt}; border: 1px solid {color}; "
                    "border-radius: 8px; padding: 2px 8px; font-weight: 600;"
                )
            applied = self.results.cellWidget(row, 4)
            if applied is not None and applied.property("applied"):
                applied.setStyleSheet(
                    f"color: {theme.success}; background: {theme.surface_alt}; border: 1px solid {theme.success}; "
                    "border-radius: 8px; padding: 2px 8px; font-weight: 600;"
                )

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.PaletteChange and hasattr(self, "results"):
            self._refresh_theme_tokens()

    def _change_selector(self, can_id, selected, byte, checked):
        updated = set(selected)
        if checked:
            updated.add(byte)
        else:
            updated.discard(byte)
        self._vm.recalculate_selector(can_id, tuple(sorted(updated)))

    @staticmethod
    def _set_value_included(result, value, included):
        excluded = set(result.get("excluded_values", []))
        if included:
            excluded.discard(value)
        else:
            excluded.add(value)
        result["excluded_values"] = sorted(excluded)

    def _apply(self):
        row = self.results.currentRow()
        item = self.results.item(row, 0) if row >= 0 else None
        if item:
            result = item.data(Qt.ItemDataRole.UserRole)
            conflict = self._vm.apply_result(result["can_id"])
            self._set_results(self._vm.results)
            if conflict:
                QMessageBox.information(self, get_text("mux_detection_title"), get_text("mux_conflict"))

    def _apply_blocked(self, can_id):
        QMessageBox.information(self, get_text("mux_detection_title"), get_text("mux_excluded_apply_blocked"))

    def _open_candidate(self):
        row = self.results.currentRow()
        item = self.results.item(row, 0) if row >= 0 else None
        if item and self._candidate_manager:
            result = item.data(Qt.ItemDataRole.UserRole)
            if result.get("excluded_values"):
                self._apply_blocked(result["can_id"])
                return
            if result.get("has_mux"):
                conflict = self._vm.apply_result(result["can_id"])
                if conflict:
                    QMessageBox.information(self, get_text("mux_detection_title"), get_text("mux_conflict"))
            self._candidate_manager.open_window_for_can_id(result["can_id"], source="Mux Detection")

    def _error(self, text):
        QMessageBox.warning(self, get_text("mux_detection_title"), text)

    def closeEvent(self, event):
        self._sensitivity_timer.stop()
        self._end_progress()
        super().closeEvent(event)
