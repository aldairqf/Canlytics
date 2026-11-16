from __future__ import annotations


def format_period_ms(seconds: float | None) -> str:
    """Format a period measured in seconds as milliseconds with three decimals."""
    return "-" if seconds is None else f"{float(seconds) * 1000:.3f}"
