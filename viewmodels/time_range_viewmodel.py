from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal as QtSignal


_DEFAULT_FILTER_STATE = {"ts_from": "", "ts_to": "", "date_from": "", "date_to": ""}


class TimeRangeViewModel(QObject):
    range_changed = QtSignal(object, object)
    filter_state_changed = QtSignal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._start: float | None = None
        self._end: float | None = None
        self._filter_state = dict(_DEFAULT_FILTER_STATE)

    @property
    def time_range(self) -> tuple[float | None, float | None]:
        return self._start, self._end

    @property
    def filter_state(self) -> dict[str, str]:
        return dict(self._filter_state)

    def set_time_range(
        self,
        start: float | None,
        end: float | None,
        *,
        filter_state: dict[str, str] | None = None,
    ) -> None:
        normalized = (self._finite_or_none(start), self._finite_or_none(end))
        if normalized[0] is not None and normalized[1] is not None and normalized[0] > normalized[1]:
            raise ValueError("time range start must be less than or equal to its end")
        new_state = self._normalize_filter_state(filter_state) if filter_state is not None else {
            "ts_from": "" if normalized[0] is None else str(normalized[0]),
            "ts_to": "" if normalized[1] is None else str(normalized[1]),
            "date_from": "",
            "date_to": "",
        }
        range_changed = normalized != self.time_range
        state_changed = new_state != self._filter_state
        self._start, self._end = normalized
        self._filter_state = new_state
        if state_changed:
            self.filter_state_changed.emit(self.filter_state)
        if range_changed:
            self.range_changed.emit(*self.time_range)

    @staticmethod
    def _finite_or_none(value: float | None) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("time range limits must be finite")
        return number

    @staticmethod
    def _normalize_filter_state(state: dict[str, str]) -> dict[str, str]:
        return {key: str(state.get(key, "") or "") for key in _DEFAULT_FILTER_STATE}
