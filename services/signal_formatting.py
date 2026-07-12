from __future__ import annotations


def format_signal_value(value) -> str:
    """Render a decoded signal value: trim trailing zeros on floats, str() otherwise."""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def normalize_display_text(value) -> str | None:
    """Clean DBC-sourced text: normalize NBSP and repair common latin-1/utf-8 mojibake."""
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    if "Â" in text or "Ã" in text:
        try:
            text = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            pass
    return text


def format_data_bytes(data_hex: str, *, as_bits: bool = False) -> str:
    """Render a DATA hex string as space-separated bytes ("AA BB CC") or, with
    as_bits, as space-separated 8-bit binary groups."""
    text = (data_hex or "").strip().upper()
    if not text:
        return ""
    if len(text) % 2 != 0:
        return text
    if as_bits:
        return " ".join(f"{int(text[i : i + 2], 16):08b}" for i in range(0, len(text), 2))
    return " ".join(text[i : i + 2] for i in range(0, len(text), 2))


def build_decode_display_lines(items: list[dict]) -> tuple[str, list[int]]:
    """Turn decoded signal items (each a dict with name/value/unit) into the
    multi-line text shown under an expanded table row, plus a line_map (each
    line's index into ``items``) so a view can map a clicked line back to its
    item."""
    lines = []
    line_map = []
    for idx, item in enumerate(items):
        unit = item.get("unit")
        suffix = f" {unit}" if unit else ""
        lines.append(f"{item['name']}: {item['value']}{suffix}")
        line_map.append(idx)
    return "\n".join(lines), line_map
