from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class HmiVideoMetadata:
    path: str
    frame_count: int
    fps: float
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        if self.fps <= 0:
            return 0.0
        return float(self.frame_count) / float(self.fps)


@dataclass(frozen=True)
class HmiRoi:
    roi_id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    unit: str = ""
    color: str = "#00d1ff"
    reader_type: str = "numeric_ocr"
    preprocess_profile: str = "auto"
    enabled: bool = True
    tracking_enabled: bool = True
    search_radius: int = 24
    anchor_x: int | None = None
    anchor_y: int | None = None
    anchor_width: int | None = None
    anchor_height: int | None = None

    @property
    def has_anchor(self) -> bool:
        return (
            self.anchor_x is not None
            and self.anchor_y is not None
            and self.anchor_width is not None
            and self.anchor_height is not None
            and self.anchor_width > 0
            and self.anchor_height > 0
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HmiFrameView:
    frame_index: int
    timestamp_seconds: float
    width: int
    height: int
    image_bytes: bytes
    image_format: str = "rgb888"
    bytes_per_line: int = 0


@dataclass(frozen=True)
class HmiOcrReading:
    value: float | None
    raw_text: str
    confidence: float
    method: str
    debug_steps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HmiExtractionRecord:
    timestamp: float
    frame: int
    variable: str
    value: float | None
    unit: str
    confidence: float
    roi_id: str
    method: str
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
