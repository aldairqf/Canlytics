



from __future__ import annotations



from dataclasses import dataclass, field

from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union



import numpy as np

import polars as pl





Endianness = Literal["be", "le"]





@dataclass(frozen=True)

class MuxDetectorConfig:





    t_min: float = 0.01

    t_max: float = 50.0

    period_mean_median_rel_max: float = 0.5

    period_cv_max: float = 1.0

    max_unaccepted_percent: float = 0.5





    bitrate: float = 250_000.0

    can_overhead_bits: int = 47

    stuff_factor: float = 1.20





    enable_bitfields: bool = True

    byte_lengths: Tuple[int, ...] = (1, 2, 3, 4)

    bit_lengths: Tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8)

    consider_endianness: Tuple[Endianness, ...] = ("be", "le")





    min_unique_values: int = 2

    min_change_rate: float = 0.001

    max_unique_ratio: float = 0.8





    enable_nmi: bool = True

    nmi_group_cap: int = 128

    nmi_threshold: float = 0.15

    top_k_dependent_bytes: int = 3





    enable_window_entropy: bool = True

    window_s: float = 1.0





    max_top_values: int = 10

    max_candidates_per_len: int = 20

    require_early_state_presence: bool = False

    early_state_presence_threshold: float = 0.15

    max_late_state_fraction: float = 0.25





    w_change: float = 1.2

    w_entropy: float = 1.0

    w_diversity: float = 0.8

    w_effective_bits: float = 0.7

    w_period_factor: float = 0.8

    w_regularity: float = 0.6

    w_nmi_mean: float = 1.2

    w_nmi_peak: float = 0.8

    w_nmi_fraction: float = 0.6





    p_unaccepted: float = 1.2

    p_too_many_unique: float = 1.0





    sigmoid_scale: float = 2.0

    sigmoid_bias: float = 2.0





@dataclass(frozen=True)

class CandidateSpec:

    kind: Literal["bytes", "bitfield"]

    frame_len: int





    start_byte: Optional[int] = None

    byte_len: Optional[int] = None





    start_bit: Optional[int] = None

    bit_len: Optional[int] = None

    endian: Optional[Endianness] = None



    def byte_span(self) -> Tuple[int, int]:

        if self.kind == "bytes":

            assert self.start_byte is not None and self.byte_len is not None

            return self.start_byte, self.start_byte + self.byte_len - 1

        assert self.start_bit is not None and self.bit_len is not None

        start_b = self.start_bit // 8

        end_b = (self.start_bit + self.bit_len - 1) // 8

        return start_b, end_b



    def bit_width(self) -> int:

        if self.kind == "bytes":

            assert self.byte_len is not None

            return self.byte_len * 8

        assert self.bit_len is not None

        return self.bit_len



    def label(self) -> str:

        if self.kind == "bytes":

            return f"bytes[{self.start_byte}:{self.start_byte + self.byte_len}]"

        return f"bitfield[{self.endian}]({self.start_bit},{self.bit_len})"





def _sigmoid(x: float) -> float:

    return 1.0 / (1.0 + np.exp(-x))





def _entropy_from_counts(counts: np.ndarray) -> float:

    total = counts.sum()

    if total <= 0:

        return 0.0

    p = counts[counts > 0].astype(np.float64) / float(total)

    return float(-(p * np.log2(p)).sum())





def _safe_div(a: float, b: float, default: float = 0.0) -> float:

    if b == 0:

        return default

    return a / b





def _frame_time_s(frame_len: int, cfg: MuxDetectorConfig) -> float:

    bits = (frame_len * 8) + cfg.can_overhead_bits

    return (bits * cfg.stuff_factor) / cfg.bitrate





def _to_uint_matrix(df_frame: pl.DataFrame, frame_len: int) -> np.ndarray:

    cols = [f"D{i}" for i in range(frame_len)]

    missing = [c for c in cols if c not in df_frame.columns]

    if missing:

        raise ValueError(f"Faltan columnas de payload: {missing}")

    data = np.column_stack([df_frame[c].to_numpy().astype(np.uint8, copy=False) for c in cols])

    return data





def _payload_uint(data: np.ndarray, endian: Endianness) -> np.ndarray:


    n, frame_len = data.shape

    out = np.zeros(n, dtype=np.uint64)

    if endian == "be":

        for i in range(frame_len):

            shift = 8 * (frame_len - 1 - i)

            out |= (data[:, i].astype(np.uint64) << np.uint64(shift))

    else:

        for i in range(frame_len):

            shift = 8 * i

            out |= (data[:, i].astype(np.uint64) << np.uint64(shift))

    return out





def _extract_candidate_values(

    data: np.ndarray,

    payload_be: np.ndarray,

    payload_le: np.ndarray,

    spec: CandidateSpec,

) -> np.ndarray:

    if spec.kind == "bytes":

        assert spec.start_byte is not None and spec.byte_len is not None

        block = data[:, spec.start_byte : spec.start_byte + spec.byte_len].astype(np.uint64, copy=False)

        val = np.zeros(block.shape[0], dtype=np.uint64)

        for i in range(spec.byte_len):

            shift = 8 * (spec.byte_len - 1 - i)

            val |= (block[:, i] << np.uint64(shift))

        return val



    assert spec.start_bit is not None and spec.bit_len is not None and spec.endian is not None

    total_bits = spec.frame_len * 8

    mask = (np.uint64(1) << np.uint64(spec.bit_len)) - np.uint64(1)



    if spec.endian == "be":

        shift = total_bits - (spec.start_bit + spec.bit_len)

        if shift < 0:

            return np.zeros(payload_be.shape[0], dtype=np.uint64)

        return (payload_be >> np.uint64(shift)) & mask





    shift = spec.start_bit

    if shift < 0:

        return np.zeros(payload_le.shape[0], dtype=np.uint64)

    return (payload_le >> np.uint64(shift)) & mask





def _byte_stats(data: np.ndarray) -> List[Dict[str, float]]:


    n = data.shape[0]

    out: List[Dict[str, float]] = []

    denom = max(1, n - 1)

    for i in range(data.shape[1]):

        col = data[:, i]

        changes = int(np.count_nonzero(col[1:] != col[:-1])) if n > 1 else 0

        counts = np.bincount(col.astype(np.uint8, copy=False), minlength=256)

        entropy = _entropy_from_counts(counts)

        top_ratio = float(counts.max() / n) if n > 0 else 1.0

        unique = int(np.count_nonzero(counts))

        out.append(

            {

                "byte": float(i),

                "changes": float(changes),

                "change_rate": float(changes / denom),

                "unique": float(unique),

                "top_ratio": top_ratio,

                "entropy": float(entropy),

            }

        )

    return out





def _value_period_features(

    mux_vals: np.ndarray,

    ts: np.ndarray,

    cfg: MuxDetectorConfig,

) -> Tuple[Dict[int, Dict[str, float]], float, float, float]:

    n = mux_vals.size

    if n < 3:

        return {}, 0.5, 0.5, 1.0



    uniq, inv, counts = np.unique(mux_vals, return_inverse=True, return_counts=True)

    k = uniq.size

    if k == 0:

        return {}, 0.5, 0.5, 1.0





    if k > cfg.nmi_group_cap:



        top_idx = np.argsort(counts)[::-1][: cfg.nmi_group_cap]

        keep_vals = set(uniq[top_idx].tolist())

        mask = np.fromiter((v in keep_vals for v in mux_vals.tolist()), dtype=bool, count=n)

        mux_vals = mux_vals[mask]

        ts = ts[mask]

        uniq = np.array(sorted(keep_vals), dtype=mux_vals.dtype)

        k = uniq.size

        if mux_vals.size < 3:

            return {}, 0.5, 0.5, 1.0



    order = np.lexsort((ts, mux_vals))

    mv = mux_vals[order]

    t = ts[order]



    boundaries = np.flatnonzero(mv[1:] != mv[:-1]) + 1

    starts = np.r_[0, boundaries]

    ends = np.r_[boundaries, mv.size]



    value_periods: Dict[int, Dict[str, float]] = {}

    regularities: List[float] = []

    accepted = 0



    for s, e in zip(starts, ends):

        val = int(mv[s])

        if e - s < 2:

            continue

        periods = np.diff(t[s:e])

        if periods.size < 1:

            continue

        median_p = float(np.median(periods))

        mean_p = float(np.mean(periods))

        if mean_p <= 0:

            continue

        rel = abs(median_p - mean_p) / mean_p

        cv = float(np.std(periods) / mean_p) if mean_p > 0 else 0.0



        ok = (

            cfg.t_min <= median_p <= cfg.t_max

            and rel <= cfg.period_mean_median_rel_max

            and cv <= cfg.period_cv_max

        )

        if ok:

            value_periods[val] = {"median_period": median_p, "mean_period": mean_p, "cv": cv}

            regularities.append(1.0 / (1.0 + cv))

            accepted += 1



    period_factor = _safe_div(accepted, max(1, k), default=0.5)

    regularity_factor = float(np.mean(regularities)) if regularities else 0.5

    unaccepted_percent = 1.0 - period_factor

    return value_periods, regularity_factor, period_factor, unaccepted_percent





def _window_entropy_stats(mux_vals: np.ndarray, ts: np.ndarray, window_s: float) -> Tuple[float, float]:


    if mux_vals.size < 2 or window_s <= 0:

        return 0.0, 0.0

    t0 = float(ts[0])

    bins = np.floor((ts - t0) / window_s).astype(np.int64)

    uniq_bins = np.unique(bins)

    entropies: List[float] = []

    for b in uniq_bins:

        idx = bins == b

        if idx.sum() < 2:

            continue

        _, c = np.unique(mux_vals[idx], return_counts=True)

        entropies.append(_entropy_from_counts(c))

    if not entropies:

        return 0.0, 0.0

    return float(np.mean(entropies)), float(np.std(entropies))





def _nmi_between_discrete(x: np.ndarray, y: np.ndarray, cap_groups: int) -> float:


    n = x.size

    if n < 3:

        return 0.0



    ux, invx, cx = np.unique(x, return_inverse=True, return_counts=True)

    if ux.size < 2:

        return 0.0





    if ux.size > cap_groups:

        top_idx = np.argsort(cx)[::-1][:cap_groups]

        keep = set(ux[top_idx].tolist())

        mask = np.fromiter((v in keep for v in x.tolist()), dtype=bool, count=n)

        x = x[mask]

        y = y[mask]

        if x.size < 3:

            return 0.0

        ux, invx, cx = np.unique(x, return_inverse=True, return_counts=True)

        if ux.size < 2:

            return 0.0





    if y.dtype != np.uint8:

        yb = y.astype(np.uint64, copy=False)

        uy, cy = np.unique(yb, return_counts=True)

        hy = _entropy_from_counts(cy)

    else:

        cy = np.bincount(y, minlength=256)

        hy = _entropy_from_counts(cy)



    if hy <= 1e-12:

        return 0.0





    hy_given_x = 0.0

    for val in ux:

        idx = x == val

        m = int(idx.sum())

        if m < 2:

            continue

        yy = y[idx]

        if yy.dtype == np.uint8:

            cc = np.bincount(yy, minlength=256)

            h = _entropy_from_counts(cc)

        else:

            _, cc = np.unique(yy, return_counts=True)

            h = _entropy_from_counts(cc)

        hy_given_x += (m / x.size) * h



    mi = max(0.0, hy - hy_given_x)

    return float(mi / hy)





def _make_candidates(frame_len: int, cfg: MuxDetectorConfig) -> List[CandidateSpec]:

    candidates: List[CandidateSpec] = []





    for start in range(frame_len):

        for bl in cfg.byte_lengths:

            if start + bl <= frame_len:

                candidates.append(CandidateSpec(kind="bytes", frame_len=frame_len, start_byte=start, byte_len=bl))





    if cfg.enable_bitfields:

        total_bits = frame_len * 8

        for endian in cfg.consider_endianness:

            for bit_len in cfg.bit_lengths:

                if bit_len <= 0 or bit_len > total_bits:

                    continue

                for start_bit in range(0, total_bits - bit_len + 1):

                    candidates.append(

                        CandidateSpec(

                            kind="bitfield",

                            frame_len=frame_len,

                            start_bit=start_bit,

                            bit_len=bit_len,

                            endian=endian,

                        )

                    )

    return candidates





def _top_values(vals: np.ndarray, max_top: int) -> List[Tuple[str, int]]:

    u, c = np.unique(vals, return_counts=True)

    order = np.argsort(c)[::-1][:max_top]

    out: List[Tuple[str, int]] = []

    for i in order:

        v = int(u[i])

        out.append((hex(v), int(c[i])))

    return out


def _state_presence_features(vals: np.ndarray, ts: np.ndarray, cfg: MuxDetectorConfig) -> Tuple[float, float, Dict[int, float]]:

    if vals.size == 0 or ts.size == 0 or vals.size != ts.size:

        return 1.0, 0.0, {}

    start_ts = float(ts[0])

    end_ts = float(ts[-1])

    duration = max(0.0, end_ts - start_ts)

    if duration <= 0.0:

        return 1.0, 0.0, {}

    first_seen: Dict[int, float] = {}

    for value, current_ts in zip(vals.tolist(), ts.tolist()):

        key = int(value)

        if key not in first_seen:

            first_seen[key] = float(current_ts)

    normalized_offsets = {

        key: max(0.0, min(1.0, (first_ts - start_ts) / duration))

        for key, first_ts in first_seen.items()

    }

    late_fraction = 0.0

    if normalized_offsets:

        late_fraction = float(

            np.mean(np.fromiter((offset > cfg.early_state_presence_threshold for offset in normalized_offsets.values()), dtype=bool))

        )

    presence_factor = 1.0 - late_fraction

    return presence_factor, late_fraction, normalized_offsets





def _score_candidate(features: Dict[str, float], cfg: MuxDetectorConfig) -> Tuple[float, float]:


    score = 0.0

    score += cfg.w_change * features.get("change_rate", 0.0)

    score += cfg.w_entropy * features.get("entropy_norm", 0.0)

    score += cfg.w_diversity * features.get("diversity", 0.0)

    score += cfg.w_effective_bits * features.get("effective_bits", 0.0)

    score += cfg.w_period_factor * features.get("period_factor", 0.0)

    score += cfg.w_regularity * features.get("regularity_factor", 0.0)



    if cfg.enable_nmi:

        score += cfg.w_nmi_mean * features.get("nmi_mean", 0.0)

        score += cfg.w_nmi_peak * features.get("nmi_max", 0.0)

        score += cfg.w_nmi_fraction * features.get("nmi_frac", 0.0)





    score -= cfg.p_unaccepted * features.get("unaccepted_percent", 0.0)

    score -= cfg.p_too_many_unique * features.get("too_many_unique_penalty", 0.0)



    prob = _sigmoid(cfg.sigmoid_scale * (score - cfg.sigmoid_bias))

    return float(score), float(prob)





def detect_mux_candidates(

    df: pl.DataFrame,

    can_id: Union[str, int],

    cfg: Optional[MuxDetectorConfig] = None,

) -> Dict[int, List[Dict[str, Any]]]:


    cfg = cfg or MuxDetectorConfig()



    required = {"ID", "TS", "LEN"}

    missing = required - set(df.columns)

    if missing:

        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")



    df_id = df.filter(pl.col("ID") == can_id)

    if df_id.is_empty():

        return {}



    df_id = df_id.sort("TS")

    frame_lens = sorted(df_id["LEN"].unique().to_list())



    results: Dict[int, List[Dict[str, Any]]] = {}



    for frame_len in frame_lens:

        df_frame = df_id.filter(pl.col("LEN") == frame_len)

        if df_frame.is_empty():

            continue



        ts = df_frame["TS"].to_numpy().astype(np.float64, copy=False)

        n_rows = ts.size

        if n_rows < 2:

            continue



        data = _to_uint_matrix(df_frame, frame_len)

        byte_stats = _byte_stats(data)

        payload_be = _payload_uint(data, "be")

        payload_le = _payload_uint(data, "le")



        total_time = float(ts[-1] - ts[0]) if n_rows > 1 else 0.0

        frame_time = _frame_time_s(frame_len, cfg)

        max_frames_physical = total_time / frame_time if frame_time > 0 else float(n_rows)



        candidates_specs = _make_candidates(frame_len, cfg)

        candidates: List[Dict[str, Any]] = []



        for spec in candidates_specs:

            vals = _extract_candidate_values(data, payload_be, payload_le, spec)



            changes = int(np.count_nonzero(vals[1:] != vals[:-1]))

            change_rate = changes / max(1, n_rows - 1)

            if changes == 0 or change_rate < cfg.min_change_rate:

                continue



            uniq, cnt = np.unique(vals, return_counts=True)

            unique_values = int(uniq.size)

            if unique_values < cfg.min_unique_values:

                continue



            unique_ratio = unique_values / n_rows

            if unique_ratio > cfg.max_unique_ratio:



                too_many_unique_penalty = min(1.0, (unique_ratio - cfg.max_unique_ratio) / (1.0 - cfg.max_unique_ratio))

            else:

                too_many_unique_penalty = 0.0



            top_ratio = float(cnt.max() / n_rows)

            entropy = _entropy_from_counts(cnt)





            max_ent = np.log2(unique_values) if unique_values > 1 else 1.0

            entropy_norm = float(entropy / max_ent) if max_ent > 0 else 0.0



            bit_width = spec.bit_width()

            effective_bits = float(_safe_div(np.log2(unique_values), bit_width, default=0.0))

            diversity = float(1.0 - top_ratio)





            value_periods, regularity_factor, period_factor, unaccepted_percent = _value_period_features(vals, ts, cfg)





            start_b, end_b = spec.byte_span()

            other_indices = [i for i in range(frame_len) if not (start_b <= i <= end_b)]



            nmi_by_byte: Dict[int, float] = {}

            nmi_mean = 0.0

            nmi_max = 0.0

            nmi_frac = 0.0

            most_dependent: List[Tuple[int, float]] = []



            if cfg.enable_nmi and other_indices:

                for bi in other_indices:

                    y = data[:, bi]

                    nmi = _nmi_between_discrete(vals, y, cap_groups=cfg.nmi_group_cap)

                    nmi_by_byte[bi] = float(nmi)

                nmis = np.array(list(nmi_by_byte.values()), dtype=np.float64)

                if nmis.size > 0:

                    nmi_mean = float(np.mean(nmis))

                    nmi_max = float(np.max(nmis))

                    nmi_frac = float(np.mean(nmis >= cfg.nmi_threshold))

                    order = np.argsort(nmis)[::-1]

                    topk = min(cfg.top_k_dependent_bytes, order.size)

                    most_dependent = [

                        (other_indices[int(order[i])], float(nmis[int(order[i])]))

                        for i in range(topk)

                    ]





            window_entropy_mean, window_entropy_std = (0.0, 0.0)

            if cfg.enable_window_entropy:

                window_entropy_mean, window_entropy_std = _window_entropy_stats(vals, ts, cfg.window_s)





            other_bytes_stats: List[Dict[str, float]] = []

            for bi in other_indices:

                st = byte_stats[bi].copy()

                other_bytes_stats.append(

                    {

                        "byte": float(bi),

                        "entropy": float(st["entropy"]),

                        "change_rate": float(st["change_rate"]),

                        "top_ratio": float(st["top_ratio"]),

                        "unique": float(st["unique"]),

                    }

                )

            other_bytes_stats.sort(key=lambda d: (-d["entropy"], -d["change_rate"]))









            expected_unique_penalty = 0.0

            if value_periods:

                mean_periods = float(np.mean([v["mean_period"] for v in value_periods.values()]))

                if mean_periods > 0 and total_time > 0:

                    expected_unique = min(max_frames_physical, total_time / mean_periods)

                    if expected_unique > 0 and unique_values > expected_unique:

                        expected_unique_penalty = min(1.0, (unique_values - expected_unique) / max(1.0, expected_unique))



            features = {

                "change_rate": float(np.clip(change_rate, 0.0, 1.0)),

                "entropy_norm": float(np.clip(entropy_norm, 0.0, 1.0)),

                "diversity": float(np.clip(diversity, 0.0, 1.0)),

                "effective_bits": float(np.clip(effective_bits, 0.0, 1.0)),

                "period_factor": float(np.clip(period_factor, 0.0, 1.0)),

                "regularity_factor": float(np.clip(regularity_factor, 0.0, 1.0)),

                "unaccepted_percent": float(np.clip(unaccepted_percent, 0.0, 1.0)),

                "too_many_unique_penalty": float(np.clip(too_many_unique_penalty, 0.0, 1.0)),

                "expected_unique_penalty": float(np.clip(expected_unique_penalty, 0.0, 1.0)),

                "nmi_mean": float(np.clip(nmi_mean, 0.0, 1.0)),

                "nmi_max": float(np.clip(nmi_max, 0.0, 1.0)),

                "nmi_frac": float(np.clip(nmi_frac, 0.0, 1.0)),

            }

            state_presence_factor, late_state_fraction, state_first_seen = _state_presence_features(vals, ts, cfg)





            features["too_many_unique_penalty"] = float(

                np.clip(features["too_many_unique_penalty"] + 0.7 * features["expected_unique_penalty"], 0.0, 1.0)

            )



            score, probability = _score_candidate(features, cfg)

            if cfg.require_early_state_presence and late_state_fraction > cfg.max_late_state_fraction:

                continue



            candidates.append(

                {

                    "spec": {

                        "kind": spec.kind,

                        "label": spec.label(),

                        "start_byte": spec.start_byte,

                        "byte_len": spec.byte_len,

                        "start_bit": spec.start_bit,

                        "bit_len": spec.bit_len,

                        "endian": spec.endian,

                        "byte_span": (start_b, end_b),

                    },

                    "score": float(score),

                    "probability": float(probability),

                    "changes": int(changes),

                    "change_rate": float(change_rate),

                    "unique_values": int(unique_values),

                    "unique_ratio": float(unique_ratio),

                    "top_ratio": float(top_ratio),

                    "entropy": float(entropy),

                    "entropy_norm": float(entropy_norm),

                    "effective_bits": float(effective_bits),

                    "period_factor": float(period_factor),

                    "regularity_factor": float(regularity_factor),

                    "unaccepted_percent": float(unaccepted_percent),

                    "window_entropy_mean": float(window_entropy_mean),

                    "window_entropy_std": float(window_entropy_std),

                    "value_periods": value_periods,

                    "nmi_mean": float(nmi_mean),

                    "nmi_max": float(nmi_max),

                    "nmi_frac": float(nmi_frac),

                    "most_mux_dependent_bytes": most_dependent,

                    "nmi_by_byte": nmi_by_byte,

                    "top_values": _top_values(vals, cfg.max_top_values),

                    "all_states": _top_values(vals, unique_values),

                    "state_presence_factor": float(state_presence_factor),

                    "late_state_fraction": float(late_state_fraction),

                    "state_first_seen_normalized": {

                        hex(int(value)): float(offset) for value, offset in sorted(state_first_seen.items(), key=lambda item: item[0])

                    },

                    "other_bytes_stats": other_bytes_stats[: min(8, len(other_bytes_stats))],

                }

            )





        candidates.sort(key=lambda c: (-c["score"], -c["probability"]))

        selected: List[Dict[str, Any]] = []





        for c in candidates:

            s, e = c["spec"]["byte_span"]

            if any((sc["spec"]["byte_span"][0] <= s and sc["spec"]["byte_span"][1] >= e) for sc in selected):

                continue

            selected.append(c)

            if len(selected) >= cfg.max_candidates_per_len:

                break



        results[int(frame_len)] = selected



    return results

