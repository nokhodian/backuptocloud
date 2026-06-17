# ui/tray.py
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSignal


class TrayIcon(QSystemTrayIcon):
    def __init__(self, icon: QIcon, main_window, parent: QObject = None):
        super().__init__(icon, parent)
        self._main_window = main_window
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        menu = QMenu()

        open_action = menu.addAction("Open")
        open_action.triggered.connect(self._show_window)

        backup_action = menu.addAction("Backup Now")
        backup_action.triggered.connect(self._main_window._on_backup_now)

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_quit)

        self.setContextMenu(menu)

    def _show_window(self):
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _on_quit(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
