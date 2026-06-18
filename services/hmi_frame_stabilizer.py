from __future__ import annotations

import numpy as np

from models.hmi_video_models import HmiRoi


class HmiFrameStabilizer:
    def __init__(self, scale: float = 0.35):
        self._cv2 = None
        self._scale = max(0.15, min(1.0, float(scale)))
        self._reference_gray: np.ndarray | None = None
        self._reference_size: tuple[int, int] = (0, 0)
        self._last_warp: np.ndarray = np.eye(2, 3, dtype=np.float32)

    def initialize(self, frame_bgr: np.ndarray) -> None:
        self._reference_gray = self._prepare_gray(frame_bgr)
        self._reference_size = (int(frame_bgr.shape[1]), int(frame_bgr.shape[0]))
        self._last_warp = np.eye(2, 3, dtype=np.float32)

    def transform_roi(self, frame_bgr: np.ndarray, roi: HmiRoi) -> HmiRoi:
        if roi.has_anchor:
            return roi
        if self._reference_gray is None:
            return roi
        warp = self._estimate_warp(frame_bgr)
        x0, y0 = self._transform_point(warp, float(roi.x), float(roi.y))
        x1, y1 = self._transform_point(warp, float(roi.x + roi.width), float(roi.y + roi.height))
        anchor = self._transform_anchor(warp, roi) if roi.has_anchor else (roi.anchor_x, roi.anchor_y, roi.anchor_width, roi.anchor_height)
        frame_h, frame_w = frame_bgr.shape[:2]
        left = max(0, min(frame_w - 1, int(round(min(x0, x1)))))
        top = max(0, min(frame_h - 1, int(round(min(y0, y1)))))
        right = max(left + 1, min(frame_w, int(round(max(x0, x1)))))
        bottom = max(top + 1, min(frame_h, int(round(max(y0, y1)))))
        return HmiRoi(
            roi_id=roi.roi_id,
            name=roi.name,
            x=left,
            y=top,
            width=max(1, right - left),
            height=max(1, bottom - top),
            unit=roi.unit,
            color=roi.color,
            reader_type=roi.reader_type,
            preprocess_profile=roi.preprocess_profile,
            enabled=roi.enabled,
            tracking_enabled=roi.tracking_enabled,
            search_radius=roi.search_radius,
            anchor_x=anchor[0],
            anchor_y=anchor[1],
            anchor_width=anchor[2],
            anchor_height=anchor[3],
        )

    def _transform_anchor(self, warp: np.ndarray, roi: HmiRoi) -> tuple[int | None, int | None, int | None, int | None]:
        if not roi.has_anchor:
            return (roi.anchor_x, roi.anchor_y, roi.anchor_width, roi.anchor_height)
        ax0, ay0 = self._transform_point(warp, float(roi.anchor_x or 0), float(roi.anchor_y or 0))
        ax1, ay1 = self._transform_point(
            warp,
            float((roi.anchor_x or 0) + (roi.anchor_width or 0)),
            float((roi.anchor_y or 0) + (roi.anchor_height or 0)),
        )
        left = int(round(min(ax0, ax1)))
        top = int(round(min(ay0, ay1)))
        right = int(round(max(ax0, ax1)))
        bottom = int(round(max(ay0, ay1)))
        return (left, top, max(1, right - left), max(1, bottom - top))

    def _estimate_warp(self, frame_bgr: np.ndarray) -> np.ndarray:
        current_gray = self._prepare_gray(frame_bgr)
        if self._reference_gray is None:
            return np.eye(2, 3, dtype=np.float32)

        cv2 = self._get_cv2()
        warp = self._last_warp.astype(np.float32).copy()
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            35,
            1e-4,
        )
        try:
            _, warp = cv2.findTransformECC(
                current_gray,
                self._reference_gray,
                warp,
                cv2.MOTION_EUCLIDEAN,
                criteria,
                None,
                3,
            )
        except Exception:
            warp = self._estimate_translation(current_gray)

        warp = warp.astype(np.float32)
        if self._scale != 1.0:
            warp = warp.copy()
            warp[0, 2] /= self._scale
            warp[1, 2] /= self._scale
        self._last_warp = warp
        return warp

    def _estimate_translation(self, current_gray: np.ndarray) -> np.ndarray:
        cv2 = self._get_cv2()
        if self._reference_gray is None:
            return np.eye(2, 3, dtype=np.float32)
        shift, _ = cv2.phaseCorrelate(
            np.float32(self._reference_gray),
            np.float32(current_gray),
        )
        warp = np.eye(2, 3, dtype=np.float32)
        warp[0, 2] = float(shift[0])
        warp[1, 2] = float(shift[1])
        return warp

    def _prepare_gray(self, frame_bgr: np.ndarray) -> np.ndarray:
        cv2 = self._get_cv2()
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self._scale != 1.0:
            gray = cv2.resize(gray, None, fx=self._scale, fy=self._scale, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        gray = cv2.equalizeHist(gray)
        return gray

    @staticmethod
    def _transform_point(warp: np.ndarray, x: float, y: float) -> tuple[float, float]:
        nx = float(warp[0, 0] * x + warp[0, 1] * y + warp[0, 2])
        ny = float(warp[1, 0] * x + warp[1, 1] * y + warp[1, 2])
        return nx, ny

    def _get_cv2(self):
        if self._cv2 is None:
            try:
                import cv2
            except Exception as exc:
                raise RuntimeError(f"OpenCV is required for frame stabilization: {exc}") from exc
            self._cv2 = cv2
        return self._cv2
