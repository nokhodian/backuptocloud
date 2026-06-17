# ui/main_window.py
import sys
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QTime
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QTextEdit, QTimeEdit, QVBoxLayout,
    QWidget, QComboBox,
)

from config.config_manager import load_config, save_config
from core.backup_engine import BackupWorker
from core.storage import IONOSStorage


class _ConnectionTestThread(QThread):
    result = pyqtSignal(bool)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self):
        storage = IONOSStorage(
            self._cfg["ionos_endpoint"],
            self._cfg["ionos_bucket"],
            self._cfg["ionos_access_key"],
            self._cfg["ionos_secret_key"],
        )
        self.result.emit(storage.test_connection())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._config = load_config()
        self._worker: BackupWorker | None = None
        self._next_run: datetime | None = None

        self._setup_ui()
        self._load_config_to_ui()
        self._restart_scheduler()

    # ------------------------------------------------------------------ setup

    def _setup_ui(self):
        self.setWindowTitle("BackupSystem")
        self.setMinimumWidth(640)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(self._build_folders_group())
        layout.addWidget(self._build_credentials_group())
        layout.addWidget(self._build_settings_group())
        layout.addWidget(self._build_status_group())
        layout.addLayout(self._build_buttons_row())

    def _build_folders_group(self) -> QGroupBox:
        box = QGroupBox("Backup Folders")
        layout = QVBoxLayout(box)
        self._folder1_edit, row1 = self._folder_row()
        self._folder2_edit, row2 = self._folder_row()
        layout.addLayout(row1)
        layout.addLayout(row2)
        return box

    def _folder_row(self):
        edit = QLineEdit()
        edit.setPlaceholderText("Click Browse to choose a folder…")
        edit.setReadOnly(True)
        btn = QPushButton("Browse")
        btn.setFixedWidth(80)
        btn.clicked.connect(lambda: self._browse_folder(edit))
        row = QHBoxLayout()
        row.addWidget(edit)
        row.addWidget(btn)
        return edit, row

    def _build_credentials_group(self) -> QGroupBox:
        box = QGroupBox("IONOS Object Storage Credentials")
        layout = QVBoxLayout(box)

        row1 = QHBoxLayout()
        self._endpoint_edit = self._labeled_input(row1, "Endpoint URL", "s3-eu-central-1.ionoscloud.com")
        self._bucket_edit = self._labeled_input(row1, "Bucket Name", "my-backups")

        row2 = QHBoxLayout()
        self._access_key_edit = self._labeled_input(row2, "Access Key", "")
        self._secret_key_edit = self._labeled_input(row2, "Secret Key", "", password=True)

        layout.addLayout(row1)
        layout.addLayout(row2)
        return box

    def _labeled_input(self, parent_layout, label: str, placeholder: str, password=False) -> QLineEdit:
        col = QVBoxLayout()
        col.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        col.addWidget(edit)
        parent_layout.addLayout(col)
        return edit

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Backup Settings")
        layout = QHBoxLayout(box)

        # Schedule
        sched_col = QVBoxLayout()
        sched_col.addWidget(QLabel("Schedule"))
        self._schedule_combo = QComboBox()
        self._schedule_combo.addItems(["Hourly", "Daily", "Weekly"])
        self._schedule_combo.currentTextChanged.connect(self._on_schedule_type_changed)
        sched_col.addWidget(self._schedule_combo)
        layout.addLayout(sched_col)

        # Time
        time_col = QVBoxLayout()
        self._time_label = QLabel("Time (HH:MM)")
        time_col.addWidget(self._time_label)
        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        time_col.addWidget(self._time_edit)
        layout.addLayout(time_col)

        # Retention
        ret_col = QVBoxLayout()
        ret_col.addWidget(QLabel("Keep Last N Backups"))
        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(1, 9999)
        self._retention_spin.setValue(30)
        ret_col.addWidget(self._retention_spin)
        layout.addLayout(ret_col)

        # Password
        pwd_col = QVBoxLayout()
        pwd_col.addWidget(QLabel("Encryption Password"))
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Required for each backup run")
        pwd_col.addWidget(self._password_edit)
        layout.addLayout(pwd_col)

        return box

    def _build_status_group(self) -> QGroupBox:
        box = QGroupBox("Status")
        layout = QVBoxLayout(box)

        self._status_label = QLabel("No backup run yet.")
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setFixedHeight(100)
        self._log_edit.setFontFamily("Courier New")
        layout.addWidget(self._log_edit)

        return box

    def _build_buttons_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._on_test_connection)
        row.addWidget(self._test_btn)

        self._save_btn = QPushButton("Save Settings")
        self._save_btn.clicked.connect(self._on_save)
        row.addWidget(self._save_btn)

        self._backup_btn = QPushButton("▶  Backup Now")
        self._backup_btn.setStyleSheet("QPushButton { background-color: #1d4ed8; color: white; font-weight: bold; padding: 6px 18px; }")
        self._backup_btn.clicked.connect(self._on_backup_now)
        row.addWidget(self._backup_btn)

        return row

    # --------------------------------------------------------- config <-> UI

    def _load_config_to_ui(self):
        self._folder1_edit.setText(self._config.get("folder1", ""))
        self._folder2_edit.setText(self._config.get("folder2", ""))
        self._endpoint_edit.setText(self._config.get("ionos_endpoint", ""))
        self._bucket_edit.setText(self._config.get("ionos_bucket", ""))
        self._access_key_edit.setText(self._config.get("ionos_access_key", ""))
        self._secret_key_edit.setText(self._config.get("ionos_secret_key", ""))
        sched = self._config.get("schedule_type", "daily").capitalize()
        idx = self._schedule_combo.findText(sched)
        if idx >= 0:
            self._schedule_combo.setCurrentIndex(idx)
        t = QTime.fromString(self._config.get("schedule_time", "02:00"), "HH:mm")
        self._time_edit.setTime(t if t.isValid() else QTime(2, 0))
        self._retention_spin.setValue(self._config.get("retention_count", 30))
        self._on_schedule_type_changed(self._schedule_combo.currentText())

    def _collect_config(self) -> dict:
        cfg = dict(self._config)
        cfg["folder1"] = self._folder1_edit.text()
        cfg["folder2"] = self._folder2_edit.text()
        cfg["ionos_endpoint"] = self._endpoint_edit.text().strip()
        cfg["ionos_bucket"] = self._bucket_edit.text().strip()
        cfg["ionos_access_key"] = self._access_key_edit.text().strip()
        cfg["ionos_secret_key"] = self._secret_key_edit.text().strip()
        cfg["schedule_type"] = self._schedule_combo.currentText().lower()
        cfg["schedule_time"] = self._time_edit.time().toString("HH:mm")
        cfg["retention_count"] = self._retention_spin.value()
        return cfg

    # ---------------------------------------------------------------- slots

    def _browse_folder(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            edit.setText(path)

    def _on_schedule_type_changed(self, text: str):
        self._time_edit.setVisible(text in ("Daily", "Weekly"))
        self._time_label.setVisible(text in ("Daily", "Weekly"))

    def _on_save(self):
        self._config = self._collect_config()
        save_config(self._config)
        self._restart_scheduler()
        self._status_label.setText("Settings saved.")

    def _on_test_connection(self):
        cfg = self._collect_config()
        missing = [k for k in ("ionos_endpoint", "ionos_bucket", "ionos_access_key", "ionos_secret_key") if not cfg.get(k)]
        if missing:
            QMessageBox.warning(self, "Missing Fields", f"Please fill in: {', '.join(missing)}")
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Testing…")
        self._conn_thread = _ConnectionTestThread(cfg, parent=self)
        self._conn_thread.result.connect(self._on_connection_result)
        self._conn_thread.start()

    def _on_connection_result(self, ok: bool):
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test Connection")
        if ok:
            QMessageBox.information(self, "Connection OK", "Successfully connected to IONOS bucket.")
        else:
            QMessageBox.critical(self, "Connection Failed", "Could not connect. Check your credentials and endpoint.")

    def _on_backup_now(self):
        if self._worker and self._worker.isRunning():
            return
        if not self._password_edit.text():
            QMessageBox.warning(self, "Password Required", "Enter your encryption password before running a backup.")
            return
        cfg = self._collect_config()
        cfg["password"] = self._password_edit.text()
        self._start_backup(cfg)

    def _start_backup(self, cfg: dict):
        self._backup_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._log_edit.clear()

        self._worker = BackupWorker(cfg, parent=self)
        self._worker.progress.connect(self._progress_bar.setValue)
        self._worker.log_line.connect(self._append_log)
        self._worker.backup_done.connect(self._on_backup_finished)
        self._worker.start()

    def _append_log(self, line: str):
        self._log_edit.append(line)
        self._log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _on_backup_finished(self, success: bool, message: str):
        self._backup_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        icon = "✓" if success else "✗"
        self._status_label.setText(f"{icon} {ts} — {message}")
        self._config["last_run"] = datetime.now().isoformat()
        save_config(self._config)

    # -------------------------------------------------------------- scheduler

    def _restart_scheduler(self):
        if hasattr(self, "_timer"):
            self._timer.stop()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_scheduler_tick)
        self._timer.start(60_000)  # check every minute
        self._compute_next_run()

    def _compute_next_run(self):
        cfg = self._config
        now = datetime.now()
        stype = cfg.get("schedule_type", "daily")
        t_str = cfg.get("schedule_time", "02:00")
        h, m = (int(x) for x in t_str.split(":"))

        if stype == "hourly":
            self._next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif stype == "daily":
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            self._next_run = candidate if candidate > now else candidate + timedelta(days=1)
        elif stype == "weekly":
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            days_ahead = (6 - now.weekday()) % 7  # next Sunday
            self._next_run = candidate + timedelta(days=days_ahead if days_ahead else 7)

    def _on_scheduler_tick(self):
        if self._next_run and datetime.now() >= self._next_run:
            self._compute_next_run()
            if self._worker and self._worker.isRunning():
                self._append_log("Scheduled backup skipped — previous backup still running.")
                return
            if not self._password_edit.text():
                self._append_log("Scheduled backup skipped — password not entered.")
                return
            cfg = self._collect_config()
            cfg["password"] = self._password_edit.text()
            self._start_backup(cfg)

    # -------------------------------------------------------- window lifecycle

    def closeEvent(self, event):
        event.ignore()
        self.hide()
