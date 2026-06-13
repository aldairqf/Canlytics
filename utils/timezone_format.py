from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
