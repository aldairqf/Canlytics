from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal
import polars as pl

from models.bit_track import BitTrack
from services.state_tracker import BitStateAccumulator


class StateTrackerViewModel(QObject):
    tracks_changed = QtSignal(object)
    track_data_changed = QtSignal(object)
    transitions_appended = QtSignal(object)
    latest_timestamp_changed = QtSignal(object)

    def __init__(self, dataframe: pl.DataFrame | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dataframe = dataframe if dataframe is not None else pl.DataFrame()
        self._tracks: dict[BitTrack, BitStateAccumulator] = {}
        self._latest_timestamp = self._latest_from(self._dataframe)
        self._can_ids = self._ids_from(self._dataframe)

    @property
    def tracks(self) -> tuple[BitTrack, ...]:
        return tuple(self._tracks)

    @property
    def latest_timestamp(self) -> float | None:
        return self._latest_timestamp

    @property
    def available_can_ids(self) -> tuple[str, ...]:
        return self._can_ids

    def add_track(self, can_id: str, byte_index: int, bit_index: int) -> bool:
        track = BitTrack(str(can_id).strip().upper().removesuffix("X"), int(byte_index), int(bit_index))
        if not track.can_id or not 0 <= track.byte_index <= 7 or not 0 <= track.bit_index <= 7:
            return False
        if track in self._tracks:
            return False
        accumulator = BitStateAccumulator(track)
        accumulator.reset(self._dataframe)
        self._tracks[track] = accumulator
        self.tracks_changed.emit(self.tracks)
        self.track_data_changed.emit(track)
        self.latest_timestamp_changed.emit(self._latest_timestamp)
        return True

    def remove_track(self, track: BitTrack) -> None:
        if self._tracks.pop(track, None) is not None:
            self.tracks_changed.emit(self.tracks)

    def track_data(self, track: BitTrack) -> tuple[list[float], list[int]]:
        accumulator = self._tracks.get(track)
        return accumulator.snapshot() if accumulator else ([], [])

    def set_dataframe(self, dataframe: pl.DataFrame) -> None:
        """Keep the latest history by reference for tracks added later."""
        if dataframe is not None:
            self._dataframe = dataframe

    def append_rows(self, dataframe: pl.DataFrame, new_ids: object = None) -> None:
        if dataframe is None or dataframe.is_empty():
            return
        changed_tracks: dict[BitTrack, list[tuple[float, int]]] = {}
        if "TS" in dataframe.columns:
            latest = dataframe.get_column("TS").max()
            if latest is not None:
                self._latest_timestamp = max(
                    self._latest_timestamp if self._latest_timestamp is not None else float(latest),
                    float(latest),
                )
        if new_ids:
            self._can_ids = tuple(sorted(set(self._can_ids).union(str(can_id) for can_id in new_ids)))
        for track, accumulator in self._tracks.items():
            transitions = accumulator.append(dataframe)
            if transitions:
                changed_tracks[track] = transitions
        if changed_tracks:
            self.transitions_appended.emit(changed_tracks)
        self.latest_timestamp_changed.emit(self._latest_timestamp)

    def reset_dataframe(self, dataframe: pl.DataFrame) -> None:
        self._dataframe = dataframe if dataframe is not None else pl.DataFrame()
        self._latest_timestamp = self._latest_from(self._dataframe)
        self._can_ids = self._ids_from(self._dataframe)
        for track, accumulator in self._tracks.items():
            accumulator.reset(self._dataframe)
        self.tracks_changed.emit(self.tracks)
        for track in self._tracks:
            self.track_data_changed.emit(track)
        self.latest_timestamp_changed.emit(self._latest_timestamp)

    @staticmethod
    def _latest_from(dataframe: pl.DataFrame) -> float | None:
        if "TS" not in dataframe.columns or dataframe.is_empty():
            return None
        latest = dataframe.get_column("TS").max()
        return float(latest) if latest is not None else None

    @staticmethod
    def _ids_from(dataframe: pl.DataFrame) -> tuple[str, ...]:
        if "ID" not in dataframe.columns or dataframe.is_empty():
            return ()
        return tuple(sorted(str(can_id) for can_id in dataframe.get_column("ID").unique().to_list()))
