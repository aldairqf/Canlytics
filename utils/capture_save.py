from __future__ import annotations

from collections.abc import Callable
from typing import Any


def save_capture_sequence(
    data_vm: Any,
    choose_path: Callable[[], str],
    write_snapshot: Callable[[str, Any], None],
    *,
    stop_capture: Callable[[], None] | None = None,
) -> str:
    """Choose a destination, then synchronously flush, snapshot, write, and mark saved."""
    path = choose_path()
    if not path:
        return ""
    if stop_capture is not None:
        stop_capture()
    data_vm.flush_pending()
    snapshot = data_vm.df
    if snapshot is None or snapshot.is_empty():
        raise ValueError("No CAN data to save")
    write_snapshot(path, snapshot)
    data_vm.mark_capture_saved()
    return path
