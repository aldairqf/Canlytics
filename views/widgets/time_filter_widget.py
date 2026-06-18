from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QWidget

from config.app_config import get_text
from config.theme import get_active_theme
from viewmodels.time_config_viewmodel import TimeConfigViewModel


class TimeFilterWidget(QGroupBox):
    range_changed = QtSignal(object, object)

    def __init__(self, time_config_vm: TimeConfigViewModel, title: str | None = None, parent: QWidget | None = None):
        if title is None:
            title = get_text("time_filter_group")
        super().__init__(title, parent)
        self._time_vm = time_config_vm

        self.ts_from = QLineEdit(self)
        self.ts_from.setPlaceholderText(get_text("time_filter_ts_from"))
        self.ts_to = QLineEdit(self)
        self.ts_to.setPlaceholderText(get_text("time_filter_ts_to"))
        self.date_from = QLineEdit(self)
        self.date_from.setPlaceholderText(get_text("time_filter_date_from"))
        self.date_to = QLineEdit(self)
        self.date_to.setPlaceholderText(get_text("time_filter_date_to"))

        ts_row = QHBoxLayout()
        ts_row.addWidget(self.ts_from)
        ts_row.addWidget(self.ts_to)

        date_row = QHBoxLayout()
        date_row.addWidget(self.date_from)
        date_row.addWidget(self.date_to)

        form = QFormLayout(self)
        form.addRow(get_text("time_filter_timestamp_label"), ts_row)
        form.addRow(get_text("time_filter_date_label"), date_row)

        self.ts_from.editingFinished.connect(self._emit_range)
        self.ts_to.editingFinished.connect(self._emit_range)
        self.date_from.editingFinished.connect(self._emit_range)
        self.date_to.editingFinished.connect(self._emit_range)
        self._time_vm.timezone_changed.connect(self._on_timezone_changed)
        self._time_vm.normalize_changed.connect(self._on_normalize_changed)
        self._apply_date_enabled()

    def _emit_range(self) -> None:
        ts_min, ts_max = self.get_range()
        self.range_changed.emit(ts_min, ts_max)

    def get_range(self) -> tuple[float | None, float | None]:
        ts_min = self._merge_lower_bounds(
            self._parse_float(self.ts_from),
            self._parse_date(self.date_from, is_end=False),
        )
        ts_max = self._merge_upper_bounds(
            self._parse_float(self.ts_to),
            self._parse_date(self.date_to, is_end=True),
        )
        return ts_min, ts_max

    def get_state(self) -> dict[str, str]:
        return {
            "ts_from": self.ts_from.text(),
            "ts_to": self.ts_to.text(),
            "date_from": self.date_from.text(),
            "date_to": self.date_to.text(),
        }

    def set_state(self, state: dict[str, str] | None) -> None:
        state = state or {}
        self.ts_from.setText(state.get("ts_from", ""))
        self.ts_to.setText(state.get("ts_to", ""))
        self.date_from.setText(state.get("date_from", ""))
        self.date_to.setText(state.get("date_to", ""))

    def _on_timezone_changed(self, _tz: str) -> None:
        self._apply_date_enabled()
        self._emit_range()

    def _on_normalize_changed(self, _normalize: bool) -> None:
        self._apply_date_enabled()
        self._emit_range()

    def _apply_date_enabled(self) -> None:
        enabled = self._current_zone() is not None
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        tooltip = "" if enabled else get_text("time_filter_date_disabled_tooltip")
        self.date_from.setToolTip(tooltip)
        self.date_to.setToolTip(tooltip)

    def _parse_float(self, field: QLineEdit) -> float | None:
        raw = (field.text() or "").strip()
        if not raw:
            field.setStyleSheet("")
            return None
        try:
            value = float(raw)
        except ValueError:
            field.setStyleSheet(f"border: 1px solid {get_active_theme().error};")
            return None
        field.setStyleSheet("")
        return value

    def _parse_date(self, field: QLineEdit, *, is_end: bool) -> float | None:
        raw = (field.text() or "").strip()
        if not raw:
            field.setStyleSheet("")
            return None

        zone = self._current_zone()
        if zone is None:
            field.setStyleSheet("")
            return None

        dt = _parse_datetime_text(raw, is_end=is_end)
        if dt is None:
            field.setStyleSheet(f"border: 1px solid {get_active_theme().error};")
            return None

        field.setStyleSheet("")
        return dt.replace(tzinfo=zone).timestamp()

    def _current_zone(self):
        tz = (self._time_vm.timezone or "none").strip()
        if tz in ("", "none"):
            return None
        if tz == "UTC":
            return timezone.utc
        try:
            return ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            return None

    @staticmethod
    def _merge_lower_bounds(*values: float | None) -> float | None:
        present = [float(v) for v in values if v is not None]
        return max(present) if present else None

    @staticmethod
    def _merge_upper_bounds(*values: float | None) -> float | None:
        present = [float(v) for v in values if v is not None]
        return min(present) if present else None


def _parse_datetime_text(text: str, *, is_end: bool) -> datetime | None:
    raw = (text or "").strip()
    if not raw:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d" and is_end:
            return dt.replace(hour=23, minute=59, second=59)
        return dt
    return None
