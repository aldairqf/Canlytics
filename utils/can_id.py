from __future__ import annotations


def can_id_to_int(raw_id) -> int:
    """Parse a CAN frame ID hex string (e.g. ``"18FEF100"``) into an int.

    Raises ``ValueError`` on malformed input, matching ``int(..., 16)``; callers
    that need a fallback should wrap this in ``try/except``.
    """
    return int(str(raw_id), 16)


def can_id_to_int_or_none(raw_id) -> int | None:
    """Same parse as can_id_to_int, but returns None instead of raising on
    empty/malformed input -- for callers that want a tolerant one-liner
    instead of wrapping can_id_to_int in their own try/except."""
    if not raw_id:
        return None
    try:
        return int(str(raw_id), 16)
    except (TypeError, ValueError):
        return None


def can_id_sort_key(value: str) -> tuple[int, int | str]:
    """Sort key that orders CAN IDs numerically, pushing non-hex values to the end."""
    text = str(value or "").strip().upper()
    try:
        return (0, int(text, 16))
    except ValueError:
        return (1, text)
