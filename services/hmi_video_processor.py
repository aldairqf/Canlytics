from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal as QtSignal

from models.hmi_video_models import HmiExtractionRecord, HmiRoi
from services.hmi_frame_stabilizer import HmiFrameStabilizer
from services.hmi_numeric_reader import HmiNumericReader
from services.hmi_roi_tracker import HmiRoiTracker
from services.hmi_video_loader import HmiVideoLoader


class HmiVideoProcessingWorker(QObject):
    progress = QtSignal(int, str)
    frame_processed = QtSignal(object)
    finished = QtSignal(object)
    failed = QtSignal(str)
    canceled = QtSignal()

    def __init__(
        self,
        *,
        video_path: str,
        rois: list[HmiRoi],
        start_frame: int,
        end_frame: int,
        frame_step: int,
        use_temporal_penalty: bool = False,
    ):
        super().__init__()
        self._video_path = video_path
        self._rois = [roi for roi in rois if roi.enabled]
        self._start_frame = max(0, int(start_frame))
        self._end_frame = max(0, int(end_frame))
        self._frame_step = max(1, int(frame_step))
        self._use_temporal_penalty = bool(use_temporal_penalty)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        loader = HmiVideoLoader()
        try:
            metadata = loader.open(self._video_path)
            end_frame = min(self._end_frame, max(0, metadata.frame_count - 1))
            reader = HmiNumericReader()
            tracker = HmiRoiTracker()
            stabilizer = HmiFrameStabilizer()
            reference_rois = list(self._rois)
            recent_values: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=5))
            total = max(1, ((end_frame - self._start_frame) // self._frame_step) + 1)
            results: list[HmiExtractionRecord] = []

            for index, (frame_number, frame_bgr, timestamp_seconds) in enumerate(
                loader.iter_frames_bgr(self._start_frame, end_frame, self._frame_step),
                start=1,
            ):
                if self._cancel_requested:
                    self.canceled.emit()
                    return
                if index == 1:
                    stabilizer.initialize(frame_bgr)
                    tracker.initialize(frame_bgr, self._rois)
                else:
                    tracker.begin_frame(frame_bgr)
                frame_results: list[tuple[HmiRoi, HmiRoi, HmiRoi, object]] = []
                for roi in reference_rois:
                    if roi.has_anchor and index > 1:
                        stabilized_roi = tracker.last_roi(roi.roi_id) or roi
                    elif roi.has_anchor:
                        stabilized_roi = roi
                    else:
                        stabilized_roi = stabilizer.transform_roi(frame_bgr, roi)
                    tracked_roi = tracker.track(frame_bgr, stabilized_roi) if index > 1 else stabilized_roi
                    reading = reader.read(frame_bgr, tracked_roi)
                    frame_results.append((roi, stabilized_roi, tracked_roi, reading))
                if index > 1:
                    tracker.end_frame()
                frame_records: list[HmiExtractionRecord] = []
                for roi, stabilized_roi, tracked_roi, reading in frame_results:
                    confidence = float(reading.confidence)
                    if self._use_temporal_penalty:
                        confidence = self._apply_temporal_confidence_penalty(
                            roi.roi_id,
                            reading.value,
                            reading.confidence,
                            recent_values,
                        )
                    if tracked_roi != stabilized_roi:
                        method = f"{reading.method}:stabilized:tracked"
                    elif stabilized_roi != roi:
                        method = f"{reading.method}:stabilized"
                    else:
                        method = reading.method
                    if self._use_temporal_penalty and confidence < reading.confidence:
                        method = f"{method}:temporal_penalty"
                    record = HmiExtractionRecord(
                        timestamp=timestamp_seconds,
                        frame=frame_number,
                        variable=roi.name,
                        value=reading.value,
                        unit=roi.unit,
                        confidence=confidence,
                        roi_id=roi.roi_id,
                        method=method,
                        raw_text=reading.raw_text,
                    )
                    if reading.value is not None and (not self._use_temporal_penalty or confidence >= 0.45):
                        recent_values[roi.roi_id].append(float(reading.value))
                    results.append(record)
                    frame_records.append(record)
                self.frame_processed.emit(frame_records)
                percent = int((index / total) * 100)
                self.progress.emit(percent, f"Processed frame {frame_number}/{end_frame}")
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        finally:
            loader.close()

        self.finished.emit(results)

    def _apply_temporal_confidence_penalty(
        self,
        roi_id: str,
        value: float | None,
        confidence: float,
        recent_values: dict[str, deque[float]],
    ) -> float:
        if value is None:
            return float(confidence)

        history = list(recent_values.get(roi_id, ()))
        if len(history) < 3:
            return float(confidence)

        ordered = sorted(history)
        baseline = ordered[len(ordered) // 2]
        delta = abs(float(value) - float(baseline))
        allowed_delta = max(6.0, abs(float(baseline)) * 0.18)
        if delta <= allowed_delta:
            return float(confidence)

        if delta >= allowed_delta * 2.5:
            return max(0.0, float(confidence) * 0.08)
        if delta >= allowed_delta * 1.8:
            return max(0.0, float(confidence) * 0.18)
        return max(0.0, float(confidence) * 0.35)


def export_hmi_results_csv(path: str, results: list[HmiExtractionRecord]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", "frame", "variable", "value", "unit", "confidence", "roi_id", "method", "raw_text"]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in results:
            writer.writerow(item.to_dict())


def export_hmi_results_json(path: str, results: list[HmiExtractionRecord]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([item.to_dict() for item in results], indent=2),
        encoding="utf-8",
    )
