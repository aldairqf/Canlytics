from __future__ import annotations

import numpy as np


class FormulaError(Exception):
    """Raised when a derived-signal formula fails to evaluate."""


def evaluate(
    formula: str,
    context: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Execute a derived-signal formula and return ``(ts, y)``.

    The formula is a Python script executed in a restricted sandbox.  It must
    assign ``result`` to either:
      - a ``(ts_array, y_array)`` tuple, or
      - a single array ``y_array`` (timestamps will be empty — use only when
        the formula relies solely on ``signal()`` with a common time axis).

    Parameters
    ----------
    formula:
        Multi-line Python script.  Only the names in ``context`` are available;
        ``__builtins__`` is empty (no ``import``, no ``open``, no ``exec``).
    context:
        Namespace dict as returned by ``build_formula_context()``.

    Raises
    ------
    FormulaError
        If the script raises an exception, ``result`` is missing, or the
        result has an unexpected shape.
    """
    if not formula or not formula.strip():
        raise FormulaError("Formula is empty.")

    ns: dict = dict(context)

    try:
        exec(compile(formula, "<formula>", "exec"), ns)  # noqa: S102
    except Exception as exc:
        raise FormulaError(f"Error in formula: {exc}") from exc

    if "result" not in ns:
        raise FormulaError(
            "Formula did not assign 'result'. "
            "End your formula with:  result = (ts_array, y_array)"
        )

    raw = ns["result"]

    # Normalize to (ts, y) pair of 1-D numpy arrays
    try:
        if isinstance(raw, tuple) and len(raw) == 2:
            ts = np.asarray(raw[0], dtype=float).ravel()
            y = np.asarray(raw[1], dtype=float).ravel()
        else:
            # Single array — no explicit timestamps
            ts = np.array([], dtype=float)
            y = np.asarray(raw, dtype=float).ravel()
    except Exception as exc:
        raise FormulaError(
            f"'result' could not be converted to (ts, y) arrays: {exc}"
        ) from exc

    if len(ts) > 0 and len(ts) != len(y):
        raise FormulaError(
            f"Timestamp array length ({len(ts)}) differs from "
            f"value array length ({len(y)})."
        )

    return ts, y
