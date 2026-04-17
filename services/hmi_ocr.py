from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float
    engine_name: str


class BaseOcrEngine:
    name = "base"

    def read_text(self, image: np.ndarray, *, whitelist: str = "") -> OcrResult:
        raise NotImplementedError

    def read_text_fast(self, image: np.ndarray, *, whitelist: str = "") -> OcrResult:
        return self.read_text(image, whitelist=whitelist)


class TesseractOcrEngine(BaseOcrEngine):
    name = "tesseract"

    def __init__(self):
        try:
            import pytesseract
        except Exception as exc:
            raise RuntimeError(f"pytesseract is required for OCR: {exc}") from exc
        self._pytesseract = pytesseract

    def read_text(self, image: np.ndarray, *, whitelist: str = "") -> OcrResult:
        config_parts = ["--psm 7", "--oem 3"]
        if whitelist:
            config_parts.append(f"-c tessedit_char_whitelist={whitelist}")
        config = " ".join(config_parts)

        text = self._pytesseract.image_to_string(image, config=config) or ""
        text = text.strip()

        confidence = 0.0
        try:
            data = self._pytesseract.image_to_data(
                image,
                config=config,
                output_type=self._pytesseract.Output.DICT,
            )
            values = []
            for raw in data.get("conf", []):
                try:
                    conf = float(raw)
                except Exception:
                    continue
                if conf >= 0:
                    values.append(conf)
            if values:
                confidence = max(0.0, min(1.0, (sum(values) / len(values)) / 100.0))
        except Exception:
            confidence = 0.0

        return OcrResult(text=text, confidence=confidence, engine_name=self.name)

    def read_text_fast(self, image: np.ndarray, *, whitelist: str = "") -> OcrResult:
        config_parts = ["--psm 7", "--oem 3"]
        if whitelist:
            config_parts.append(f"-c tessedit_char_whitelist={whitelist}")
        config = " ".join(config_parts)
        text = self._pytesseract.image_to_string(image, config=config) or ""
        text = text.strip()

        confidence = 0.0
        try:
            data = self._pytesseract.image_to_data(
                image,
                config=config,
                output_type=self._pytesseract.Output.DICT,
            )
            values = []
            for raw in data.get("conf", []):
                try:
                    conf = float(raw)
                except Exception:
                    continue
                if conf >= 0:
                    values.append(conf)
            if values:
                confidence = max(0.0, min(1.0, (sum(values) / len(values)) / 100.0))
        except Exception:
            confidence = 0.0

        return OcrResult(text=text, confidence=confidence, engine_name=f"{self.name}_fast")


def parse_numeric_text(text: str) -> float | None:
    cleaned = str(text or "").replace(",", ".").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None
