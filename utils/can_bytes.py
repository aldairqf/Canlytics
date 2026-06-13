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
