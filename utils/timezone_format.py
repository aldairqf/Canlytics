from __future__ import annotations

import math
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def format_timestamp(value: float, tz_mode: str | None) -> str:
    """Format a unix timestamp for display on the time axis.

    Returns ``HH:MM:SS`` in the requested timezone, or a decimal-seconds
    string (``"{value:.2f}"``) when *tz_mode* is ``None`` or ``"none"``.
    Falls back to UTC for unrecognised zone names.  Returns ``""`` for
    non-finite inputs.
    """
    try:
        v = float(value)
        if not math.isfinite(v):
            return ""
    except Exception:
        return ""

    if tz_mode in (None, "none"):
        return f"{v:.2f}"

    if tz_mode == "UTC":
        tz = dt_timezone.utc
    else:
        try:
            tz = ZoneInfo(tz_mode)
        except ZoneInfoNotFoundError:
            tz = dt_timezone.utc

    try:
        dt = datetime.fromtimestamp(v, dt_timezone.utc).astimezone(tz)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ""


def format_timezone_label(tz: str) -> str:
    """Render a timezone name with its current UTC offset, e.g. ``America/Lima (UTC-05:00)``.

    Returns the raw name unchanged when the zone is unknown or has no offset.
    """
    if tz == "UTC":
        return "UTC (UTC+00:00)"

    try:
        offset = datetime.now(ZoneInfo(tz)).utcoffset()
    except ZoneInfoNotFoundError:
        return tz

    if offset is None:
        return tz

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_minutes = abs(total_minutes)
    hours, minutes = divmod(abs_minutes, 60)
    return f"{tz} (UTC{sign}{hours:02d}:{minutes:02d})"
