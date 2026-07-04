from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Union

import numpy as np
import polars as pl

Endianness = Literal["be", "le"]

# analyze_subframe_payload / _numeric_decode_candidate scoring weights -- heuristic,
# used only to *annotate* a recommended candidate with "what this probably decodes
# as"; they do not affect which byte range gets recommended as the mux discriminator.
_DECODE_CHANGE_RATE_WEIGHT = 1.1
_DECODE_DIVERSITY_WEIGHT = 0.8
_DECODE_ENTROPY_WEIGHT = 0.4
_DECODE_FLOAT_SMALL_MAGNITUDE = 10_000
_DECODE_FLOAT_LARGE_MAGNITUDE = 1_000_000
_DECODE_INT_LARGE_MAGNITUDE = 1_000_000
_DECODE_INT_HUGE_MAGNITUDE = 100_000_000

_MAX_SAMPLE_VALUES = 8
_MAX_SAMPLE_FRAMES = 3


@dataclass(frozen=True)
class PayloadDecodeConfig:
    enable_int_uint: bool = True
    enable_float32: bool = True
    enable_bitfields: bool = False
    max_decode_candidates: int = 12


@dataclass(frozen=True)
class MuxDetectorConfig:
    """Tunables for detect_fast_mux_patterns.

    Every field gates exactly one step of discover_mux_candidates and is
    meaningful on its own -- there are no derived/coupled weights to tune.
    """

    candidate_widths: tuple[int, ...] = (1, 2, 3, 4)
    min_support: int = 10  # frames a discriminator value needs to count as a real group
    min_covered_ratio: float = 0.5  # fraction of frames that must fall into groups with enough support
    max_cardinality: int = 32  # absolute cap on distinct discriminator values
    max_cardinality_ratio: float = 0.2  # cardinality cap relative to the group's frame count
    min_explainable_bytes: int = 2  # remaining bytes with nonzero baseline entropy needed to trust the score
    counter_like_ratio: float = 0.9  # fraction of "value+1 (mod cardinality)" steps flagged as cyclical
    min_nmi: float = 0.5  # 0..1 acceptance threshold on normalized mutual information
    parsimony_tolerance: float = 0.03  # keep the narrowest candidate within this of the group's best score
    max_candidates_per_group: int = 10
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
class MuxCandidate:
    """A byte range evaluated as a possible mux discriminator.

    ``information_gain`` is normalized mutual information (0..1): how much of
    the *better-explained half* of the bytes outside ``byte_range`` has its
    entropy reduced once you know the discriminator's value (see
    ``_mean_information_gain``). Only the stronger half is averaged, not
    every remaining byte, so a real discriminator isn't punished for sharing
    the frame with an unrelated signal (e.g. a continuously-varying sensor
    reading) that it was never meant to explain. 1.0 means those bytes are
    fully determined by the discriminator; 0.0 means no dependency at all.
    """

    byte_range: tuple[int, int]  # (start, end_inclusive) -- anywhere in the frame, not just a prefix
    width: int
    cardinality: int
    support: int  # frames covered by discriminator values with enough support
    coverage_ratio: float
    information_gain: float
    counter_like: bool  # value sequence cycles like a free-running counter -- informational only
    recommended: bool
    reason: str
    top_decode: DecodeCandidate | None
    sample_values: tuple[tuple[int, int], ...]  # (value, count), most frequent first
    sample_frames: tuple[SampleFrame, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_range": list(self.byte_range),
            "width": int(self.width),
            "cardinality": int(self.cardinality),
            "support": int(self.support),
            "coverage_ratio": float(self.coverage_ratio),
            "information_gain": float(self.information_gain),
            "counter_like": bool(self.counter_like),
            "recommended": bool(self.recommended),
            "reason": self.reason,
            "top_decode": self.top_decode.to_dict() if self.top_decode is not None else None,
            "sample_values": [[int(value), int(count)] for value, count in self.sample_values],
            "sample_frames": [frame.to_dict() for frame in self.sample_frames],
        }


@dataclass(frozen=True)
class FrameAnalysis:
    can_id: str
    frame_len: int
    total_frames: int
    candidates: tuple[MuxCandidate, ...]
    best_candidate: str | None
    best_decode: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_id": self.can_id,
            "frame_len": int(self.frame_len),
            "total_frames": int(self.total_frames),
            "candidate_count": len(self.candidates),
            "best_candidate": self.best_candidate,
            "best_decode": self.best_decode,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
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
        if magnitude < _DECODE_FLOAT_LARGE_MAGNITUDE:
            plausibility += 0.65
        if magnitude < _DECODE_FLOAT_SMALL_MAGNITUDE:
            plausibility += 0.15
    else:
        if magnitude > _DECODE_INT_LARGE_MAGNITUDE:
            plausibility -= 0.25
        if magnitude > _DECODE_INT_HUGE_MAGNITUDE:
            plausibility -= 0.25
    score = (
        (_DECODE_CHANGE_RATE_WEIGHT * change_rate)
        + (_DECODE_DIVERSITY_WEIGHT * diversity)
        + (_DECODE_ENTROPY_WEIGHT * _safe_div(entropy, max(1.0, np.log2(max(2, uniq.size))), 0.0))
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
    """Suggest what the bytes from ``payload_start`` to the end of the frame decode as.

    This is an annotation on top of a recommended mux candidate, not part of
    detection itself -- it only looks at the contiguous suffix *after* the
    candidate's byte range, even if the candidate sits in the middle of the
    frame (bytes before it are not considered here).
    """
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


def _candidate_value(data: np.ndarray, start: int, width: int) -> np.ndarray:
    block = data[:, start : start + width].astype(np.uint64)
    values = np.zeros(data.shape[0], dtype=np.uint64)
    for idx in range(width):
        values |= block[:, idx] << np.uint64(8 * (width - 1 - idx))
    return values


def _cardinality_within_bounds(values: np.ndarray, cfg: MuxDetectorConfig) -> np.ndarray | None:
    uniq = np.unique(values)
    cardinality = uniq.size
    if cardinality < 2:
        return None
    cap = min(cfg.max_cardinality, max(2, int(cfg.max_cardinality_ratio * values.size)))
    if cardinality > cap:
        return None
    return uniq


def _supported_groups(
    values: np.ndarray, uniq: np.ndarray, cfg: MuxDetectorConfig
) -> tuple[np.ndarray, np.ndarray, int] | None:
    counts = np.array([int(np.count_nonzero(values == value)) for value in uniq])
    keep = counts >= cfg.min_support
    if int(keep.sum()) < 2:
        return None
    covered = int(counts[keep].sum())
    if covered / max(1, values.size) < cfg.min_covered_ratio:
        return None
    return uniq[keep], counts[keep], covered


def _eta_squared(groups: list[np.ndarray]) -> float:
    """Fraction of a numeric byte's variance explained by group membership (one-way ANOVA)."""
    non_empty = [g for g in groups if g.size > 0]
    if len(non_empty) < 2:
        return 0.0
    all_values = np.concatenate(non_empty)
    grand_mean = float(np.mean(all_values))
    ss_total = float(np.sum((all_values - grand_mean) ** 2))
    if ss_total <= 1e-9:
        return 0.0
    ss_between = sum(g.size * (float(np.mean(g)) - grand_mean) ** 2 for g in non_empty)
    return max(0.0, min(1.0, ss_between / ss_total))


def _mean_information_gain(
    data: np.ndarray,
    values: np.ndarray,
    kept_values: np.ndarray,
    kept_counts: np.ndarray,
    remaining_cols: list[int],
    min_explainable_bytes: int,
) -> tuple[float, int] | None:
    total_kept = int(kept_counts.sum())
    masks = [values == value for value in kept_values]
    ratios: list[float] = []
    for col in remaining_cols:
        column = data[:, col]
        base_counts = np.bincount(column, minlength=256)
        h_base = _entropy_from_counts(base_counts)
        if h_base <= 1e-9:
            continue  # constant byte across the whole group -- nothing to explain

        h_cond = 0.0
        for mask, count in zip(masks, kept_counts):
            sub_counts = np.bincount(column[mask], minlength=256)
            h_cond += (float(count) / total_kept) * _entropy_from_counts(sub_counts)
        entropy_ratio = max(0.0, h_base - h_cond) / h_base

        # Entropy rewards a byte collapsing onto a few discrete values per
        # group -- a continuously-varying analog signal (e.g. a slowly
        # drifting sensor reading) never does that even when it is genuinely
        # gated by the discriminator, so it always scores poorly on entropy
        # alone. eta-squared (fraction of variance explained by group
        # membership) catches that case: each group can shift the *level* of
        # a still-noisy signal without ever collapsing its distribution.
        eta_sq = _eta_squared([column[mask].astype(np.float64) for mask in masks])

        ratios.append(max(entropy_ratio, eta_sq))
    explainable = len(ratios)
    if explainable < min_explainable_bytes:
        return None
    # A real discriminator only has to explain a meaningful *portion* of the
    # rest of the frame -- other bytes can be an unrelated signal that just
    # shares the same message (e.g. a continuously-varying sensor reading),
    # and averaging those in would unfairly punish an otherwise-real
    # candidate. Average only the better half of the per-byte ratios, while
    # still requiring at least min_explainable_bytes to contribute.
    top_k = max(min_explainable_bytes, -(-explainable // 2))  # ceil(explainable / 2)
    top_ratios = sorted(ratios, reverse=True)[:top_k]
    return float(np.mean(top_ratios)), explainable


def _is_counter_like(values: np.ndarray, cardinality: int, threshold: float) -> bool:
    if cardinality < 2 or values.size < 3:
        return False
    steps = values[1:] == ((values[:-1] + 1) % np.uint64(cardinality))
    return float(np.mean(steps)) > threshold


def _describe_candidate(
    *, nmi: float, explainable: int, coverage_ratio: float, counter_like: bool, cfg: MuxDetectorConfig
) -> str:
    if nmi < cfg.min_nmi:
        return (
            f"Explains only {nmi:.0%} of the remaining {explainable} byte(s)' variability "
            f"-- below the {cfg.min_nmi:.0%} threshold."
        )
    note = ""
    if counter_like:
        note = " Value sequence cycles like a counter -- verify it is a real state, not a free-running tick."
    return (
        f"Explains {nmi:.0%} of the remaining {explainable} byte(s)' variability, "
        f"covering {coverage_ratio:.0%} of frames.{note}"
    )


def _select_winner(
    scored: list[tuple[tuple[int, int], MuxCandidate]], cfg: MuxDetectorConfig
) -> None:
    """Exactly one candidate per group ends up ``recommended`` (or none).

    A real mux byte makes nearly every *other* byte partly predictable too
    (they all depend on the same underlying state), so several unrelated byte
    ranges can independently clear ``min_nmi`` -- that alone must not produce
    multiple simultaneous "recommended" discriminators for one message. Only
    the single, narrowest candidate within ``parsimony_tolerance`` of the
    group's best score wins; every other candidate is demoted to
    ``recommended=False``, even if its own score is above ``min_nmi``.
    """
    eligible = [(key, candidate) for key, candidate in scored if candidate.information_gain >= cfg.min_nmi]
    if not eligible:
        return
    best_nmi = max(candidate.information_gain for _, candidate in eligible)
    close_keys = {
        key
        for key, candidate in eligible
        if candidate.information_gain >= best_nmi - cfg.parsimony_tolerance
    }
    winner_key = min(close_keys, key=lambda key: (key[1], key[0]))  # (width, start)
    for idx, (key, candidate) in enumerate(scored):
        is_winner = key == winner_key
        if candidate.recommended == is_winner:
            continue
        note = "" if is_winner else " Not the strongest candidate for this group -- see the recommended range instead."
        scored[idx] = (key, replace(candidate, recommended=is_winner, reason=candidate.reason + note))


def discover_mux_candidates(
    data: np.ndarray,
    ts: np.ndarray,
    frame_len: int,
    cfg: MuxDetectorConfig,
) -> list[MuxCandidate]:
    total = data.shape[0]
    scored: list[tuple[tuple[int, int], MuxCandidate]] = []

    for start in range(frame_len):
        widths_here = sorted(w for w in cfg.candidate_widths if 0 < w and start + w <= frame_len)
        if not widths_here:
            continue

        for width in widths_here:
            remaining_cols = [c for c in range(frame_len) if not (start <= c < start + width)]
            values = _candidate_value(data, start, width)
            uniq = _cardinality_within_bounds(values, cfg)
            if uniq is None:
                continue
            supported = _supported_groups(values, uniq, cfg)
            if supported is None:
                continue
            kept_values, kept_counts, covered = supported
            gain_result = _mean_information_gain(
                data, values, kept_values, kept_counts, remaining_cols, cfg.min_explainable_bytes
            )
            if gain_result is None:
                continue
            nmi, explainable = gain_result
            coverage_ratio = covered / total
            counter_like = _is_counter_like(values, int(uniq.size), cfg.counter_like_ratio)
            recommended = nmi >= cfg.min_nmi

            decode_candidates: list[DecodeCandidate] = []
            if recommended and start + width < frame_len:
                decode_candidates = analyze_subframe_payload(data, start + width, cfg.payload)
            top_decode = decode_candidates[0] if decode_candidates else None

            order = np.argsort(-kept_counts)
            sample_values = tuple(
                (int(kept_values[i]), int(kept_counts[i])) for i in order[:_MAX_SAMPLE_VALUES]
            )
            sample_frames = tuple(
                SampleFrame(timestamp=float(ts[i]), payload_hex=_bytes_label(bytes(data[i].tolist())))
                for i in range(min(_MAX_SAMPLE_FRAMES, total))
            )

            candidate = MuxCandidate(
                byte_range=(start, start + width - 1),
                width=width,
                cardinality=int(uniq.size),
                support=int(covered),
                coverage_ratio=float(coverage_ratio),
                information_gain=float(nmi),
                counter_like=bool(counter_like),
                recommended=bool(recommended),
                reason=_describe_candidate(
                    nmi=nmi, explainable=explainable, coverage_ratio=coverage_ratio,
                    counter_like=counter_like, cfg=cfg,
                ),
                top_decode=top_decode,
                sample_values=sample_values,
                sample_frames=sample_frames,
            )
            scored.append(((start, width), candidate))

    _select_winner(scored, cfg)

    candidates = [candidate for _, candidate in scored]
    candidates.sort(
        key=lambda item: (not item.recommended, -item.information_gain, item.width, item.byte_range[0])
    )
    return candidates[: cfg.max_candidates_per_group]


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
        candidates = tuple(discover_mux_candidates(data, ts, int(frame_len), cfg))
        best_candidate = candidates[0] if candidates else None
        best_candidate_label = (
            f"bytes {best_candidate.byte_range[0]}..{best_candidate.byte_range[1]}"
            if best_candidate is not None
            else None
        )
        best_decode_label = (
            best_candidate.top_decode.label if best_candidate and best_candidate.top_decode else None
        )
        analyses[int(frame_len)] = FrameAnalysis(
            can_id=str(can_id),
            frame_len=int(frame_len),
            total_frames=int(data.shape[0]),
            candidates=candidates,
            best_candidate=best_candidate_label,
            best_decode=best_decode_label,
        )
    return analyses
