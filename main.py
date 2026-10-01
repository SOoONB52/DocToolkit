import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import ICON_ICO


def main() -> int:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TariqAlanazi.DocToolkit")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_ICO)))
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
        if sys.stdout:
            sys.stdout.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
