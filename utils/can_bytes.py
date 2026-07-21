from __future__ import annotations


def parse_hex_bytes(data_hex) -> bytes:
    """Convert a CAN payload hex string into bytes.

    Odd-length strings are right-padded with a trailing ``0`` nibble; empty or
    malformed input yields ``b""`` instead of raising.
    """
    text = str(data_hex or "")
    if len(text) % 2 == 1:
        text = text + "0"
    if not text:
        return b""
    try:
        return bytes.fromhex(text)
    except ValueError:
        return b""


def byte_value_to_hex(value: int | None) -> str:
    """Render a single byte value (0-255) as 2-digit uppercase hex; ``None`` -> "".

    Explicit ``is None`` check (not a truthy `or ""` fallback) so a legitimate
    zero byte renders as "00" instead of being mistaken for "missing".
    """
    if value is None:
        return ""
    return f"{int(value):02X}"
