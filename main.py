# main.py
import sys
import os
import logging
from logging.handlers import RotatingFileHandler
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from PyQt6.QtGui import QIcon

from version import __version__
from ui.main_window import MainWindow
from ui.tray import TrayIcon


def _setup_logging() -> None:
    log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "BackupSystem")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "backupsystem.log")
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("BackupSystem")
    app.setQuitOnLastWindowClosed(False)  # keep alive when window is hidden

    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    icon = QIcon(icon_path)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Error", "System tray is not available on this desktop.")
        sys.exit(1)

    window = MainWindow(__version__)
    window.setWindowIcon(icon)

    tray = TrayIcon(icon, window, parent=app)
    tray.setToolTip("BackupSystem")
    tray.show()

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
