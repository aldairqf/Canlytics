from __future__ import annotations

from pathlib import Path
from queue import Queue
from threading import Event, Lock

import polars as pl
from PySide6.QtCore import QObject, QThread, Qt, Signal as QtSignal, Slot

from services.continuous_recorder import ContinuousCandumpRecorder


_STOP = object()


class _ContinuousRecorderWorker(QObject):
    started = QtSignal(str)
    size_changed = QtSignal(int)
    failed = QtSignal(str)
    finished = QtSignal(bool)

    def __init__(self, path: Path, chunks: Queue[object]):
        super().__init__()
        self._path = path
        self._chunks = chunks

    @Slot()
    def run(self) -> None:
        recorder = ContinuousCandumpRecorder(self._path)
        completed = False
        try:
            recorder.start()
            self.started.emit(str(self._path))
            while True:
                chunk = self._chunks.get()
                if chunk is _STOP:
                    completed = True
                    break
                self.size_changed.emit(recorder.write_chunk(chunk))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                recorder.close(completed=completed)
            except Exception as exc:
                self.failed.emit(str(exc))
                completed = False
            self.finished.emit(completed)


class ContinuousRecorderViewModel(QObject):
    recording_started = QtSignal(str)
    size_changed = QtSignal(int)
    recording_stopped = QtSignal(str)
    recording_failed = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _ContinuousRecorderWorker | None = None
        self._chunks: Queue[object] = Queue()
        self._thread_started = Event()
        self._recording_lock = Lock()
        self._path: str | None = None
        self._last_path: str | None = None
        self._recorded_paths: list[str] = []
        self._stopping = False
        self._completed = False

    @property
    def active_path(self) -> str | None:
        return self._path if self._thread is not None and not self._stopping else None

    @property
    def last_path(self) -> str | None:
        return self._last_path

    @property
    def recorded_paths(self) -> tuple[str, ...]:
        return tuple(self._recorded_paths)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_recording(self, path: str | Path) -> bool:
        if self._thread is not None:
            return False
        self._path = str(Path(path))
        self._last_path = self._path
        self._recorded_paths.append(self._path)
        self._stopping = False
        self._completed = False
        self._chunks = Queue()
        self._thread_started = Event()
        thread = QThread(self)
        worker = _ContinuousRecorderWorker(Path(path), self._chunks)
        worker.moveToThread(thread)
        thread.started.connect(self._thread_started.set, Qt.ConnectionType.DirectConnection)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_started)
        worker.size_changed.connect(self.size_changed)
        worker.failed.connect(self.recording_failed)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(self._set_completed, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    def append_chunk(self, dataframe: pl.DataFrame) -> None:
        if dataframe.is_empty():
            return
        with self._recording_lock:
            if self._thread is not None and not self._stopping:
                self._chunks.put(dataframe)

    def stop_recording(self) -> None:
        with self._recording_lock:
            if self._thread is not None and not self._stopping:
                self._stopping = True
                self._chunks.put(_STOP)

    def stop_and_drain(self) -> None:
        self.stop_recording()
        thread = self._thread
        if thread is None:
            return
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        self._thread_started.wait(2.0)
        while thread.isRunning():
            thread.wait(50)
            if app is not None:
                app.processEvents()
        if app is not None:
            app.processEvents()

    def _on_started(self, path: str) -> None:
        self._path = path
        self.recording_started.emit(path)

    @Slot(bool)
    def _set_completed(self, completed: bool) -> None:
        self._completed = completed

    @Slot()
    def _cleanup(self) -> None:
        thread = self.sender()
        path = self._path
        if thread != self._thread:
            return
        with self._recording_lock:
            self._thread = None
            self._worker = None
            self._stopping = False
        if path and self._completed:
            self.recording_stopped.emit(path)
        self._path = None
        self._completed = False
        if isinstance(thread, QThread):
            thread.deleteLater()

    def shutdown(self) -> None:
        self.stop_and_drain()
