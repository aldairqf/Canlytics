from __future__ import annotations

"""Convert a pipeline simple_config dict into a Python formula string.

The generated code is valid input for ``services.formula_evaluator.evaluate()``.
"""

_MATH_FN_MAP: dict[str, str] = {
    "sqrt":  "np.sqrt",
    "abs":   "np.abs",
    "log10": "np.log10",
    "ln":    "np.log",
    "exp":   "np.exp",
    "sin":   "np.sin",
    "cos":   "np.cos",
    "tan":   "np.tan",
}

_COMBINE_SYM: dict[str, str] = {
    "add": "+", "sub": "-", "mul": "*", "div": "/",
}


def generate_formula(config: dict) -> str:
    """Convert a pipeline ``simple_config`` dict to a Python formula string.

    Parameters
    ----------
    config:
        Dict with keys ``type``, ``branches``, ``combine``,
        ``output_transforms``.

    Returns
    -------
    str
        Multi-line Python script ready for the formula sandbox.

    Raises
    ------
    ValueError
        No sources, unknown source kind, unknown transform op, or unknown math fn.
    """
    branches, combine_ops, output_transforms = _normalize_pipeline(config)

    lines: list[str] = []

    if len(branches) == 1:
        branch = branches[0]
        lines.extend(_source_lines(branch["source"], "ts", "y"))
        for t in branch.get("transforms", []):
            lines.append(_transform_line(t, "y"))
    else:
        ts_vars: list[str] = []
        y_vars: list[str] = []
        for idx, branch in enumerate(branches):
            suffix = _branch_suffix(idx)
            ts_var = f"ts_{suffix}"
            y_var = f"y_{suffix}"
            ts_vars.append(ts_var)
            y_vars.append(y_var)
            lines.extend(_source_lines(branch["source"], ts_var, y_var))
            for t in branch.get("transforms", []):
                lines.append(_transform_line(t, y_var))
        align_args = ", ".join(f"({ts_var}, {y_var})" for ts_var, y_var in zip(ts_vars, y_vars))
        aligned_vars = ", ".join(y_vars)
        lines.append(f"ts, ({aligned_vars}) = align({align_args})")
        lines.append(f"y = {y_vars[0]}")
        for op, y_var in zip(combine_ops, y_vars[1:]):
            lines.append(_combine_line(op, "y", y_var))

    for t in output_transforms:
        lines.append(_transform_line(t, "y"))

    lines.append("result = ts, y")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Source code generators
# ---------------------------------------------------------------------------

def _normalize_pipeline(config: dict) -> tuple[list[dict], list[str], list[dict]]:
    branches = config.get("branches") or []
    if not branches:
        raise ValueError("Pipeline has no sources.")
    normalized = []
    for idx, branch in enumerate(branches):
        source = branch.get("source")
        if not source:
            raise ValueError(f"Branch {idx + 1} has no source.")
        normalized.append(
            {
                "source": source,
                "transforms": list(branch.get("transforms") or []),
            }
        )
    combine = config.get("combine") or {}
    raw_ops = combine.get("ops")
    if raw_ops is None:
        ops = ["add"] * max(0, len(normalized) - 1)
    else:
        ops = [str(item.get("op")) for item in raw_ops]
        expected = max(0, len(normalized) - 1)
        if len(ops) != expected:
            raise ValueError(f"Pipeline needs {expected} combine operations.")
    return normalized, ops, list(config.get("output_transforms") or [])

def _source_lines(s: dict, ts_var: str, y_var: str) -> list[str]:
    kind = s.get("kind", "signal")

    if kind == "signal":
        name = s["signal_name"]
        return [f"{ts_var}, {y_var} = signal({name!r})"]

    if kind == "bam_extract":
        pgn = s["pgn"]
        start_bit = int(s["start_bit"])
        length = int(s["length"])
        byte_order = s.get("byte_order", "LE")
        return [f"{ts_var}, {y_var} = bam_bits({_pgn(pgn)}, {start_bit}, {length}, byte_order={byte_order!r})"]

    if kind == "bam_chunk_extract":
        pgn = s["pgn"]
        chunk_size = s["chunk_size"]
        start = _start(s)
        n, dtype = _length(s), s["dtype"]
        # Suffix keeps temp-variable names unique when both sources are chunk-extract
        suffix = ts_var[2:] if ts_var.startswith("ts") else ""
        mv = f"_msgs{suffix}"
        tv = f"_ts_out{suffix}"
        yv = f"_y_out{suffix}"
        return [
            f"{mv} = bam_messages(pgn={_pgn(pgn)})",
            f"{tv}, {yv} = [], []",
            f"for _msg in {mv}:",
            f"    for _i in range(0, len(_msg.data), {chunk_size}):",
            f"        _chunk = _msg.data[_i : _i + {chunk_size}]",
            f"        if len(_chunk) == {chunk_size}:",
            f"            {tv}.append(_msg.timestamp)",
            f"            {yv}.append(decode_bytes(_chunk, {start}, {n}, {dtype!r}))",
            f"{ts_var}, {y_var} = np.array({tv}), np.array({yv})",
        ]

    if kind == "raw_extract":
        can_id = s["can_id"]
        start_bit = int(s["start_bit"])
        length = int(s["length"])
        byte_order = s.get("byte_order", "LE")
        mode = s.get("mode", "exact")
        return [f"{ts_var}, {y_var} = raw_bits({_id(can_id)}, {start_bit}, {length}, byte_order={byte_order!r}, mode={mode!r})"]

    if kind == "raw_field":
        return _raw_field_lines(s, ts_var, y_var)

    raise ValueError(f"Unknown source kind: {kind!r}")


def _raw_field_lines(s: dict, ts_var: str, y_var: str) -> list[str]:
    bam = s.get("bam", False)
    start_bit = int(s["start_bit"])
    length = int(s["length"])
    byte_order = s.get("byte_order", "LE")
    type_data = s.get("type_data", "uint")

    mux_args = ""
    mux_start = s.get("mux_start")
    if mux_start is not None:
        mux_bytes = s.get("mux_bytes", 1)
        mux_value = s.get("mux_value", 0)
        mux_args = f", mux_start={int(mux_start)}, mux_bytes={int(mux_bytes)}, mux_value={int(mux_value)}"

    lines: list[str] = []
    if bam:
        pgn = s["pgn"]
        lines.append(
            f"{ts_var}, {y_var} = bam_bits({_pgn(pgn)}, {start_bit}, {length},"
            f" byte_order={byte_order!r}{mux_args})"
        )
    else:
        can_id = s["can_id"]
        mode = s.get("mode", "exact")
        lines.append(
            f"{ts_var}, {y_var} = raw_bits({_id(can_id)}, {start_bit}, {length},"
            f" byte_order={byte_order!r}, mode={mode!r}{mux_args})"
        )

    if type_data == "int":
        lines.append(
            f"{y_var} = np.where({y_var} >= 2**{length - 1},"
            f" {y_var} - 2**{length}, {y_var})"
        )
    elif type_data == "float32":
        lines.append(
            f"{y_var} = {y_var}.astype(np.uint32).view(np.float32).astype(np.float64)"
        )

    return lines


def _combine_line(op: str, left_var: str, right_var: str) -> str:
    if op in _COMBINE_SYM:
        return f"{left_var} = {left_var} {_COMBINE_SYM[op]} {right_var}"
    if op == "max":
        return f"{left_var} = np.maximum({left_var}, {right_var})"
    if op == "min":
        return f"{left_var} = np.minimum({left_var}, {right_var})"
    raise ValueError(f"Unknown combine op: {op!r}")


# ---------------------------------------------------------------------------
# Transform code generators
# ---------------------------------------------------------------------------

def _transform_line(t: dict, y_var: str = "y") -> str:
    op = t.get("op")

    if op == "scale":
        return f"{y_var} = {y_var} * {t['value']!r}"

    if op == "offset":
        return f"{y_var} = {y_var} + {t['value']!r}"

    if op == "abs":
        return f"{y_var} = np.abs({y_var})"

    if op == "clamp":
        return f"{y_var} = np.clip({y_var}, {t['min']!r}, {t['max']!r})"

    if op == "conditional":
        cmp_op = t["cmp"]
        thresh = t["threshold"]
        true_expr = _lin_expr(t.get("true_scale", 1.0), t.get("true_offset", 0.0), y_var)
        false_expr = _lin_expr(t.get("false_scale", 1.0), t.get("false_offset", 0.0), y_var)
        return f"{y_var} = np.where({y_var} {cmp_op} {thresh!r}, {true_expr}, {false_expr})"

    if op == "math":
        fn = t["fn"]
        np_fn = _MATH_FN_MAP.get(fn)
        if np_fn is None:
            raise ValueError(f"Unknown math function: {fn!r}. Valid: {sorted(_MATH_FN_MAP)}")
        return f"{y_var} = {np_fn}({y_var})"

    if op == "round":
        return f"{y_var} = np.round({y_var}, {t.get('decimals', 2)!r})"

    raise ValueError(f"Unknown transform op: {op!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lin_expr(scale: float, offset_val: float, y_var: str = "y") -> str:
    """Compact linear expression for the conditional transform true/false arms."""
    if scale == 1.0 and offset_val == 0.0:
        return y_var
    if offset_val == 0.0:
        return f"{y_var} * {scale!r}"
    if scale == 1.0:
        return f"{y_var} + {offset_val!r}"
    return f"{y_var} * {scale!r} + {offset_val!r}"


def _pgn(pgn: int) -> str:
    return hex(pgn) if pgn >= 256 else str(pgn)


def _id(can_id: int) -> str:
    return hex(can_id) if can_id > 0 else str(can_id)


def _branch_suffix(index: int) -> str:
    if 0 <= index < 26:
        return chr(ord("a") + index)
    return f"s{index + 1}"


def _start(source: dict) -> int:
    return int(source["start"])


def _length(source: dict) -> int:
    return int(source["len"])
