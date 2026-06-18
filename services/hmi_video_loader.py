from __future__ import annotations

from pathlib import Path

import numpy as np

from models.hmi_video_models import HmiFrameView, HmiVideoMetadata


class HmiVideoLoader:
    def __init__(self):
        self._cv2 = None
        self._cap = None
        self._metadata: HmiVideoMetadata | None = None

    @property
    def metadata(self) -> HmiVideoMetadata | None:
        return self._metadata

    def open(self, path: str) -> HmiVideoMetadata:
        cv2 = self._get_cv2()
        self.close()

        resolved = str(Path(path).resolve())
        cap = cv2.VideoCapture(resolved)
        if not cap.isOpened():
            raise RuntimeError(f"Unable to open video: {resolved}")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        self._cap = cap
        self._metadata = HmiVideoMetadata(
            path=resolved,
            frame_count=frame_count,
            fps=fps,
            width=width,
            height=height,
        )
        return self._metadata

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._metadata = None

    def get_frame(self, frame_index: int) -> HmiFrameView:
        if self._cap is None or self._metadata is None:
            raise RuntimeError("No video loaded")

        frame_index = max(0, min(int(frame_index), max(0, self._metadata.frame_count - 1)))
        cv2 = self._get_cv2()
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame_bgr = self._cap.read()
        if not ok or frame_bgr is None:
            raise RuntimeError(f"Unable to read frame {frame_index}")

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        fps = self._metadata.fps
        timestamp_seconds = (frame_index / fps) if fps > 0 else 0.0

        return HmiFrameView(
            frame_index=frame_index,
            timestamp_seconds=float(timestamp_seconds),
            width=int(w),
            height=int(h),
            image_bytes=frame_rgb.tobytes(),
            image_format="rgb888",
            bytes_per_line=int(frame_rgb.strides[0]),
        )

    def get_frame_bgr(self, frame_index: int) -> tuple[np.ndarray, float]:
        if self._cap is None or self._metadata is None:
            raise RuntimeError("No video loaded")

        frame_index = max(0, min(int(frame_index), max(0, self._metadata.frame_count - 1)))
        cv2 = self._get_cv2()
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame_bgr = self._cap.read()
        if not ok or frame_bgr is None:
            raise RuntimeError(f"Unable to read frame {frame_index}")
        fps = self._metadata.fps
        timestamp_seconds = (frame_index / fps) if fps > 0 else 0.0
        return frame_bgr, float(timestamp_seconds)

    def iter_frames_bgr(self, start_frame: int, end_frame: int, frame_step: int):
        if self._cap is None or self._metadata is None:
            raise RuntimeError("No video loaded")

        cv2 = self._get_cv2()
        max_index = max(0, self._metadata.frame_count - 1)
        start_frame = max(0, min(int(start_frame), max_index))
        end_frame = max(0, min(int(end_frame), max_index))
        frame_step = max(1, int(frame_step))

        self._cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_index = start_frame

        while frame_index <= end_frame:
            ok, frame_bgr = self._cap.read()
            if not ok or frame_bgr is None:
                break
            fps = self._metadata.fps
            timestamp_seconds = (frame_index / fps) if fps > 0 else 0.0
            yield frame_index, frame_bgr, float(timestamp_seconds)

            skips = frame_step - 1
            skipped = 0
            while skipped < skips and frame_index < end_frame:
                if not self._cap.grab():
                    return
                skipped += 1
                frame_index += 1
            frame_index += 1

    def _get_cv2(self):
        if self._cv2 is None:
            try:
                import cv2
            except Exception as exc:
                raise RuntimeError(f"OpenCV is required for video loading: {exc}") from exc
            self._cv2 = cv2
        return self._cv2
