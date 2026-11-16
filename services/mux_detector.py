from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import polars as pl

from config.defaults import (MUX_EXTENSION_MIN_DETERMINISM, MUX_EXTENSION_TOLERANCE, MUX_MAX_VALUES, MUX_MIN_CHANGE_RATE,
                             MUX_MIN_COVERAGE, MUX_MIN_GAIN, MUX_MIN_SUPPORT,
                             MUX_MIN_SUPPORT_RATIO, MUX_MIN_VALUES, MUX_CONFIDENCE_HIGH_MARGIN,
                             MUX_CONFIDENCE_MEDIUM_MARGIN, MUX_CONFIDENCE_STABLE_CV,
                             MUX_CONFIDENCE_HIGH_COVERAGE,
                             MUX_CONFIDENCE_MEDIUM_EXTENSION_AGREEMENT,
                             MUX_CONFIDENCE_HIGH_STABILITY, MUX_CONFIDENCE_MEDIUM_STABILITY,
                             MUX_CONFIDENCE_HIGH_EXTENSION_AGREEMENT)


@dataclass(frozen=True)
class MuxDetectorConfig:
    min_values: int = MUX_MIN_VALUES
    max_values: int = MUX_MAX_VALUES
    min_support: int = MUX_MIN_SUPPORT
    min_support_ratio: float = MUX_MIN_SUPPORT_RATIO
    min_coverage: float = MUX_MIN_COVERAGE
    min_change_rate: float = MUX_MIN_CHANGE_RATE
    min_gain: float = MUX_MIN_GAIN
    extension_tolerance: float = MUX_EXTENSION_TOLERANCE
    extension_min_determinism: float = MUX_EXTENSION_MIN_DETERMINISM


def detect_muxes(
    df: pl.DataFrame,
    can_ids: list[str] | None = None,
    config: MuxDetectorConfig | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    forced_selectors: dict[str, tuple[int, ...]] | None = None,
) -> list[dict[str, object]]:
    """Find compact selectors per CAN ID using vectorized byte and transition counts."""
    cfg = config or MuxDetectorConfig()
    required = {"ID", "LEN", "TS", *(f"D{i}" for i in range(8))}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing CAN columns: {sorted(required - set(df.columns))}")
    ids = sorted(set(str(v).upper() for v in df["ID"].to_list()))
    if can_ids is not None:
        selected = {str(v).upper() for v in can_ids}
        ids = [value for value in ids if value in selected]
    results: list[dict[str, object]] = []
    for i, can_id in enumerate(ids):
        if cancelled and cancelled():
            break
        group = df.filter(pl.col("ID").cast(pl.Utf8).str.to_uppercase() == can_id)
        forced = (forced_selectors or {}).get(can_id)
        results.append(_detect_id(group, can_id, cfg, forced))
        if progress:
            progress(i + 1, len(ids))
    return results


def _detect_id(
    group: pl.DataFrame,
    can_id: str,
    cfg: MuxDetectorConfig,
    forced_selector: tuple[int, ...] | None = None,
) -> dict[str, object]:
    n = group.height
    data = np.column_stack([group[f"D{i}"].to_numpy().astype(np.uint8, copy=False) for i in range(8)])
    lengths = group["LEN"].to_numpy().astype(np.uint8, copy=False)
    ts = group["TS"].to_numpy().astype(np.float64, copy=False)
    candidates: list[dict[str, object]] = []
    discarded = {"counter": 0, "dlc": 0, "hierarchy": 0, "filters": 0}
    support_floor = max(cfg.min_support, int(n * cfg.min_support_ratio))
    for start in range(8):
        for width in range(1, min(4, 8 - start) + 1):
            if forced_selector is not None and (start, width) != (forced_selector[0], len(forced_selector)):
                continue
            valid = lengths > start
            if int(valid.sum()) < cfg.min_support:
                discarded["dlc"] += 1
                continue
            available = np.minimum(lengths[valid].astype(np.int16) - start, width).astype(np.uint64)
            packed = _pack(data[valid, start:start + width]).astype(np.uint64)
            raw_values = (packed << np.uint64(4)) | available
            unique, inverse, counts = np.unique(raw_values, return_inverse=True, return_counts=True)
            supported = counts >= support_floor
            k = int(supported.sum())
            if k < cfg.min_values or k > cfg.max_values:
                discarded["filters"] += 1
                continue
            coverage = float(counts[supported].sum() / max(1, n))
            if coverage < cfg.min_coverage:
                discarded["filters"] += 1
                continue
            state_map = np.full(len(unique), -1, dtype=np.int32)
            state_map[supported] = np.arange(k, dtype=np.int32)
            all_states = state_map[inverse]
            accepted = all_states >= 0
            matrix = data[valid][accepted]
            states = all_states[accepted]
            accepted_values = raw_values[accepted]
            change = float(np.count_nonzero(np.diff(states)) / max(1, len(states) - 1))
            gain = _conditional_gain(matrix, states, start, width)
            if change < cfg.min_change_rate:
                discarded["filters"] += 1
                continue
            counter = _counter_like(states, accepted_values)
            if counter:
                discarded["counter"] += 1
            score = gain
            candidates.append({"start": start, "width": width, "values": unique[supported],
                               "inverse": states, "counts": counts[supported], "valid": valid,
                               "accepted": accepted, "row_values": raw_values[accepted], "gain": gain, "score": score,
                               "coverage": coverage, "change": change, "k": k,
                               "counter": counter, "frame_indices": np.flatnonzero(valid)[accepted]})
    viable = [candidate for candidate in candidates
              if float(candidate["score"]) >= cfg.min_gain]
    hierarchy_suspected = False
    for base in candidates:
        for extended in candidates:
            adjacent = (int(extended["width"]) == int(base["width"]) + 1
                        and int(extended["start"]) in (int(base["start"]) - 1, int(base["start"])))
            if (adjacent and float(base["score"]) >= cfg.min_gain
                    and int(extended["k"]) > 2 * int(base["k"])):
                if float(extended["score"]) >= cfg.extension_tolerance * float(base["score"]):
                    hierarchy_suspected = True
                    break
        if hierarchy_suspected:
            break
    if hierarchy_suspected:
        discarded["hierarchy"] += 1
    if not viable:
        return {"can_id": can_id, "selector": (), "values": [], "confidence": None, "has_mux": False,
                "counter_like": discarded["counter"] > 0, "variable_dlc": bool(np.unique(lengths).size > 1),
                "hierarchy_suspected": hierarchy_suspected, "discarded": discarded, "frame_count": n,
                "coverage": 0.0, "gain_margin": 0.0, "period_stability": 0.0,
                "extension_agreement": None}
    best_gain = max(float(candidate["score"]) for candidate in viable)
    eligible = [candidate for candidate in viable
                if float(candidate["score"]) >= cfg.extension_tolerance * best_gain]
    eligible.sort(key=lambda candidate: (int(candidate["width"]), int(candidate["start"]),
                                         -float(candidate["score"])))
    chosen = eligible[0]
    initial = chosen
    if forced_selector is None:
        chosen = _extend_adjacent_candidates(chosen, candidates, cfg)
    extension_agreement = (
        _extension_determinism(initial, chosen)
        if chosen is not initial else None
    )
    valid_ts = ts[np.asarray(chosen["valid"])][np.asarray(chosen["accepted"])]
    valid_len = lengths[np.asarray(chosen["valid"])][np.asarray(chosen["accepted"])]
    states = np.asarray(chosen["inverse"])
    value_rows = []
    for state, raw_value in enumerate(np.asarray(chosen["values"])):
        positions = np.flatnonzero(states == state)
        periods = np.diff(valid_ts[positions])
        median = float(np.median(periods)) if periods.size else None
        cv = float(np.std(periods) / np.mean(periods)) if periods.size and np.mean(periods) else None
        dlc, dlc_counts = np.unique(valid_len[positions], return_counts=True)
        packed_value = int(raw_value) >> 4
        available = int(raw_value) & 0xF
        label = f"{packed_value:0{int(chosen['width']) * 2}X}"
        if available < int(chosen["width"]):
            label += f" (DLC {int(chosen['start']) + available})"
        value_rows.append({"value": label, "n": int(len(positions)),
                           "period_median": median, "cv": cv, "dlc": int(dlc[np.argmax(dlc_counts)])})
    score = float(chosen["score"])
    other_scores = [float(candidate["score"]) for candidate in candidates if candidate is not chosen]
    gain_margin = score - max(other_scores, default=0.0)
    stable_values = [float(row["cv"]) <= MUX_CONFIDENCE_STABLE_CV
                     for row in value_rows if row["cv"] is not None]
    period_stability = float(sum(stable_values) / len(stable_values)) if stable_values else 0.0
    ambiguous = any(candidate is not chosen and int(candidate["k"]) == int(chosen["k"])
                    and float(candidate["coverage"]) >= cfg.min_coverage
                    and float(candidate["score"]) >= cfg.extension_tolerance * score
                    for candidate in candidates)
    confidence = _confidence_from_evidence(
        coverage=float(chosen["coverage"]), gain_margin=gain_margin,
        period_stability=period_stability, extension_agreement=extension_agreement,
        ambiguous=ambiguous,
    )
    return {"can_id": can_id, "selector": tuple(range(int(chosen["start"]), int(chosen["start"]) + int(chosen["width"]))),
            "values": value_rows, "confidence": confidence, "has_mux": score >= cfg.min_gain,
            "gain": float(chosen["gain"]), "score": score, "counter_like": discarded["counter"] > 0,
            "variable_dlc": bool(np.unique(lengths).size > 1),
            "hierarchy_suspected": hierarchy_suspected or discarded["hierarchy"] > 0,
            "selector_ambiguous": ambiguous,
            "discarded": discarded, "frame_count": n, "coverage": float(chosen["coverage"]),
            "gain_margin": gain_margin, "period_stability": period_stability,
            "extension_agreement": extension_agreement}


def _confidence_from_evidence(
    *, coverage: float, gain_margin: float, period_stability: float,
    extension_agreement: float | None, ambiguous: bool,
) -> str:
    """Rank selector evidence using coverage, competing-window margin, timing and extension."""
    extension_confirmed = (
        extension_agreement is not None
        and extension_agreement >= MUX_CONFIDENCE_MEDIUM_EXTENSION_AGREEMENT
    )
    if (coverage >= MUX_CONFIDENCE_HIGH_COVERAGE
            and period_stability >= MUX_CONFIDENCE_HIGH_STABILITY
            and ((extension_agreement or 0.0) >= MUX_CONFIDENCE_HIGH_EXTENSION_AGREEMENT
                 or gain_margin >= MUX_CONFIDENCE_HIGH_MARGIN)
            and (not ambiguous or extension_confirmed)):
        return "high"
    if (coverage >= MUX_MIN_COVERAGE and period_stability >= MUX_CONFIDENCE_MEDIUM_STABILITY
            and (gain_margin >= MUX_CONFIDENCE_MEDIUM_MARGIN or extension_confirmed)):
        return "medium"
    return "low"

def _pack(block: np.ndarray) -> np.ndarray:
    result = np.zeros(block.shape[0], dtype=np.uint32)
    for col in range(block.shape[1]):
        result = (result << 8) | block[:, col].astype(np.uint32)
    return result


def _extend_adjacent_candidates(
    chosen: dict[str, object], candidates: list[dict[str, object]], cfg: MuxDetectorConfig
) -> dict[str, object]:
    """Extend a selector while wider nested candidates retain evidence."""
    initial_k = int(chosen["k"])
    while True:
        start = int(chosen["start"])
        end = start + int(chosen["width"])
        extensions = []
        for candidate in candidates:
            candidate_start = int(candidate["start"])
            candidate_width = int(candidate["width"])
            candidate_k = int(candidate["k"])
            determinism = _extension_determinism(chosen, candidate)
            grew_support = candidate_k > int(chosen["k"])
            equivalent_left_step = (candidate_k == int(chosen["k"])
                                    and candidate_start == start - 1
                                    and candidate_width == int(chosen["width"]) + 1)
            if (candidate_width > int(chosen["width"])
                    and candidate_start <= start
                    and candidate_start + candidate_width >= end
                    and (grew_support or equivalent_left_step)
                    and candidate_k <= 2 * int(chosen["k"])
                    and candidate_k <= 2 * initial_k
                    and candidate_k <= cfg.max_values
                    and float(candidate["coverage"]) >= cfg.min_coverage
                    and float(candidate["score"]) >= cfg.extension_tolerance * float(chosen["score"])
                    and determinism >= cfg.extension_min_determinism):
                extensions.append(candidate)
        if not extensions:
            return chosen
        extensions.sort(key=lambda candidate: (int(candidate["width"]), int(candidate["start"]),
                                               -float(candidate["score"])))
        chosen = extensions[0]


def _extension_determinism(base: dict[str, object], extension: dict[str, object]) -> float:
    """Measure whether each base value maps consistently to an extended value."""
    if "frame_indices" not in base or "frame_indices" not in extension:
        return float(extension.get("extension_determinism", 0.0))
    base_indices = np.asarray(base["frame_indices"])
    extended_indices = np.asarray(extension["frame_indices"])
    common = np.intersect1d(base_indices, extended_indices, assume_unique=True)
    if common.size == 0:
        return 0.0
    base_rows = np.searchsorted(base_indices, common)
    extended_rows = np.searchsorted(extended_indices, common)
    base_states = np.asarray(base["inverse"])[base_rows].astype(np.int64, copy=False)
    extended_states = np.asarray(extension["inverse"])[extended_rows].astype(np.int64, copy=False)
    base_k, extended_k = int(base["k"]), int(extension["k"])
    joint = np.bincount(base_states * extended_k + extended_states,
                        minlength=base_k * extended_k).reshape(base_k, extended_k)
    totals = joint.sum(axis=1)
    supported = totals > 0
    return float(joint.max(axis=1)[supported].sum() / common.size)


def _entropy(counts: np.ndarray) -> float:
    counts = counts[counts > 0].astype(np.float64)
    if not counts.size:
        return 0.0
    probabilities = counts / counts.sum()
    return float(-np.sum(probabilities * np.log2(probabilities)))


def _conditional_gain(data: np.ndarray, states: np.ndarray, selector_start: int, selector_width: int) -> float:
    gains: list[float] = []
    n = len(states)
    k = int(states.max()) + 1
    for col in range(data.shape[1]):
        if selector_start <= col < selector_start + selector_width:
            continue
        values = data[:, col].astype(np.int64, copy=False)
        marginal = np.bincount(values, minlength=256)
        marginal_entropy = _entropy(marginal)
        if marginal_entropy < 0.5:
            continue
        joint = np.bincount(states.astype(np.int64) * 256 + values, minlength=k * 256).reshape(k, 256)
        state_totals = joint.sum(axis=1)
        conditional_entropy = 0.0
        for state in range(k):
            if state_totals[state]:
                conditional_entropy += state_totals[state] / n * _entropy(joint[state])
        active_values = int(np.count_nonzero(marginal))
        bias = (k - 1) * (active_values - 1) / (2 * n * np.log(2))
        gains.append(max(0.0, (marginal_entropy - conditional_entropy - bias) / marginal_entropy))
    gains.sort(reverse=True)
    top = gains[:max(1, (len(gains) + 1) // 2)]
    return float(np.mean(top)) if top else 0.0

def _counter_like(states: np.ndarray, values: np.ndarray) -> bool:
    if len(states) < 8 or len(np.unique(values)) > 128:
        return False
    current, following = states[:-1], states[1:]
    changed = current != following
    current, following = current[changed], following[changed]
    if not current.size:
        return False
    pairs = np.bincount(current.astype(np.int64) * int(states.max() + 1) + following,
                        minlength=int(states.max() + 1) ** 2).reshape(int(states.max() + 1), -1)
    successor = np.argmax(pairs, axis=1)
    support = pairs.sum(axis=1)
    deterministic = float(pairs.max(axis=1)[support > 0].sum() / max(1, support[support > 0].sum()))
    vals = np.unique(values.astype(np.uint64) >> np.uint64(4))
    ordered = np.sort(vals)
    adjacent = np.all(np.diff(ordered) == 1)
    expected = np.roll(np.arange(len(ordered)), -1)
    follows_sequence = bool(np.all(successor[:len(ordered)][support[:len(ordered)] > 0]
                                   == expected[support[:len(ordered)] > 0]))
    return bool(adjacent and deterministic > 0.9 and follows_sequence)
