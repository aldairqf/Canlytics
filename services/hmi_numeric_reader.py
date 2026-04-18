from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.hmi_video_models import HmiOcrReading, HmiRoi
from services.hmi_ocr import BaseOcrEngine, TesseractOcrEngine, parse_numeric_text


@dataclass(frozen=True)
class _Variant:
    name: str
    image: np.ndarray


class HmiNumericReader:
    def __init__(self, ocr_engine: BaseOcrEngine | None = None):
        self._ocr = ocr_engine or TesseractOcrEngine()
        self._cv2 = None

    def read(self, frame_bgr: np.ndarray, roi: HmiRoi) -> HmiOcrReading:
        crop = self._crop(frame_bgr, roi)
        if crop is None:
            return HmiOcrReading(
                value=None,
                raw_text="",
                confidence=0.0,
                method=f"{self._ocr.name}:empty",
                debug_steps=("empty_roi",),
            )

        blur_score = self._estimate_blur(crop)
        if blur_score < 18.0:
            return HmiOcrReading(
                value=None,
                raw_text="",
                confidence=0.0,
                method=f"{self._ocr.name}:blur_reject",
                debug_steps=(f"blur_score:{blur_score:.2f}",),
            )

        variants = self._build_variants(crop, roi.preprocess_profile)
        use_fast = roi.preprocess_profile == "fast_numeric"
        read_func = self._ocr.read_text_fast if use_fast else self._ocr.read_text
        best_value = None
        best_text = ""
        best_selection_score = -1.0
        best_confidence = 0.0
        best_method = self._ocr.name
        debug_steps: list[str] = []
        numeric_candidates: list[tuple[float, float]] = []

        for variant in variants:
            result = read_func(variant.image, whitelist="0123456789.-")
            value = parse_numeric_text(result.text)
            selection_score = float(result.confidence)
            if value is not None:
                selection_score += 0.18 if use_fast else 0.25
                numeric_candidates.append((value, float(result.confidence)))
            debug_steps.append(f"{variant.name}:{result.text or '-'}:{result.confidence:.3f}")
            if selection_score > best_selection_score:
                best_selection_score = selection_score
                best_value = value
                best_text = result.text
                best_confidence = float(result.confidence)
                best_method = f"{result.engine_name}:{variant.name}"

        confidence = max(0.0, min(1.0, best_confidence))
        if len(numeric_candidates) > 1:
            values = [value for value, _ in numeric_candidates]
            avg = sum(values) / len(values)
            span = max(values) - min(values)
            if abs(avg) >= 1e-6:
                disagreement = min(1.0, abs(span) / max(abs(avg), 1.0))
                confidence *= max(0.0, 1.0 - disagreement)

        if blur_score < 50.0:
            confidence *= 0.6
        elif blur_score < 70.0:
            confidence *= 0.75
        elif blur_score < 90.0:
            confidence *= 0.9

        if best_text and any(ch not in "0123456789.-" for ch in best_text):
            confidence *= 0.5

        confidence = max(0.0, min(1.0, confidence))
        return HmiOcrReading(
            value=best_value,
            raw_text=best_text,
            confidence=confidence,
            method=best_method,
            debug_steps=tuple(debug_steps),
        )

    def _crop(self, frame_bgr: np.ndarray, roi: HmiRoi) -> np.ndarray | None:
        h, w = frame_bgr.shape[:2]
        pad_x = max(3, int(roi.width * 0.18))
        pad_y = max(2, int(roi.height * 0.20))
        x0 = max(0, int(roi.x) - pad_x)
        y0 = max(0, int(roi.y) - pad_y)
        x1 = min(w, int(roi.x + max(1, int(roi.width)) + pad_x))
        y1 = min(h, int(roi.y + max(1, int(roi.height)) + pad_y))
        if x1 <= x0 or y1 <= y0:
            return None
        crop = frame_bgr[y0:y1, x0:x1].copy()
        if crop.size == 0:
            return None
        return crop

    def _build_variants(self, crop_bgr: np.ndarray, profile: str) -> list[_Variant]:
        cv2 = self._get_cv2()
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        if profile == "gray":
            return [_Variant("gray", gray)]
        if profile == "fast_numeric":
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return [_Variant("fast_binary", binary)]
        if profile == "binary":
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return [_Variant("binary", binary)]
        if profile == "binary_inv":
            _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            return [_Variant("binary_inv", binary_inv)]
        if profile == "adaptive":
            adaptive = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                5,
            )
            return [_Variant("adaptive", adaptive)]

        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )
        return [
            _Variant("gray", gray),
            _Variant("binary", binary),
            _Variant("binary_inv", binary_inv),
            _Variant("adaptive", adaptive),
        ]

    def _estimate_blur(self, crop: np.ndarray) -> float:
        cv2 = self._get_cv2()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        return float(np.var(lap))

    def _get_cv2(self):
        if self._cv2 is None:
            try:
                import cv2
            except Exception as exc:
                raise RuntimeError(f"OpenCV is required for numeric OCR preprocessing: {exc}") from exc
            self._cv2 = cv2
        return self._cv2
