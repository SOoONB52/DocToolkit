"""Run slow work (OCR, PDF extraction) in a background thread.

Only one job runs at a time. That keeps the window responsive and also
respects PDFium's rule that it must not be used from two threads at once.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class Job(QObject):
    progress = Signal(int, int, str)   # done, total, current item name
    item_done = Signal(object)         # one finished item (e.g. label + text)
    finished = Signal(object)          # final result
    failed = Signal(object)            # the exception

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
        except Exception as exc:  # reported to the UI, never crashes the app
            self.failed.emit(exc)
        else:
            self.finished.emit(result)


def stop_job(job: Job | None, thread: QThread | None, wait_ms: int = 5000) -> bool:
    """Ask a job to stop and wait for it. Returns False if it is still running
    (for example one long OCR image), so the app can exit without waiting."""
    if job is not None:
        job.cancel()
    if thread is None:
        return True
    try:
        thread.quit()
        return bool(thread.wait(wait_ms))
    except RuntimeError:  # Qt already deleted the finished thread
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
