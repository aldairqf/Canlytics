from __future__ import annotations

import re


_LEGACY_LABEL = re.compile(
    r"^ID:\s*([0-9A-Fa-f]+)\s+LEN:\s*(\d+)\s+MUX:.+?\s+"
    r"startBit:\s*(\d+)\s+sigLen:\s*(\d+)\s+\S+\s+(LE|BE|LittleEndian|BigEndian)$"
)


def legacy_candidate_tag_to_signal(label: str, name: str) -> dict[str, object] | None:
    """Convert an old Candidate label/tag pair to Save as signal parameters."""
    match = _LEGACY_LABEL.match(str(label))
    original_name = str(name).strip()
    signal_name = re.sub(r"[^A-Za-z0-9_]", "_", original_name)
    if signal_name and signal_name[0].isdigit():
        signal_name = f"_{signal_name}"
    if match is None or not signal_name:
        return None
    can_id, frame_length, start, length, byte_order = match.groups()
    return {
        "can_id": can_id,
        "message_length": int(frame_length),
        "signal_name": signal_name,
        "start": int(start),
        "length": int(length),
        "byte_order": "little_endian" if byte_order in ("LE", "LittleEndian") else "big_endian",
        "is_signed": False,
        "scale": 1.0,
        "offset": 0.0,
        "comment": f"Migrated Candidate tag: {label}",
    }
