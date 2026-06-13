from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union

import numpy as np
import polars as pl

Endianness = Literal["be", "le"]


@dataclass(frozen=True)
class SubframeDiscoveryConfig:
    prefix_lengths: tuple[int, ...] = (1, 2, 3, 4)
    min_support: int = 5
    min_support_ratio: float = 0.01
    max_patterns_per_group: int = 24
    refinement_gain_threshold: float = 0.10
    sample_frames_per_pattern: int = 3
    decode_gain_weight: float = 0.60
    entropy_gain_weight: float = 1.00
    min_recommended_decode_score: float = 0.55
    min_semantic_score: float = 0.50


@dataclass(frozen=True)
class PayloadDecodeConfig:
    enable_int_uint: bool = True
    enable_float32: bool = True
    enable_bitfields: bool = False
    max_decode_candidates: int = 12


@dataclass(frozen=True)
class MuxDetectorConfig:
    discovery: SubframeDiscoveryConfig = field(default_factory=SubframeDiscoveryConfig)
    payload: PayloadDecodeConfig = field(default_factory=PayloadDecodeConfig)


@dataclass(frozen=True)
class SampleFrame:
    timestamp: float
    payload_hex: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": float(self.timestamp),
            "payload_hex": self.payload_hex,
        }


@dataclass(frozen=True)
class DecodeCandidate:
    label: str
    kind: str
    byte_range: tuple[int, int] | None
    bit_range: tuple[int, int] | None
    endian: Endianness | None
    score: float
    support: int
    unique_values: int
    change_rate: float
    min_value: float | None
    max_value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "byte_range": self.byte_range,
            "bit_range": self.bit_range,
            "endian": self.endian,
            "score": float(self.score),
            "support": int(self.support),
            "unique_values": int(self.unique_values),
            "change_rate": float(self.change_rate),
            "min_value": self.min_value,
            "max_value": self.max_value,
        }


@dataclass(frozen=True)
class SubframePattern:
    pattern: bytes
    prefix_len: int
    support: int
    support_ratio: float
    payload_start: int
    remaining_entropy_mean: float
    stability_score: float
    refinement_gain: float
    best_decode_label: str | None
    best_decode_score: float
    best_decode_kind: str | None
    semantic_score: float
    recommended: bool
    recommendation_reason: str
    decode_candidates: tuple[DecodeCandidate, ...]
    sample_frames: tuple[SampleFrame, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": _bytes_label(self.pattern),
            "prefix_len": int(self.prefix_len),
            "support": int(self.support),
            "support_ratio": float(self.support_ratio),
            "payload_start": int(self.payload_start),
            "remaining_entropy_mean": float(self.remaining_entropy_mean),
            "stability_score": float(self.stability_score),
            "refinement_gain": float(self.refinement_gain),
            "best_decode_label": self.best_decode_label,
            "best_decode_score": float(self.best_decode_score),
            "best_decode_kind": self.best_decode_kind,
            "semantic_score": float(self.semantic_score),
            "recommended": bool(self.recommended),
            "recommendation_reason": self.recommendation_reason,
            "decode_candidates": [candidate.to_dict() for candidate in self.decode_candidates],
            "sample_frames": [frame.to_dict() for frame in self.sample_frames],
        }


@dataclass(frozen=True)
class FrameAnalysis:
    can_id: str
    frame_len: int
    total_frames: int
    patterns: tuple[SubframePattern, ...]
    best_pattern: str | None
    best_decode: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_id": self.can_id,
            "frame_len": int(self.frame_len),
            "total_frames": int(self.total_frames),
            "pattern_count": len(self.patterns),
            "best_pattern": self.best_pattern,
            "best_decode": self.best_decode,
            "patterns": [pattern.to_dict() for pattern in self.patterns],
        }


def _bytes_label(token: bytes) -> str:
    return " ".join(f"{value:02X}" for value in token)


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return default if b == 0 else a / b


def _entropy_from_counts(counts: np.ndarray) -> float:
    total = counts.sum()
    if total <= 0:
        return 0.0
    probs = counts[counts > 0].astype(np.float64) / float(total)
    return float(-(probs * np.log2(probs)).sum())


def _to_uint_matrix(df_frame: pl.DataFrame, frame_len: int) -> np.ndarray:
    cols = [f"D{i}" for i in range(frame_len)]
    missing = [name for name in cols if name not in df_frame.columns]
    if missing:
        raise ValueError(f"Faltan columnas de payload: {missing}")
    return np.column_stack([df_frame[col].to_numpy().astype(np.uint8, copy=False) for col in cols])


def _extract_uint_values(data: np.ndarray, start_byte: int, byte_len: int, endian: Endianness) -> np.ndarray:
    block = data[:, start_byte : start_byte + byte_len].astype(np.uint64, copy=False)
    values = np.zeros(block.shape[0], dtype=np.uint64)
    if endian == "be":
        for idx in range(byte_len):
            shift = 8 * (byte_len - 1 - idx)
            values |= block[:, idx] << np.uint64(shift)
    else:
        for idx in range(byte_len):
            shift = 8 * idx
            values |= block[:, idx] << np.uint64(shift)
    return values


def _extract_int_values(data: np.ndarray, start_byte: int, byte_len: int, endian: Endianness) -> np.ndarray:
    unsigned = _extract_uint_values(data, start_byte, byte_len, endian)
    bit_width = byte_len * 8
    sign_bit = np.uint64(1) << np.uint64(bit_width - 1)
    signed = unsigned.astype(np.int64, copy=False)
    negative_mask = (unsigned & sign_bit) != 0
    signed[negative_mask] -= int(np.uint64(1) << np.uint64(bit_width))
    return signed


def _extract_float32_values(data: np.ndarray, start_byte: int, endian: Endianness) -> np.ndarray:
    block = np.ascontiguousarray(data[:, start_byte : start_byte + 4])
    dtype = ">f4" if endian == "be" else "<f4"
    with np.errstate(invalid="ignore", over="ignore"):
        viewed = block.view(dtype).reshape(-1)
        return viewed.astype(np.float64, copy=False)


def _extract_bitfield_values(data: np.ndarray, start_bit: int, bit_len: int) -> np.ndarray:
    frame_len = data.shape[1]
    payload = np.zeros(data.shape[0], dtype=np.uint64)
    for idx in range(frame_len):
        shift = 8 * (frame_len - 1 - idx)
        payload |= data[:, idx].astype(np.uint64) << np.uint64(shift)
    total_bits = frame_len * 8
    shift = total_bits - (start_bit + bit_len)
    if shift < 0:
        return np.zeros(data.shape[0], dtype=np.uint64)
    mask = (np.uint64(1) << np.uint64(bit_len)) - np.uint64(1)
    return (payload >> np.uint64(shift)) & mask


def _mean_remaining_entropy(data: np.ndarray, payload_start: int) -> float:
    if payload_start >= data.shape[1]:
        return 0.0
    entropies: list[float] = []
    for byte_idx in range(payload_start, data.shape[1]):
        counts = np.bincount(data[:, byte_idx].astype(np.uint8, copy=False), minlength=256)
        entropies.append(_entropy_from_counts(counts))
    return float(np.mean(entropies)) if entropies else 0.0


def _weighted_refined_decode_quality(
    data: np.ndarray,
    next_len: int,
    discovery_cfg: SubframeDiscoveryConfig,
    payload_cfg: PayloadDecodeConfig,
) -> tuple[float, float, float]:
    tokens = np.ascontiguousarray(data[:, :next_len]).view(np.dtype((np.void, next_len))).reshape(-1)
    states, counts = np.unique(tokens, return_counts=True)
    weighted_entropy = 0.0
    weighted_decode = 0.0
    accepted_counts: list[int] = []
    used = 0
    for token, count in zip(states, counts):
        support = int(count)
        support_ratio = float(support / max(1, data.shape[0]))
        if support < discovery_cfg.min_support and support_ratio < discovery_cfg.min_support_ratio:
            continue
        mask = tokens == token
        subset = data[mask]
        weighted_entropy += _safe_div(subset.shape[0], max(1, data.shape[0])) * _mean_remaining_entropy(subset, next_len)
        decode_candidates = analyze_subframe_payload(subset, next_len, payload_cfg)
        weighted_decode += _safe_div(subset.shape[0], max(1, data.shape[0])) * (
            decode_candidates[0].score if decode_candidates else 0.0
        )
        accepted_counts.append(support)
        used += subset.shape[0]
    if used < discovery_cfg.min_support:
        return 0.0, 0.0, 0.0
    split_strength = 0.0
    if len(accepted_counts) > 1:
        split_strength = _safe_div(
            _entropy_from_counts(np.asarray(accepted_counts, dtype=np.int64)),
            max(1.0, np.log2(len(accepted_counts))),
            0.0,
        )
    return float(weighted_entropy), float(weighted_decode), float(split_strength)


def _normalized_decode_score(score: float) -> float:
    return float(max(0.0, min(1.0, score / 1.25)))


def _semantic_score(*, stability_score: float, best_decode_score: float, support_ratio: float) -> float:
    decode_quality = _normalized_decode_score(best_decode_score)
    support_quality = max(0.0, min(1.0, support_ratio / 0.25))
    return float((0.45 * stability_score) + (0.45 * decode_quality) + (0.10 * support_quality))


def _estimate_refinement_gain(
    data: np.ndarray,
    prefix_len: int,
    prefix_lengths: tuple[int, ...],
    discovery_cfg: SubframeDiscoveryConfig,
    payload_cfg: PayloadDecodeConfig,
    current_best_decode_score: float,
) -> tuple[float, str]:
    current_entropy = _mean_remaining_entropy(data, prefix_len)
    best_gain = 0.0
    best_reason = "No longer prefix produced a materially better payload split."
    for next_len in prefix_lengths:
        if next_len <= prefix_len or next_len > data.shape[1]:
            continue
        weighted_entropy, weighted_decode, split_strength = _weighted_refined_decode_quality(
            data,
            next_len,
            discovery_cfg,
            payload_cfg,
        )
        if weighted_entropy == 0.0 and weighted_decode == 0.0 and split_strength == 0.0:
            continue
        entropy_gain = max(0.0, current_entropy - weighted_entropy)
        decode_gain = max(0.0, weighted_decode - current_best_decode_score)
        structural_gain = 0.35 * split_strength
        decode_quality_floor = max(0.35, current_best_decode_score * 0.55)
        if weighted_decode < decode_quality_floor:
            if decode_gain <= 0.0:
                continue
            entropy_gain *= 0.15
            structural_gain *= 0.10
        gain = (
            (discovery_cfg.entropy_gain_weight * entropy_gain)
            + (discovery_cfg.decode_gain_weight * decode_gain)
            + structural_gain
        )
        if gain > best_gain:
            best_gain = gain
            best_reason = (
                f"Refining to {next_len} bytes improves payload semantics "
                f"(entropy_gain={entropy_gain:.3f}, decode_gain={decode_gain:.3f}, split_gain={structural_gain:.3f})."
            )
    return float(best_gain), best_reason


def _numeric_decode_candidate(
    values: np.ndarray,
    *,
    label: str,
    kind: str,
    byte_range: tuple[int, int] | None,
    bit_range: tuple[int, int] | None,
    endian: Endianness | None,
) -> DecodeCandidate | None:
    if values.size < 4:
        return None
    finite = values[np.isfinite(values)]
    if finite.size < 4:
        return None
    rounded = np.round(finite.astype(np.float64), decimals=6)
    uniq, counts = np.unique(rounded, return_counts=True)
    if uniq.size < 2:
        return None
    changes = int(np.count_nonzero(np.diff(rounded) != 0))
    change_rate = float(changes / max(1, rounded.size - 1))
    entropy = _entropy_from_counts(counts)
    diversity = 1.0 - float(counts.max() / max(1, rounded.size))
    magnitude = max(abs(float(np.min(rounded))), abs(float(np.max(rounded))))
    plausibility = 0.0
    if kind == "float32":
        if magnitude < 1_000_000:
            plausibility += 0.65
        if magnitude < 10_000:
            plausibility += 0.15
    else:
        if magnitude > 1_000_000:
            plausibility -= 0.25
        if magnitude > 100_000_000:
            plausibility -= 0.25
    score = (
        (1.1 * change_rate)
        + (0.8 * diversity)
        + (0.4 * _safe_div(entropy, max(1.0, np.log2(max(2, uniq.size))), 0.0))
        + plausibility
    )
    return DecodeCandidate(
        label=label,
        kind=kind,
        byte_range=byte_range,
        bit_range=bit_range,
        endian=endian,
        score=float(score),
        support=int(rounded.size),
        unique_values=int(uniq.size),
        change_rate=float(change_rate),
        min_value=float(np.min(rounded)),
        max_value=float(np.max(rounded)),
    )


def analyze_subframe_payload(data: np.ndarray, payload_start: int, cfg: PayloadDecodeConfig) -> list[DecodeCandidate]:
    frame_len = data.shape[1]
    candidates: list[DecodeCandidate] = []

    if cfg.enable_int_uint:
        for start in range(payload_start, frame_len):
            for width in (1, 2, 3, 4):
                if start + width > frame_len:
                    continue
                for endian in ("be", "le"):
                    uint_values = _extract_uint_values(data, start, width, endian).astype(np.float64)
                    candidate = _numeric_decode_candidate(
                        uint_values,
                        label=f"uint{width * 8}_{endian} @ {start}..{start + width - 1}",
                        kind=f"uint{width * 8}",
                        byte_range=(start, start + width - 1),
                        bit_range=None,
                        endian=endian,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

                    int_values = _extract_int_values(data, start, width, endian).astype(np.float64)
                    candidate = _numeric_decode_candidate(
                        int_values,
                        label=f"int{width * 8}_{endian} @ {start}..{start + width - 1}",
                        kind=f"int{width * 8}",
                        byte_range=(start, start + width - 1),
                        bit_range=None,
                        endian=endian,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

    if cfg.enable_float32:
        for start in range(payload_start, frame_len - 3):
            for endian in ("be", "le"):
                float_values = _extract_float32_values(data, start, endian)
                candidate = _numeric_decode_candidate(
                    float_values,
                    label=f"float32_{endian} @ {start}..{start + 3}",
                    kind="float32",
                    byte_range=(start, start + 3),
                    bit_range=None,
                    endian=endian,
                )
                if candidate is not None:
                    candidates.append(candidate)

    if cfg.enable_bitfields:
        total_bits = frame_len * 8
        for bit_len in (2, 3, 4, 5, 6, 7, 8):
            for start_bit in range(payload_start * 8, total_bits - bit_len + 1):
                values = _extract_bitfield_values(data, start_bit, bit_len).astype(np.float64)
                candidate = _numeric_decode_candidate(
                    values,
                    label=f"bits[{start_bit}:{start_bit + bit_len - 1}]",
                    kind="bitfield",
                    byte_range=None,
                    bit_range=(start_bit, start_bit + bit_len - 1),
                    endian=None,
                )
                if candidate is not None:
                    candidates.append(candidate)

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[: cfg.max_decode_candidates]


def discover_subframe_patterns(
    data: np.ndarray,
    ts: np.ndarray,
    frame_len: int,
    cfg: SubframeDiscoveryConfig,
    payload_cfg: PayloadDecodeConfig,
) -> list[SubframePattern]:
    total_rows = data.shape[0]
    discovered: dict[tuple[int, bytes], SubframePattern] = {}

    for prefix_len in sorted(length for length in cfg.prefix_lengths if 0 < length <= frame_len):
        tokens = np.ascontiguousarray(data[:, :prefix_len]).view(np.dtype((np.void, prefix_len))).reshape(-1)
        states, counts = np.unique(tokens, return_counts=True)
        ranked = sorted(zip(states, counts), key=lambda item: item[1], reverse=True)
        for token, count in ranked:
            support = int(count)
            support_ratio = float(support / max(1, total_rows))
            if support < cfg.min_support and support_ratio < cfg.min_support_ratio:
                continue
            mask = tokens == token
            subset = data[mask]
            subset_ts = ts[mask]
            pattern = bytes(token.tobytes())
            mean_entropy = _mean_remaining_entropy(subset, prefix_len)
            stability_score = max(0.0, 1.0 - _safe_div(mean_entropy, 8.0, 0.0))
            decode_candidates = tuple(analyze_subframe_payload(subset, prefix_len, payload_cfg))
            best_decode = decode_candidates[0] if decode_candidates else None
            best_decode_label = best_decode.label if best_decode is not None else None
            best_decode_score = float(best_decode.score) if best_decode is not None else 0.0
            best_decode_kind = best_decode.kind if best_decode is not None else None
            refinement_gain, refinement_reason = _estimate_refinement_gain(
                subset,
                prefix_len,
                cfg.prefix_lengths,
                cfg,
                payload_cfg,
                best_decode_score,
            )
            semantic_score = _semantic_score(
                stability_score=stability_score,
                best_decode_score=best_decode_score,
                support_ratio=support_ratio,
            )
            decode_ready = best_decode_score >= cfg.min_recommended_decode_score
            semantically_clear = semantic_score >= cfg.min_semantic_score
            recommended = decode_ready and semantically_clear and refinement_gain <= cfg.refinement_gain_threshold
            if not decode_candidates:
                reason = (
                    f"Prefix {prefix_len} has no convincing payload decode yet; "
                    f"semantic_score={semantic_score:.3f}."
                )
            elif not decode_ready:
                reason = (
                    f"Best decode '{best_decode_label}' is still weak "
                    f"(decode_score={best_decode_score:.3f})."
                )
            elif not semantically_clear:
                reason = (
                    f"Prefix {prefix_len} still looks semantically mixed "
                    f"(semantic_score={semantic_score:.3f})."
                )
            elif refinement_gain > cfg.refinement_gain_threshold:
                reason = refinement_reason
            else:
                reason = (
                    f"Prefix {prefix_len} is the smallest stable explanation so far: "
                    f"decode='{best_decode_label}', decode_score={best_decode_score:.3f}, "
                    f"semantic_score={semantic_score:.3f}, refinement_gain={refinement_gain:.3f}."
                )
            sample_frames = tuple(
                SampleFrame(timestamp=float(ts_value), payload_hex=_bytes_label(bytes(row.tolist())))
                for ts_value, row in zip(subset_ts[: cfg.sample_frames_per_pattern], subset[: cfg.sample_frames_per_pattern], strict=False)
            )
            discovered[(prefix_len, pattern)] = SubframePattern(
                pattern=pattern,
                prefix_len=prefix_len,
                support=support,
                support_ratio=support_ratio,
                payload_start=prefix_len,
                remaining_entropy_mean=float(mean_entropy),
                stability_score=float(stability_score),
                refinement_gain=float(refinement_gain),
                best_decode_label=best_decode_label,
                best_decode_score=float(best_decode_score),
                best_decode_kind=best_decode_kind,
                semantic_score=float(semantic_score),
                recommended=bool(recommended),
                recommendation_reason=reason,
                decode_candidates=decode_candidates,
                sample_frames=sample_frames,
            )

    patterns = list(discovered.values())
    patterns.sort(
        key=lambda item: (
            not item.recommended,
            item.prefix_len,
            -item.semantic_score,
            -item.best_decode_score,
            -item.support,
            item.refinement_gain,
        )
    )
    return patterns[: cfg.max_patterns_per_group]


def detect_fast_mux_patterns(
    df: pl.DataFrame,
    can_id: Union[str, int],
    cfg: MuxDetectorConfig | None = None,
) -> dict[int, FrameAnalysis]:
    cfg = cfg or MuxDetectorConfig()
    required = {"ID", "TS", "LEN"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")

    df_id = df.filter(pl.col("ID") == can_id)
    if df_id.is_empty():
        return {}

    analyses: dict[int, FrameAnalysis] = {}
    df_id = df_id.sort("TS")
    for frame_len in sorted(df_id["LEN"].unique().to_list()):
        df_frame = df_id.filter(pl.col("LEN") == frame_len)
        if df_frame.is_empty():
            continue
        data = _to_uint_matrix(df_frame, int(frame_len))
        ts = df_frame["TS"].to_numpy().astype(np.float64, copy=False)
        patterns = tuple(discover_subframe_patterns(data, ts, int(frame_len), cfg.discovery, cfg.payload))
        best_pattern = patterns[0].pattern if patterns else None
        best_pattern_label = _bytes_label(best_pattern) if best_pattern is not None else None
        best_decode_label = None
        if patterns and patterns[0].decode_candidates:
            best_decode_label = patterns[0].decode_candidates[0].label
        analyses[int(frame_len)] = FrameAnalysis(
            can_id=str(can_id),
            frame_len=int(frame_len),
            total_frames=int(data.shape[0]),
            patterns=patterns,
            best_pattern=best_pattern_label,
            best_decode=best_decode_label,
        )
    return analyses
