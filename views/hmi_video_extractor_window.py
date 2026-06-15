from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)
import pyqtgraph as pg

from config.app_config import get_text
from models.hmi_video_models import HmiFrameView, HmiRoi, HmiVideoMetadata
from viewmodels.hmi_video_extractor_viewmodel import HmiVideoExtractorViewModel
from views.widgets.hmi_frame_editor_widget import HmiFrameEditorWidget


class HmiVideoExtractorWindow(QMainWindow):
    def __init__(self, vm: HmiVideoExtractorViewModel, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("hmi_video_title"))
        self.resize(1600, 950)
        self._vm = vm
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        self.btn_load_video = QPushButton(get_text("hmi_video_load"))
        self.btn_draw_roi = QPushButton(get_text("hmi_video_draw_roi"))
        self.btn_draw_roi.setCheckable(True)
        self.btn_draw_anchor = QPushButton(get_text("hmi_video_draw_anchor"))
        self.btn_draw_anchor.setCheckable(True)
        self.btn_delete_roi = QPushButton(get_text("hmi_video_delete_roi"))

        self.preview = HmiFrameEditorWidget(self)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setEnabled(False)
        self.btn_prev = QPushButton("<", self)
        self.btn_next = QPushButton(">", self)
        self.lbl_frame_info = QLabel("-", self)

        self.logs = QTextEdit(self)
        self.logs.setReadOnly(True)
        self.logs.setMaximumHeight(200)

        self.roi_table = QTableWidget(0, 4, self)
        self.roi_table.setHorizontalHeaderLabels(["Name", "Unit", "Profile", "Enabled"])
        self.roi_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.roi_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.roi_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.edit_name = QLineEdit(self)
        self.edit_unit = QLineEdit(self)
        self.combo_profile = QComboBox(self)
        self.combo_profile.addItems(["fast_numeric", "auto", "gray", "binary", "binary_inv", "adaptive"])
        self.chk_enabled = QCheckBox(get_text("hmi_roi_enabled"), self)
        self.lbl_preview_value = QLabel("-", self)
        self.lbl_preview_confidence = QLabel("-", self)
        self.lbl_preview_method = QLabel("-", self)

        roi_form = QFormLayout()
        roi_form.addRow(get_text("hmi_roi_name"), self.edit_name)
        roi_form.addRow(get_text("hmi_roi_unit"), self.edit_unit)
        roi_form.addRow(get_text("hmi_roi_profile"), self.combo_profile)
        roi_form.addRow("", self.chk_enabled)
        roi_form.addRow("Current value", self.lbl_preview_value)
        roi_form.addRow("Confidence", self.lbl_preview_confidence)
        roi_form.addRow("Method", self.lbl_preview_method)

        self.roi_box = QGroupBox(get_text("hmi_video_rois"), self)
        roi_box_layout = QVBoxLayout(self.roi_box)
        roi_box_layout.addWidget(self.roi_table, 1)
        roi_box_layout.addLayout(roi_form)

        self.spin_start = QSpinBox(self)
        self.spin_end = QSpinBox(self)
        self.spin_step = QSpinBox(self)
        self.spin_step.setMinimum(1)
        self.spin_step.setValue(1)
        self.chk_temporal_penalty = QCheckBox(get_text("hmi_process_temporal_penalty"), self)
        self.chk_temporal_penalty.setChecked(False)
        self.btn_process = QPushButton(get_text("hmi_video_process"), self)
        self.btn_cancel = QPushButton(get_text("cancel"), self)
        self.btn_export_csv = QPushButton("CSV", self)
        self.btn_export_json = QPushButton("JSON", self)
        self.progress = QProgressBar(self)

        processing_form = QFormLayout()
        processing_form.addRow(get_text("hmi_process_start"), self.spin_start)
        processing_form.addRow(get_text("hmi_process_end"), self.spin_end)
        processing_form.addRow(get_text("hmi_process_step"), self.spin_step)
        processing_form.addRow("", self.chk_temporal_penalty)

        processing_buttons = QHBoxLayout()
        processing_buttons.addWidget(self.btn_process)
        processing_buttons.addWidget(self.btn_cancel)
        processing_buttons.addWidget(self.btn_export_csv)
        processing_buttons.addWidget(self.btn_export_json)

        self.processing_box = QGroupBox(get_text("hmi_video_processing"), self)
        processing_box_layout = QVBoxLayout(self.processing_box)
        processing_box_layout.addLayout(processing_form)
        processing_box_layout.addLayout(processing_buttons)
        processing_box_layout.addWidget(self.progress)

        self.results_table = QTableWidget(0, 8, self)
        self.results_table.setHorizontalHeaderLabels(
            ["Timestamp", "Frame", "Variable", "Value", "Unit", "Confidence", "Method", "Raw"]
        )
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.plot_min_confidence_label = QLabel(get_text("hmi_min_confidence"), self)
        self.spin_plot_min_confidence = QDoubleSpinBox(self)
        self.spin_plot_min_confidence.setRange(0.0, 1.0)
        self.spin_plot_min_confidence.setSingleStep(0.1)
        self.spin_plot_min_confidence.setValue(0.5)

        self.plot_variables = QListWidget(self)
        self.plot_variables.setSelectionMode(QAbstractItemView.MultiSelection)
        self.plot = pg.PlotWidget(self)
        self.plot.setLabel("left", "Value")
        self.plot.setLabel("bottom", "Time (s)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)

        # Build tabs
        self._build_tabs()
        self.setCentralWidget(self.tabs)

    def _build_tabs(self) -> None:
        # Video tab
        video_controls = QHBoxLayout()
        video_controls.addWidget(self.btn_load_video)
        video_controls.addWidget(self.btn_draw_roi)
        video_controls.addWidget(self.btn_draw_anchor)
        video_controls.addWidget(self.btn_delete_roi)
        video_controls.addStretch(1)
        video_controls.addWidget(self.btn_prev)
        video_controls.addWidget(self.btn_next)
        video_controls.addWidget(self.lbl_frame_info)

        video_left = QWidget(self)
        video_left_layout = QVBoxLayout(video_left)
        video_left_layout.addLayout(video_controls)
        video_left_layout.addWidget(self.preview, 1)
        video_left_layout.addWidget(self.slider)

        video_right = QWidget(self)
        video_right_layout = QVBoxLayout(video_right)
        video_right_layout.addWidget(self.roi_box, 2)
        video_right_layout.addWidget(self.processing_box)
        video_right_layout.addWidget(self.logs, 1)

        video_splitter = QSplitter(Qt.Horizontal, self)
        video_splitter.addWidget(video_left)
        video_splitter.addWidget(video_right)
        video_splitter.setStretchFactor(0, 3)
        video_splitter.setStretchFactor(1, 2)

        video_tab = QWidget(self)
        video_layout = QVBoxLayout(video_tab)
        video_layout.addWidget(video_splitter, 1)

        # Results tab
        results_tab = QWidget(self)
        results_layout = QVBoxLayout(results_tab)
        results_layout.addWidget(self.results_table)

        # Plots tab
        plots_tab = QWidget(self)
        plots_layout = QVBoxLayout(plots_tab)
        plot_filter_layout = QHBoxLayout()
        plot_filter_layout.addWidget(self.plot_min_confidence_label)
        plot_filter_layout.addWidget(self.spin_plot_min_confidence)
        plot_filter_layout.addStretch(1)
        plot_layout = QHBoxLayout()
        plot_layout.addWidget(self.plot_variables, 0)
        plot_layout.addWidget(self.plot, 1)
        plots_layout.addLayout(plot_filter_layout)
        plots_layout.addLayout(plot_layout, 1)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(video_tab, "Video")
        self.tabs.addTab(results_tab, get_text("hmi_video_results"))
        self.tabs.addTab(plots_tab, get_text("hmi_video_plots"))

    def _wire(self) -> None:
        self.btn_load_video.clicked.connect(self._pick_video)
        self.btn_draw_roi.toggled.connect(self._toggle_draw_roi)
        self.btn_draw_anchor.toggled.connect(self._toggle_draw_anchor)
        self.btn_delete_roi.clicked.connect(self._vm.remove_selected_roi)
        self.btn_prev.clicked.connect(lambda: self._vm.step_frame(-1))
        self.btn_next.clicked.connect(lambda: self._vm.step_frame(1))
        self.slider.valueChanged.connect(self._vm.set_frame)
        self.preview.roi_drawn.connect(self._on_roi_drawn)
        self.preview.anchor_drawn.connect(self._on_anchor_drawn)
        self.roi_table.currentCellChanged.connect(self._on_roi_selected)
        self.edit_name.editingFinished.connect(self._apply_roi_form)
        self.edit_unit.editingFinished.connect(self._apply_roi_form)
        self.combo_profile.currentTextChanged.connect(lambda _text: self._apply_roi_form())
        self.chk_enabled.toggled.connect(lambda _checked: self._apply_roi_form())
        self.btn_process.clicked.connect(self._start_processing)
        self.btn_cancel.clicked.connect(self._vm.cancel_processing)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_json.clicked.connect(self._export_json)
        self.plot_variables.itemSelectionChanged.connect(self._refresh_plot)
        self.spin_plot_min_confidence.valueChanged.connect(lambda _: self._refresh_plot())

        self._vm.video_loaded.connect(self._on_video_loaded)
        self._vm.frame_changed.connect(self._on_frame_changed)
        self._vm.rois_changed.connect(self._set_rois)
        self._vm.preview_rois_changed.connect(self._set_preview_rois)
        self._vm.selected_roi_changed.connect(self._set_selected_roi)
        self._vm.preview_reading_changed.connect(self._set_preview_reading)
        self._vm.processing_started.connect(self._on_processing_started)
        self._vm.processing_progress.connect(self._on_processing_progress)
        self._vm.processing_partial_results.connect(self._on_processing_partial_results)
        self._vm.processing_finished.connect(self._on_processing_finished)
        self._vm.processing_failed.connect(self._on_processing_failed)
        self._vm.processing_canceled.connect(self._on_processing_canceled)
        self._vm.log_message.connect(self._append_log)

    def _pick_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("hmi_video_load"),
            "",
            get_text("hmi_video_files_filter"),
        )
        if not path:
            return
        try:
            self._vm.load_video(path)
        except Exception as exc:
            QMessageBox.warning(self, get_text("hmi_video_title"), str(exc))

    def _on_video_loaded(self, metadata: HmiVideoMetadata) -> None:
        max_frame = max(0, metadata.frame_count - 1)
        self.slider.setEnabled(True)
        self.slider.setRange(0, max_frame)
        self.spin_start.setRange(0, max_frame)
        self.spin_end.setRange(0, max_frame)
        self.spin_end.setValue(max_frame)
        self.progress.setValue(0)

    def _on_frame_changed(self, frame: HmiFrameView) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(frame.frame_index)
        self.slider.blockSignals(False)
        self.preview.set_frame(frame)
        metadata = self._vm.metadata
        total = metadata.frame_count if metadata is not None else 0
        fps = metadata.fps if metadata is not None else 0.0
        self.lbl_frame_info.setText(
            f"Frame {frame.frame_index + 1}/{total} | TS {frame.timestamp_seconds:.3f}s | FPS {fps:.2f}"
        )

    def _on_roi_drawn(self, x: int, y: int, width: int, height: int) -> None:
        self._vm.add_roi(x, y, width, height)
        self.btn_draw_roi.setChecked(False)

    def _on_anchor_drawn(self, x: int, y: int, width: int, height: int) -> None:
        self._vm.set_selected_anchor(x, y, width, height)
        self.btn_draw_anchor.setChecked(False)

    def _set_rois(self, rois: list[HmiRoi]) -> None:
        self.roi_table.blockSignals(True)
        self.roi_table.setRowCount(0)
        for roi in rois:
            row = self.roi_table.rowCount()
            self.roi_table.insertRow(row)
            self.roi_table.setItem(row, 0, self._make_item(roi.name, roi.roi_id))
            self.roi_table.setItem(row, 1, self._make_item(roi.unit, roi.roi_id))
            self.roi_table.setItem(row, 2, self._make_item(roi.preprocess_profile, roi.roi_id))
            self.roi_table.setItem(row, 3, self._make_item("Yes" if roi.enabled else "No", roi.roi_id))
        self.roi_table.blockSignals(False)

    def _set_preview_rois(self, rois: list[HmiRoi]) -> None:
        self.preview.set_rois(rois, self._vm.selected_roi().roi_id if self._vm.selected_roi() else None)

    def _set_selected_roi(self, roi_id: str) -> None:
        selected = self._vm.selected_roi()
        self.preview.set_rois(self._vm.preview_rois, roi_id or None)
        if selected is None:
            self.edit_name.setText("")
            self.edit_unit.setText("")
            self.combo_profile.setCurrentText("auto")
            self.chk_enabled.setChecked(False)
            self.lbl_preview_value.setText("-")
            self.lbl_preview_confidence.setText("-")
            self.lbl_preview_method.setText("-")
            return
        self.edit_name.setText(selected.name)
        self.edit_unit.setText(selected.unit)
        self.combo_profile.setCurrentText(selected.preprocess_profile)
        self.chk_enabled.setChecked(selected.enabled)
        for row in range(self.roi_table.rowCount()):
            item = self.roi_table.item(row, 0)
            if item and item.data(Qt.UserRole) == roi_id:
                self.roi_table.setCurrentCell(row, 0)
                break

    def _set_preview_reading(self, payload: dict) -> None:
        if not payload:
            self.lbl_preview_value.setText("-")
            self.lbl_preview_confidence.setText("-")
            self.lbl_preview_method.setText("-")
            return
        if payload.get("error"):
            self.lbl_preview_value.setText("Error")
            self.lbl_preview_confidence.setText("-")
            self.lbl_preview_method.setText(str(payload.get("error")))
            return
        value = payload.get("value")
        self.lbl_preview_value.setText("" if value is None else str(value))
        self.lbl_preview_confidence.setText(f"{float(payload.get('confidence', 0.0)):.3f}")
        self.lbl_preview_method.setText(str(payload.get("method", "")))

    def _on_roi_selected(self, current_row: int, _current_col: int, _prev_row: int, _prev_col: int) -> None:
        if current_row < 0:
            self._vm.set_selected_roi(None)
            return
        item = self.roi_table.item(current_row, 0)
        self._vm.set_selected_roi(item.data(Qt.UserRole) if item else None)

    def _apply_roi_form(self) -> None:
        roi = self._vm.selected_roi()
        if roi is None:
            return
        self._vm.update_roi(
            roi.roi_id,
            name=self.edit_name.text(),
            unit=self.edit_unit.text(),
            preprocess_profile=self.combo_profile.currentText(),
            enabled=self.chk_enabled.isChecked(),
        )

    def _start_processing(self) -> None:
        try:
            self._vm.process_video(
                start_frame=self.spin_start.value(),
                end_frame=self.spin_end.value(),
                frame_step=self.spin_step.value(),
                use_temporal_penalty=self.chk_temporal_penalty.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, get_text("hmi_video_title"), str(exc))

    def _on_processing_started(self) -> None:
        self.progress.setValue(0)
        self.btn_process.setEnabled(False)
        self.results_table.setRowCount(0)
        self.plot.clear()
        self.plot_variables.clear()

    def _on_processing_progress(self, value: int, message: str) -> None:
        self.progress.setValue(value)
        self._append_log(message)

    def _on_processing_partial_results(self, results: list) -> None:
        self._append_results(results)
        self._populate_plot_variables()
        self._refresh_plot()

    def _on_processing_finished(self, _results) -> None:
        self.btn_process.setEnabled(True)
        self.progress.setValue(100)
        self._populate_results()
        self._populate_plot_variables()
        self._refresh_plot()

    def _on_processing_failed(self, message: str) -> None:
        self.btn_process.setEnabled(True)
        QMessageBox.warning(self, get_text("hmi_video_title"), message)

    def _on_processing_canceled(self) -> None:
        self.btn_process.setEnabled(True)
        self._append_log("Processing canceled")

    def _populate_results(self) -> None:
        rows = self._vm.results_as_rows()
        self.results_table.setRowCount(0)
        for row_data in rows:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            values = [
                f"{float(row_data.get('timestamp', 0.0)):.6f}",
                str(row_data.get("frame", "")),
                str(row_data.get("variable", "")),
                "" if row_data.get("value") is None else str(row_data.get("value")),
                str(row_data.get("unit", "")),
                f"{float(row_data.get('confidence', 0.0)):.3f}",
                str(row_data.get("method", "")),
                str(row_data.get("raw_text", "")),
            ]
            for col, value in enumerate(values):
                self.results_table.setItem(row, col, QTableWidgetItem(value))

    def _populate_plot_variables(self) -> None:
        selected = {item.text() for item in self.plot_variables.selectedItems()}
        self.plot_variables.clear()
        for series in self._vm.plot_series(self.spin_plot_min_confidence.value()):
            item = QListWidgetItem(series["label"])
            self.plot_variables.addItem(item)
            if not selected or series["label"] in selected:
                item.setSelected(True)

    def _append_results(self, results: list) -> None:
        for record in results:
            row_data = record.to_dict() if hasattr(record, "to_dict") else record
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            values = [
                f"{float(row_data.get('timestamp', 0.0)):.6f}",
                str(row_data.get("frame", "")),
                str(row_data.get("variable", "")),
                "" if row_data.get("value") is None else str(row_data.get("value")),
                str(row_data.get("unit", "")),
                f"{float(row_data.get('confidence', 0.0)):.3f}",
                str(row_data.get("method", "")),
                str(row_data.get("raw_text", "")),
            ]
            for col, value in enumerate(values):
                self.results_table.setItem(row, col, QTableWidgetItem(value))

    def _refresh_plot(self) -> None:
        self.plot.clear()
        selected = {item.text() for item in self.plot_variables.selectedItems()}
        min_confidence = self.spin_plot_min_confidence.value()
        for series in self._vm.plot_series(min_confidence=min_confidence):
            if selected and series["label"] not in selected:
                continue
            self.plot.plot(
                series["x"],
                series["y"],
                pen=pg.mkPen(series["color"], width=1.8),
            )

    def _export_csv(self) -> None:
        if not self._vm.results:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV files (*.csv)")
        if path:
            self._vm.export_results_csv(path)

    def _export_json(self) -> None:
        if not self._vm.results:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "", "JSON files (*.json)")
        if path:
            self._vm.export_results_json(path)

    def _append_log(self, message: str) -> None:
        if not message:
            return
        self.logs.append(message)

    def _toggle_draw_roi(self, checked: bool) -> None:
        if checked:
            self.btn_draw_anchor.setChecked(False)
            self.preview.set_draw_mode("roi")
        elif not self.btn_draw_anchor.isChecked():
            self.preview.set_draw_mode("")

    def _toggle_draw_anchor(self, checked: bool) -> None:
        if checked:
            if self._vm.selected_roi() is None:
                self.btn_draw_anchor.setChecked(False)
                QMessageBox.information(self, get_text("hmi_video_title"), get_text("hmi_anchor_select_roi_first"))
                return
            self.btn_draw_roi.setChecked(False)
            self.preview.set_draw_mode("anchor")
        elif not self.btn_draw_roi.isChecked():
            self.preview.set_draw_mode("")

    def closeEvent(self, event) -> None:
        self._vm.shutdown()
        super().closeEvent(event)

    @staticmethod
    def _make_item(text: str, roi_id: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.UserRole, roi_id)
        return item
