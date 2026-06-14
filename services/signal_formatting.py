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
