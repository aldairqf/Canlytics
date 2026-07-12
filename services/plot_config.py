"""Pure (de)serialization helpers for plot .conf files.

Was viewmodels/plot_viewmodel.py's config version-migration (v1/v2+) and MUX
value parsing/validation -- Qt-free domain logic that doesn't need a running
application to test. PlotViewModel keeps: unique-name resolution (needs its
live in-memory state), QColor (de)serialization (_common_style_dict/
_common_style_kwargs, a genuine Qt-adapter concern), and internal_id/storage
bookkeeping.
"""

from __future__ import annotations

from models.derived_signal import DerivedSignal
from models.frame_selector import FrameSelector
from models.signal import Signal


def maybe_int(value) -> int | None:
    """Permissive int parse for values already written by a previous save --
    no validation, just tolerates None/garbage from a hand-edited .conf."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_signal_from_dict(data: dict, *, name: str) -> Signal:
    """Build a Signal from a .conf "signal" dict (v2+) or a flat v1 item --
    both use the same field names, just at different nesting."""
    return Signal(
        name=name,
        can_id=data.get("can_id"),
        start_bit=int(data.get("start_bit", 0)),
        length=int(data.get("length", 8)),
        le=bool(data.get("le", True)),
        scale=float(data.get("scale", 1.0)),
        offset=float(data.get("offset", 0.0)),
        mux_start=int(data.get("mux_start", 0)),
        mux_bytes=int(data.get("mux_bytes", 0)),
        mux_value=maybe_int(data.get("mux_value", None)),
        type_data=str(data.get("type_data", "uint")),
    )


def build_selector_from_v2_dict(sel_data: dict, *, fallback_can_id) -> FrameSelector:
    return FrameSelector(
        selected_id=sel_data.get("selected_id") or fallback_can_id,
        mode=sel_data.get("mode", "exact"),
        pgn=sel_data.get("pgn"),
        target_id=sel_data.get("target_id"),
    )


def build_selector_from_v1_dict(item: dict, *, can_id) -> FrameSelector:
    mode = item.get("id_match", "exact")
    return FrameSelector(
        selected_id=can_id,
        mode=mode if mode in ("exact", "j1939", "bam") else "exact",
        pgn=item.get("pgn"),
        target_id=None,
    )


def build_derived_signal_from_dict(item: dict, *, name: str) -> DerivedSignal:
    return DerivedSignal(
        name=name,
        formula=item.get("formula", ""),
        inputs=list(item.get("inputs", [])),
        simple_config=item.get("simple_config"),
    )


def parse_signal_data(data: dict) -> dict:
    """Normalize a signal definition coming from elsewhere in the app (Signal
    Coverage row, Candidate Interpretations row, either the nested v2+
    signal/selector shape or a flat legacy shape) into a canonical
    {"signal": {...}, "selector": {...}} dict, parsing/validating a
    hex/decimal/octal MUX value along the way."""
    if "signal" in data or "selector" in data:
        signal_data = dict(data.get("signal") or {})
        selector_data = dict(data.get("selector") or {})
    else:
        signal_data = {
            "name": data.get("name", ""),
            "can_id": data.get("can_id") or data.get("can_id"),
            "start_bit": data.get("start_bit", 0),
            "length": data.get("length", 8),
            "le": data.get("le", True),
            "scale": data.get("scale", 1.0),
            "offset": data.get("offset", 0.0),
            "mux_start": data.get("mux_start", 0),
            "mux_bytes": data.get("mux_bytes", 0),
            "mux_value": data.get("mux_value", None),
            "type_data": data.get("type_data", "uint"),
        }
        selector_data = {
            "selected_id": data.get("can_id"),
            "mode": data.get("id_match", "exact"),
            "pgn": data.get("pgn"),
            "target_id": None,
        }

    mux_text = str(signal_data.get("mux_value") or "").strip()
    mux_bytes = int(signal_data.get("mux_bytes", 0))

    try:
        mux_value = int(mux_text, 0) if mux_text else None
    except ValueError:
        mux_value = None

    if mux_value is not None and mux_bytes > 0:
        max_value = (1 << (mux_bytes * 8)) - 1
        if mux_value > max_value:
            raise ValueError(f"MUX value {mux_value} no cabe en {mux_bytes} bytes")

    signal_data["mux_value"] = mux_value
    signal_data.setdefault("type_data", "uint")
    signal_data.setdefault("can_id", None)

    selector_data.setdefault("selected_id", signal_data.get("can_id"))
    selector_data.setdefault("mode", "exact")
    selector_data.setdefault("pgn", None)
    selector_data.setdefault("target_id", None)

    return {"signal": signal_data, "selector": selector_data}
