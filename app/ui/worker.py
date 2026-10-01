from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class Job(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(object)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            result = self._fn(self, *self._args, **self._kwargs)
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.finished.emit(result)


def stop_job(job: Job | None, thread: QThread | None, wait_ms: int = 5000) -> bool:
    if job is not None:
        job.cancel()
    if thread is None:
        return True
    try:
        thread.quit()
        return bool(thread.wait(wait_ms))
    except RuntimeError:
        return True


def start_job(parent: QObject, job: Job) -> QThread:
    thread = QThread(parent)
    job.moveToThread(thread)
    thread.started.connect(job.run)
    job.finished.connect(thread.quit)
    job.failed.connect(thread.quit)
    thread.finished.connect(job.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
