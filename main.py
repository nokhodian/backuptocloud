# main.py
import sys
import os
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow
from ui.tray import TrayIcon


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BackupSystem")
    app.setQuitOnLastWindowClosed(False)  # keep alive when window is hidden

    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    icon = QIcon(icon_path)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Error", "System tray is not available on this desktop.")
        sys.exit(1)

    window = MainWindow()
    window.setWindowIcon(icon)

    tray = TrayIcon(icon, window, parent=app)
    tray.setToolTip("BackupSystem")
    tray.show()

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
