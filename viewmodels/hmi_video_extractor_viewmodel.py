from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from models.hmi_video_models import HmiExtractionRecord, HmiFrameView, HmiRoi, HmiVideoMetadata
from services.hmi_frame_stabilizer import HmiFrameStabilizer
from services.hmi_numeric_reader import HmiNumericReader
from services.hmi_roi_tracker import HmiRoiTracker
from services.hmi_video_loader import HmiVideoLoader
from services.hmi_video_processor import (
    HmiVideoProcessingWorker,
    build_plot_series,
    export_hmi_results_csv,
    export_hmi_results_json,
)


class HmiVideoExtractorViewModel(QObject):
    video_loaded = QtSignal(object)
    frame_changed = QtSignal(object)
    rois_changed = QtSignal(object)
    preview_rois_changed = QtSignal(object)
    selected_roi_changed = QtSignal(str)
    preview_reading_changed = QtSignal(object)
    processing_started = QtSignal()
    processing_progress = QtSignal(int, str)
    processing_partial_results = QtSignal(object)
    processing_finished = QtSignal(object)
    processing_failed = QtSignal(str)
    processing_canceled = QtSignal()
    log_message = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._loader = HmiVideoLoader()
        self._metadata: HmiVideoMetadata | None = None
        self._current_frame: HmiFrameView | None = None
        self._rois: list[HmiRoi] = []
        self._preview_rois: list[HmiRoi] = []
        self._selected_roi_id: str | None = None
        self._results: list[HmiExtractionRecord] = []
        self._thread: QThread | None = None
        self._worker: HmiVideoProcessingWorker | None = None
        self._preview_tracker = HmiRoiTracker()
        self._preview_stabilizer = HmiFrameStabilizer()
        self._preview_reader = None
        self._preview_frame_index: int | None = None
        self._preview_reference_rois: list[HmiRoi] = []

    @property
    def metadata(self) -> HmiVideoMetadata | None:
        return self._metadata

    @property
    def current_frame(self) -> HmiFrameView | None:
        return self._current_frame

    @property
    def rois(self) -> list[HmiRoi]:
        return list(self._rois)

    @property
    def preview_rois(self) -> list[HmiRoi]:
        return list(self._preview_rois or self._rois)

    @property
    def results(self) -> list[HmiExtractionRecord]:
        return list(self._results)

    def load_video(self, path: str) -> None:
        self._metadata = self._loader.open(path)
        self._current_frame = self._loader.get_frame(0)
        frame_bgr, _ = self._loader.get_frame_bgr(0)
        self._preview_stabilizer.initialize(frame_bgr)
        self._preview_tracker.initialize(frame_bgr, self._rois)
        self._preview_rois = list(self._rois)
        self._preview_reference_rois = list(self._rois)
        self._preview_frame_index = 0
        self._results = []
        self.video_loaded.emit(self._metadata)
        self.frame_changed.emit(self._current_frame)
        self.preview_rois_changed.emit(self.preview_rois)
        self._emit_preview_reading(frame_bgr)
        self.log_message.emit(f"Video loaded: {self._metadata.path}")

    def close_video(self) -> None:
        self._loader.close()
        self._metadata = None
        self._current_frame = None
        self._results = []
        self._rois = []
        self._preview_rois = []
        self._preview_reference_rois = []
        self._selected_roi_id = None
        self.rois_changed.emit(self._rois)
        self.preview_rois_changed.emit(self._preview_rois)
        self.selected_roi_changed.emit("")
        self.preview_reading_changed.emit({})

    def set_frame(self, frame_index: int) -> None:
        if self._metadata is None:
            return
        frame_bgr, _ = self._loader.get_frame_bgr(frame_index)
        self._current_frame = self._loader.get_frame(frame_index)
        sequential_forward = self._preview_frame_index is not None and int(frame_index) == self._preview_frame_index + 1
        if sequential_forward:
            seeds = []
            for roi in self._preview_reference_rois:
                if roi.has_anchor:
                    seeds.append(self._preview_tracker.last_roi(roi.roi_id) or roi)
                else:
                    seeds.append(self._preview_stabilizer.transform_roi(frame_bgr, roi))
        else:
            seeds = [
                roi if roi.has_anchor else self._preview_stabilizer.transform_roi(frame_bgr, roi)
                for roi in self._preview_reference_rois
            ]
        if sequential_forward and seeds:
            self._preview_tracker.begin_frame(frame_bgr)
            self._preview_rois = [self._preview_tracker.track(frame_bgr, roi) for roi in seeds]
            self._preview_tracker.end_frame()
        else:
            self._preview_rois = list(seeds)
            self._preview_tracker.initialize(frame_bgr, self._preview_rois)
        self._preview_frame_index = int(frame_index)
        self.frame_changed.emit(self._current_frame)
        self.preview_rois_changed.emit(self.preview_rois)
        self._emit_preview_reading(frame_bgr)

    def step_frame(self, delta: int) -> None:
        if self._current_frame is None:
            return
        self.set_frame(self._current_frame.frame_index + int(delta))

    def add_roi(self, x: int, y: int, width: int, height: int) -> None:
        roi = HmiRoi(
            roi_id=uuid4().hex[:12],
            name=f"ROI {len(self._rois) + 1}",
            x=int(x),
            y=int(y),
            width=max(1, int(width)),
            height=max(1, int(height)),
        )
        self._rois.append(roi)
        self._preview_rois = list(self._rois)
        self._reinitialize_preview_tracker()
        self._selected_roi_id = roi.roi_id
        self.rois_changed.emit(self.rois)
        self.preview_rois_changed.emit(self.preview_rois)
        self.selected_roi_changed.emit(roi.roi_id)

    def update_roi(
        self,
        roi_id: str,
        *,
        name: str | None = None,
        unit: str | None = None,
        preprocess_profile: str | None = None,
        enabled: bool | None = None,
        rect: tuple[int, int, int, int] | None = None,
        anchor_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        updated: list[HmiRoi] = []
        for roi in self._rois:
            if roi.roi_id != roi_id:
                updated.append(roi)
                continue
            x, y, w, h = rect if rect is not None else (roi.x, roi.y, roi.width, roi.height)
            ax, ay, aw, ah = (
                anchor_rect
                if anchor_rect is not None
                else (
                    roi.anchor_x,
                    roi.anchor_y,
                    roi.anchor_width,
                    roi.anchor_height,
                )
            )
            updated.append(
                HmiRoi(
                    roi_id=roi.roi_id,
                    name=(name if name is not None else roi.name).strip() or roi.name,
                    x=int(x),
                    y=int(y),
                    width=max(1, int(w)),
                    height=max(1, int(h)),
                    unit=(unit if unit is not None else roi.unit).strip(),
                    color=roi.color,
                    reader_type=roi.reader_type,
                    preprocess_profile=(preprocess_profile if preprocess_profile is not None else roi.preprocess_profile),
                    enabled=roi.enabled if enabled is None else bool(enabled),
                    tracking_enabled=roi.tracking_enabled,
                    search_radius=roi.search_radius,
                    anchor_x=None if ax is None else int(ax),
                    anchor_y=None if ay is None else int(ay),
                    anchor_width=None if aw is None else max(1, int(aw)),
                    anchor_height=None if ah is None else max(1, int(ah)),
                )
            )
        self._rois = updated
        self._preview_rois = [next((r for r in updated if r.roi_id == roi.roi_id), roi) for roi in (self._preview_rois or updated)]
        self._reinitialize_preview_tracker()
        self.rois_changed.emit(self.rois)
        self.preview_rois_changed.emit(self.preview_rois)

    def set_selected_anchor(self, x: int, y: int, width: int, height: int) -> None:
        roi = self.selected_roi()
        if roi is None:
            return
        self.update_roi(
            roi.roi_id,
            anchor_rect=(int(x), int(y), max(1, int(width)), max(1, int(height))),
        )

    def remove_selected_roi(self) -> None:
        if not self._selected_roi_id:
            return
        self._rois = [roi for roi in self._rois if roi.roi_id != self._selected_roi_id]
        self._preview_rois = [roi for roi in self._preview_rois if roi.roi_id != self._selected_roi_id]
        self._reinitialize_preview_tracker()
        self._selected_roi_id = self._rois[0].roi_id if self._rois else None
        self.rois_changed.emit(self.rois)
        self.preview_rois_changed.emit(self.preview_rois)
        self.selected_roi_changed.emit(self._selected_roi_id or "")

    def set_selected_roi(self, roi_id: str | None) -> None:
        roi_id = (roi_id or "").strip() or None
        self._selected_roi_id = roi_id
        self.selected_roi_changed.emit(self._selected_roi_id or "")

    def selected_roi(self) -> HmiRoi | None:
        for roi in self._rois:
            if roi.roi_id == self._selected_roi_id:
                return roi
        return None

    def process_video(
        self,
        *,
        start_frame: int,
        end_frame: int,
        frame_step: int,
        use_temporal_penalty: bool = False,
    ) -> None:
        if self.running:
            return
        if self._metadata is None:
            raise RuntimeError("No video loaded")
        if not self._rois:
            raise RuntimeError("Add at least one ROI before processing")

        self._results = []
        self.processing_started.emit()
        self._thread = QThread(self)
        self._worker = HmiVideoProcessingWorker(
            video_path=self._metadata.path,
            rois=self._rois,
            start_frame=start_frame,
            end_frame=end_frame,
            frame_step=frame_step,
            use_temporal_penalty=use_temporal_penalty,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.processing_progress.emit)
        self._worker.frame_processed.connect(self._on_processing_partial_results)
        self._worker.finished.connect(self._on_processing_finished)
        self._worker.failed.connect(self._on_processing_failed)
        self._worker.canceled.connect(self._on_processing_canceled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def cancel_processing(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def export_results_csv(self, path: str) -> None:
        export_hmi_results_csv(path, self._results)
        self.log_message.emit(f"CSV exported: {path}")

    def export_results_json(self, path: str) -> None:
        export_hmi_results_json(path, self._results)
        self.log_message.emit(f"JSON exported: {path}")

    def results_as_rows(self) -> list[dict]:
        return [row.to_dict() for row in self._results]

    def plot_series(self, min_confidence: float = 0.0) -> list[dict]:
        return build_plot_series(self._results, min_confidence)

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel_processing()
            self._thread.quit()
            self._thread.wait(2000)
        self._loader.close()

    def _emit_preview_reading(self, frame_bgr) -> None:
        selected = self.selected_roi()
        if selected is None:
            self.preview_reading_changed.emit({})
            return
        tracked = next((roi for roi in self.preview_rois if roi.roi_id == selected.roi_id), selected)
        try:
            if self._preview_reader is None:
                self._preview_reader = HmiNumericReader()
            reading = self._preview_reader.read(frame_bgr, tracked)
        except Exception as exc:
            self.preview_reading_changed.emit({"error": str(exc)})
            return
        self.preview_reading_changed.emit(
            {
                "value": reading.value,
                "raw_text": reading.raw_text,
                "confidence": reading.confidence,
                "method": reading.method,
                "x": tracked.x,
                "y": tracked.y,
            }
        )

    def _reinitialize_preview_tracker(self) -> None:
        if self._metadata is None or self._current_frame is None:
            return
        try:
            frame_bgr, _ = self._loader.get_frame_bgr(self._current_frame.frame_index)
        except Exception:
            return
        reference_rois = list(self._preview_rois or self._rois)
        self._preview_reference_rois = reference_rois
        self._preview_stabilizer.initialize(frame_bgr)
        self._preview_tracker.initialize(frame_bgr, reference_rois)
        self._preview_rois = list(reference_rois)
        self._preview_frame_index = self._current_frame.frame_index
        self.preview_rois_changed.emit(self.preview_rois)
        self._emit_preview_reading(frame_bgr)

    def _on_processing_partial_results(self, results: list[HmiExtractionRecord]) -> None:
        self._results.extend(results)
        self.processing_partial_results.emit(results)

    def _on_processing_finished(self, results: list[HmiExtractionRecord]) -> None:
        self._results = list(results)
        self.processing_finished.emit(self._results)
        self.log_message.emit(f"Processing finished: {len(self._results)} records")

    def _on_processing_failed(self, message: str) -> None:
        self.processing_failed.emit(message)
        self.log_message.emit(f"Processing failed: {message}")

    def _on_processing_canceled(self) -> None:
        self.processing_canceled.emit()
        self.log_message.emit("Processing canceled")

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
