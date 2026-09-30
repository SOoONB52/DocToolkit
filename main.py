"""DocToolkit entry point."""
import os
import sys

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DocToolkit")
    app.setStyle("Fusion")

    from app.ui.startup_dialog import StartupDialog
    if not StartupDialog().exec():
        return 0

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    code = app.exec()
    if window.jobs_still_running:
        # A background job (for example one long OCR image) didn't stop in time.
        # Exit right away instead of letting Qt crash while tidying it up.
        if sys.stdout:  # None in the .exe (no console)
            sys.stdout.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
