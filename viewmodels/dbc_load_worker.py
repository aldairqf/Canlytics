from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal as QtSignal

from services.dbc_manager import DbcManager
from services.pgn_csv_to_dbc import UnrecognizedCsvOrderError, convert_pgn_csv_to_dbc


class DbcLoadWorker(QObject):
    # (load_path, db, from_csv, display_name, overlaps, csv_order) --
    # display_name is always the ORIGINAL selected file's stem, since for a CSV
    # import load_path points at a generated temp .dbc with a meaningless
    # random name (see run()). overlaps is a list[SignalOverlap] (empty when
    # not from_csv or when the CSV has no overlapping signals) -- overlapping
    # signals are NOT an error (see convert_pgn_csv_to_dbc/build_database_from_rows),
    # just something worth flagging to the user. csv_order is the detected (or
    # forced, see __init__) CSV schema name ("CAI Order"/"DBC Order", see
    # services/pgn_csv_to_dbc.py), or None when not from_csv.
    finished = QtSignal(str, object, bool, str, object, object)
    failed = QtSignal(str, str)
    # (path, display_name) -- raised instead of `failed` specifically when the
    # CSV's columns don't match either known schema, so the caller can offer a
    # manual format picker instead of a dead-end error (see
    # DbcManagerDialog._on_unrecognized_format).
    unrecognized_format = QtSignal(str, str)

    def __init__(self, path: str, *, forced_order: str | None = None):
        super().__init__()
        self._path = path
        self._forced_order = forced_order

    def run(self) -> None:
        source = Path(self._path)
        from_csv = source.suffix.lower() == ".csv"
        load_path = self._path
        generated_path: str | None = None
        overlaps: list = []
        csv_order: str | None = None
        try:
            if from_csv:
                # Write the generated DBC to a temp file rather than next to
                # the source CSV -- writing "<csv_stem>.dbc" alongside it would
                # silently overwrite any existing .dbc that happens to share
                # that stem (plausible in this domain: a PGN map and its
                # already-converted DBC living side by side). The temp file
                # only needs to survive long enough for the caller to load it
                # and let SessionStateStore copy it into .canlytics_state/ --
                # the caller deletes it afterwards (see
                # DbcManagerDialog._on_dbc_loaded).
                fd, generated_path = tempfile.mkstemp(suffix=".dbc")
                os.close(fd)
                _, overlaps, csv_order = convert_pgn_csv_to_dbc(
                    self._path, generated_path, order=self._forced_order
                )
                load_path = generated_path
            db = DbcManager().load_database(load_path)
        except UnrecognizedCsvOrderError:
            if generated_path is not None:
                _silent_remove(generated_path)
            self.unrecognized_format.emit(self._path, source.stem)
            return
        except Exception as exc:
            if generated_path is not None:
                _silent_remove(generated_path)
            self.failed.emit(self._path, str(exc))
            return
        self.finished.emit(load_path, db, from_csv, source.stem, overlaps, csv_order)


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
