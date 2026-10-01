from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QTabWidget

from app.i18n import tr
from app.ui.about_dialog import AboutDialog
from app.ui.images_tab import ImagesTab
from app.ui.metadata_tab import MetadataTab
from app.ui.ocr_tab import OcrTab
from app.ui.wordcount_tab import WordCountTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DocToolkit")
        self.resize(1150, 720)
        self.jobs_still_running = False

        self.tabs = QTabWidget()
        self.metadata_tab = MetadataTab()
        self.images_tab = ImagesTab()
        self.ocr_tab = OcrTab()
        self.wordcount_tab = WordCountTab()

        self.tabs.addTab(self.metadata_tab, tr("tab_metadata"))
        self.tabs.addTab(self.images_tab, tr("tab_images"))
        self.tabs.addTab(self.ocr_tab, tr("tab_ocr"))
        self.tabs.addTab(self.wordcount_tab, tr("tab_wordcount"))
        self.setCentralWidget(self.tabs)

        help_menu = self.menuBar().addMenu(tr("menu_help"))
        about = QAction(tr("menu_about"), self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

        self.statusBar().showMessage(tr("ready"))

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def closeEvent(self, event) -> None:
        if not self.metadata_tab.confirm_discard(quitting=True):
            event.ignore()
            return
        stopped = [tab.shutdown() for tab in (self.wordcount_tab, self.images_tab, self.ocr_tab)]
        self.jobs_still_running = not all(stopped)
        super().closeEvent(event)
