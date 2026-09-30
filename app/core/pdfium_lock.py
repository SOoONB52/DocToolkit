"""PDFium (used through pypdfium2) is not thread-safe.

Several tabs can run background jobs at the same time, so every use of
pypdfium2 goes through this one lock.
"""
import threading

PDFIUM_LOCK = threading.RLock()
