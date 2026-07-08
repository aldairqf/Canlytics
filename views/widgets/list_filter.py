from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QLineEdit, QListWidget


def apply_text_filter(
    search_box: QLineEdit,
    list_widget: QListWidget,
    *,
    key: Callable[[object], object] | None = None,
) -> None:
    """Hide items whose text doesn't match search_box (case-insensitive)."""
    needle = (search_box.text() or "").strip().upper()
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        haystack = key(item) if key is not None else item.text()
        item.setHidden(bool(needle) and needle not in str(haystack or "").upper())
