from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.hmi_video_models import HmiRoi


@dataclass(frozen=True)
class _AnchorTemplate:
    image: np.ndarray
    inset_x: int
    inset_y: int
    width: int
    height: int
    keypoints: tuple | None = None
    descriptors: np.ndarray | None = None


class HmiRoiTracker:
    def __init__(self):
        self._cv2 = None
        self._trackers: dict[str, object] = {}
        self._templates: dict[str, _AnchorTemplate] = {}
        self._last_rois: dict[str, HmiRoi] = {}
        self._current_frame: np.ndarray | None = None

    def initialize(self, frame_bgr: np.ndarray, rois: list[HmiRoi]) -> None:
        self._trackers = {}
        self._templates = {}
        self._last_rois = {}
        self._current_frame = None
        for roi in rois:
            template = self._build_anchor_template(frame_bgr, roi)
            if template is None:
                self._last_rois[roi.roi_id] = roi
                continue
            self._templates[roi.roi_id] = template
            self._last_rois[roi.roi_id] = self._copy_roi(
                roi,
                anchor_x=int(roi.anchor_x if roi.has_anchor else roi.x - template.inset_x),
                anchor_y=int(roi.anchor_y if roi.has_anchor else roi.y - template.inset_y),
                anchor_width=int(roi.anchor_width if roi.has_anchor else template.image.shape[1]),
                anchor_height=int(roi.anchor_height if roi.has_anchor else template.image.shape[0]),
            )
            tracker = self._create_tracker()
            if tracker is not None:
                anchor_rect = self._anchor_rect(self._last_rois[roi.roi_id], template)
                tracker.init(frame_bgr, anchor_rect)
                self._trackers[roi.roi_id] = tracker

    def begin_frame(self, frame_bgr: np.ndarray) -> None:
        self._current_frame = frame_bgr

    def end_frame(self) -> None:
        self._current_frame = None

    def last_roi(self, roi_id: str) -> HmiRoi | None:
        return self._last_rois.get(roi_id)

    def track(self, frame_bgr: np.ndarray, roi: HmiRoi) -> HmiRoi:
        if not roi.tracking_enabled:
            self._last_rois[roi.roi_id] = roi
            return roi

        frame = self._current_frame if self._current_frame is not None else frame_bgr
        previous = self._last_rois.get(roi.roi_id, roi)
        template = self._templates.get(roi.roi_id)
        if template is None:
            template = self._build_anchor_template(frame, previous)
            if template is None:
                self._last_rois[roi.roi_id] = previous
                return previous
            self._templates[roi.roi_id] = template

        tracked = self._track_with_features(frame, previous, template) if previous.has_anchor else None
        if tracked is None:
            tracked = self._track_with_tracker(frame, previous, template)
        if tracked is None:
            tracked = self._track_with_template(frame, previous, template)
        if tracked is None:
            tracked = previous

        self._last_rois[roi.roi_id] = tracked
        self._refresh_tracker(frame, tracked, template)
        return tracked

    def _track_with_features(self, frame_bgr: np.ndarray, roi: HmiRoi, template: _AnchorTemplate) -> HmiRoi | None:
        cv2 = self._get_cv2()
        if template.descriptors is None or template.keypoints is None or len(template.keypoints) < 6:
            return None

        search = self._search_window(frame_bgr, roi, self._search_radius(roi, template), template)
        if search is None:
            return None

        gray = cv2.cvtColor(search["image"], cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        orb = cv2.ORB_create(nfeatures=500, fastThreshold=10)
        keypoints, descriptors = orb.detectAndCompute(gray, None)
        if descriptors is None or keypoints is None or len(keypoints) < 6:
            return None

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        matches = matcher.knnMatch(template.descriptors, descriptors, k=2)
        good_matches = []
        for pair in matches:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.72 * n.distance:
                good_matches.append(m)
        if len(good_matches) < 6:
            return None

        src_pts = np.float32([template.keypoints[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([keypoints[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        matrix, inliers = cv2.estimateAffinePartial2D(
            src_pts,
            dst_pts,
            method=cv2.RANSAC,
            ransacReprojThreshold=4.0,
            maxIters=2000,
            confidence=0.98,
        )
        if matrix is None or inliers is None:
            return None
        if int(np.sum(inliers)) < 5:
            return None

        h, w = template.image.shape[:2]
        corners = np.float32([[[0.0, 0.0]], [[w, 0.0]], [[w, h]], [[0.0, h]]])
        transformed = cv2.transform(corners, matrix)
        xs = transformed[:, 0, 0] + float(search["x"])
        ys = transformed[:, 0, 1] + float(search["y"])
        anchor_x = int(round(np.min(xs)))
        anchor_y = int(round(np.min(ys)))
        anchor_w = int(round(np.max(xs) - np.min(xs)))
        anchor_h = int(round(np.max(ys) - np.min(ys)))
        if anchor_w <= 4 or anchor_h <= 4:
            return None

        return self._roi_from_anchor(roi, template, anchor_x, anchor_y, anchor_w, anchor_h, frame_bgr.shape[:2])

    def _track_with_tracker(self, frame_bgr: np.ndarray, roi: HmiRoi, template: _AnchorTemplate) -> HmiRoi | None:
        tracker = self._trackers.get(roi.roi_id)
        if tracker is None:
            return None
        ok, bbox = tracker.update(frame_bgr)
        if not ok or bbox is None:
            return None
        x, y, w, h = bbox
        if w <= 2 or h <= 2:
            return None
        anchor_x = int(round(x))
        anchor_y = int(round(y))
        anchor_w = int(round(w))
        anchor_h = int(round(h))
        return self._roi_from_anchor(roi, template, anchor_x, anchor_y, anchor_w, anchor_h, frame_bgr.shape[:2])

    def _track_with_template(self, frame_bgr: np.ndarray, roi: HmiRoi, template: _AnchorTemplate) -> HmiRoi | None:
        search = self._search_window(frame_bgr, roi, self._search_radius(roi, template), template)
        if search is None:
            return None

        cv2 = self._get_cv2()
        template_edges = self._prepare_match_image(template.image)
        search_edges = self._prepare_match_image(search["image"])
        if (
            search_edges.shape[0] < template_edges.shape[0]
            or search_edges.shape[1] < template_edges.shape[1]
        ):
            return None

        result = cv2.matchTemplate(search_edges, template_edges, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if float(max_val) < 0.50:
            return None

        anchor_x = int(search["x"] + max_loc[0])
        anchor_y = int(search["y"] + max_loc[1])
        return self._roi_from_anchor(
            roi,
            template,
            anchor_x,
            anchor_y,
            template.image.shape[1],
            template.image.shape[0],
            frame_bgr.shape[:2],
        )

    def _refresh_tracker(self, frame_bgr: np.ndarray, roi: HmiRoi, template: _AnchorTemplate) -> None:
        tracker = self._create_tracker()
        if tracker is None:
            return
        anchor_rect = self._anchor_rect(roi, template)
        tracker.init(frame_bgr, anchor_rect)
        self._trackers[roi.roi_id] = tracker

    def _create_tracker(self):
        cv2 = self._get_cv2()
        candidates = [
            getattr(cv2, "TrackerCSRT_create", None),
            getattr(getattr(cv2, "legacy", None), "TrackerCSRT_create", None),
            getattr(cv2, "TrackerKCF_create", None),
            getattr(getattr(cv2, "legacy", None), "TrackerKCF_create", None),
            getattr(cv2, "TrackerMOSSE_create", None),
            getattr(getattr(cv2, "legacy", None), "TrackerMOSSE_create", None),
        ]
        for factory in candidates:
            if callable(factory):
                try:
                    return factory()
                except Exception:
                    continue
        return None

    def _anchor_rect(self, roi: HmiRoi, template: _AnchorTemplate) -> tuple[int, int, int, int]:
        return (
            int(roi.anchor_x if roi.has_anchor else roi.x - template.inset_x),
            int(roi.anchor_y if roi.has_anchor else roi.y - template.inset_y),
            int(roi.anchor_width if roi.has_anchor else template.image.shape[1]),
            int(roi.anchor_height if roi.has_anchor else template.image.shape[0]),
        )

    def _roi_from_anchor(
        self,
        roi: HmiRoi,
        template: _AnchorTemplate,
        anchor_x: int,
        anchor_y: int,
        anchor_width: int,
        anchor_height: int,
        frame_shape: tuple[int, int],
    ) -> HmiRoi:
        frame_h, frame_w = frame_shape
        x = max(0, min(frame_w - 1, int(anchor_x + template.inset_x)))
        y = max(0, min(frame_h - 1, int(anchor_y + template.inset_y)))
        width = max(1, min(frame_w - x, int(template.width)))
        height = max(1, min(frame_h - y, int(template.height)))
        return self._copy_roi(
            roi,
            x=x,
            y=y,
            width=width,
            height=height,
            anchor_x=max(0, min(frame_w - 1, int(anchor_x))),
            anchor_y=max(0, min(frame_h - 1, int(anchor_y))),
            anchor_width=max(1, min(frame_w - anchor_x, int(anchor_width))),
            anchor_height=max(1, min(frame_h - anchor_y, int(anchor_height))),
        )

    def _search_radius(self, roi: HmiRoi, template: _AnchorTemplate) -> int:
        if roi.has_anchor:
            return max(36, int((roi.anchor_width or template.image.shape[1]) * 0.35))
        return max(64, int(template.image.shape[1] * 0.5))

    def _search_window(
        self,
        frame_bgr: np.ndarray,
        roi: HmiRoi,
        radius: int,
        template: _AnchorTemplate,
    ) -> dict | None:
        h, w = frame_bgr.shape[:2]
        anchor_x, anchor_y, anchor_w, anchor_h = self._anchor_rect(roi, template)
        x0 = max(0, int(anchor_x - radius))
        y0 = max(0, int(anchor_y - radius))
        x1 = min(w, int(anchor_x + anchor_w + radius))
        y1 = min(h, int(anchor_y + anchor_h + radius))
        if x1 <= x0 or y1 <= y0:
            return None
        image = frame_bgr[y0:y1, x0:x1]
        if image.size == 0:
            return None
        return {"x": x0, "y": y0, "image": image}

    def _prepare_match_image(self, image_bgr: np.ndarray) -> np.ndarray:
        cv2 = self._get_cv2()
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        gray = cv2.equalizeHist(gray)
        return cv2.Canny(gray, 40, 120)

    def _build_anchor_template(self, frame_bgr: np.ndarray, roi: HmiRoi) -> _AnchorTemplate | None:
        h, w = frame_bgr.shape[:2]
        if roi.has_anchor:
            x0 = max(0, int(roi.anchor_x or 0))
            y0 = max(0, int(roi.anchor_y or 0))
            x1 = min(w, x0 + int(roi.anchor_width or 0))
            y1 = min(h, y0 + int(roi.anchor_height or 0))
        else:
            pad_x = max(24, int(roi.width * 1.5))
            pad_y = max(24, int(roi.height * 1.5))
            x0 = max(0, int(roi.x) - pad_x)
            y0 = max(0, int(roi.y) - pad_y)
            x1 = min(w, int(roi.x + roi.width + pad_x))
            y1 = min(h, int(roi.y + roi.height + pad_y))
        if x1 <= x0 or y1 <= y0:
            return None
        anchor = frame_bgr[y0:y1, x0:x1].copy()
        if anchor.size == 0:
            return None
        cv2 = self._get_cv2()
        gray = cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        orb = cv2.ORB_create(nfeatures=500, fastThreshold=10)
        keypoints, descriptors = orb.detectAndCompute(gray, None)
        return _AnchorTemplate(
            image=anchor,
            inset_x=int(roi.x - x0),
            inset_y=int(roi.y - y0),
            width=int(roi.width),
            height=int(roi.height),
            keypoints=tuple(keypoints) if keypoints is not None else None,
            descriptors=descriptors,
        )

    @staticmethod
    def _copy_roi(roi: HmiRoi, **overrides) -> HmiRoi:
        return HmiRoi(
            roi_id=roi.roi_id,
            name=roi.name,
            x=int(overrides.get("x", roi.x)),
            y=int(overrides.get("y", roi.y)),
            width=int(overrides.get("width", roi.width)),
            height=int(overrides.get("height", roi.height)),
            unit=roi.unit,
            color=roi.color,
            reader_type=roi.reader_type,
            preprocess_profile=roi.preprocess_profile,
            enabled=roi.enabled,
            tracking_enabled=roi.tracking_enabled,
            search_radius=roi.search_radius,
            anchor_x=overrides.get("anchor_x", roi.anchor_x),
            anchor_y=overrides.get("anchor_y", roi.anchor_y),
            anchor_width=overrides.get("anchor_width", roi.anchor_width),
            anchor_height=overrides.get("anchor_height", roi.anchor_height),
        )

    def _get_cv2(self):
        if self._cv2 is None:
            try:
                import cv2
            except Exception as exc:
                raise RuntimeError(f"OpenCV is required for ROI tracking: {exc}") from exc
            self._cv2 = cv2
        return self._cv2
