# ui/main_window.py
import os
import sys
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QTime
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QStackedWidget, QTextEdit, QTimeEdit, QVBoxLayout,
    QWidget, QComboBox,
)

from config.config_manager import (
    load_config, save_config,
    load_encryption_password, save_encryption_password,
)
from core.backup_engine import BackupWorker
from core.storage import get_storage
from core.updater import check_for_update, download_update, install_update

# (display_name, config_value, stack_page_index)
_PROVIDERS = [
    ("IONOS Object Storage",  "ionos",        0),
    ("AWS S3",                "aws_s3",        0),
    ("MinIO / Generic S3",    "minio",         0),
    ("Backblaze B2",          "backblaze_b2",  0),
    ("Microsoft OneDrive",    "onedrive",      1),
    ("Google Drive",          "google_drive",  2),
    ("Dropbox",               "dropbox",       3),
    ("Azure Blob Storage",    "azure_blob",    4),
    ("SFTP",                  "sftp",          5),
]
_VALUE_TO_IDX = {v: i for i, (_, v, _pg) in enumerate(_PROVIDERS)}


class _ConnectionTestThread(QThread):
    result = pyqtSignal(bool)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self):
        try:
            storage = get_storage(self._cfg)
            self.result.emit(storage.test_connection())
        except Exception:
            self.result.emit(False)


class _UpdateCheckThread(QThread):
    update_available = pyqtSignal(str, str, str)
    no_update = pyqtSignal()

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        latest, url, checksum_url = check_for_update(self._current_version)
        if latest:
            self.update_available.emit(latest, url, checksum_url or "")
        else:
            self.no_update.emit()


class _UpdateDownloadThread(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(str)

    def __init__(self, download_url: str, checksum_url: str = "", parent=None):
        super().__init__(parent)
        self._url = download_url
        self._checksum_url = checksum_url or None

    def run(self):
        def _cb(downloaded, total):
            self.progress.emit(int(downloaded * 100 / total))

        path = download_update(self._url, checksum_url=self._checksum_url,
                               progress_cb=_cb, worker=self)
        self.done.emit(path or "")


class MainWindow(QMainWindow):
    def __init__(self, version: str = "0.0.0"):
        super().__init__()
        self._version = version
        self._config = load_config()
        self._worker: BackupWorker | None = None
        self._next_run: datetime | None = None
        self._update_exe_path: str | None = None

        self._setup_ui()
        self._load_config_to_ui()
        self._restart_scheduler()
        self._check_for_updates_silently()

    # ------------------------------------------------------------------ setup

    def _setup_ui(self):
        self.setWindowTitle(f"BackupSystem v{self._version}")
        self.setMinimumWidth(700)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(self._build_folders_group())
        layout.addWidget(self._build_storage_group())
        layout.addWidget(self._build_settings_group())
        layout.addWidget(self._build_status_group())
        layout.addLayout(self._build_buttons_row())

    def _build_folders_group(self) -> QGroupBox:
        box = QGroupBox("Backup Folders")
        layout = QVBoxLayout(box)

        self._folders_list = QListWidget()
        self._folders_list.setFixedHeight(100)
        self._folders_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(self._folders_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Folder")
        add_btn.clicked.connect(self._on_add_folder)
        remove_btn = QPushButton("− Remove Selected")
        remove_btn.clicked.connect(self._on_remove_folder)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return box

    # ------------------------------------------------------------------ storage group

    def _build_storage_group(self) -> QGroupBox:
        box = QGroupBox("Cloud Storage")
        layout = QVBoxLayout(box)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        for display, _val, _pg in _PROVIDERS:
            self._provider_combo.addItem(display)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self._provider_combo)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        self._storage_stack = QStackedWidget()
        self._storage_stack.addWidget(self._build_s3_page())       # 0
        self._storage_stack.addWidget(self._build_onedrive_page())  # 1
        self._storage_stack.addWidget(self._build_gdrive_page())    # 2
        self._storage_stack.addWidget(self._build_dropbox_page())   # 3
        self._storage_stack.addWidget(self._build_azure_page())     # 4
        self._storage_stack.addWidget(self._build_sftp_page())      # 5
        layout.addWidget(self._storage_stack)

        return box

    # -- S3-compatible page (IONOS / AWS S3 / MinIO / Backblaze B2) ----------

    def _build_s3_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        ep_col = QVBoxLayout()
        self._s3_endpoint_label = QLabel("Endpoint")
        ep_col.addWidget(self._s3_endpoint_label)
        self._s3_endpoint_edit = QLineEdit()
        self._s3_endpoint_edit.setPlaceholderText("s3-eu-central-1.ionoscloud.com")
        ep_col.addWidget(self._s3_endpoint_edit)
        row1.addLayout(ep_col)

        region_col = QVBoxLayout()
        self._s3_region_label = QLabel("Region")
        region_col.addWidget(self._s3_region_label)
        self._s3_region_edit = QLineEdit()
        self._s3_region_edit.setPlaceholderText("us-east-1")
        region_col.addWidget(self._s3_region_edit)
        row1.addLayout(region_col)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        bucket_col = QVBoxLayout()
        bucket_col.addWidget(QLabel("Bucket Name"))
        self._s3_bucket_edit = QLineEdit()
        self._s3_bucket_edit.setPlaceholderText("my-backups")
        bucket_col.addWidget(self._s3_bucket_edit)
        row2.addLayout(bucket_col)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        key_col = QVBoxLayout()
        key_col.addWidget(QLabel("Access Key"))
        self._s3_access_key_edit = QLineEdit()
        key_col.addWidget(self._s3_access_key_edit)
        row3.addLayout(key_col)

        secret_col = QVBoxLayout()
        secret_col.addWidget(QLabel("Secret Key"))
        self._s3_secret_key_edit = QLineEdit()
        self._s3_secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        secret_col.addWidget(self._s3_secret_key_edit)
        row3.addLayout(secret_col)
        layout.addLayout(row3)

        return page

    # -- OneDrive page --------------------------------------------------------

    def _build_onedrive_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        folder_col = QVBoxLayout()
        folder_col.addWidget(QLabel("Backup Folder (OneDrive path)"))
        self._onedrive_folder_edit = QLineEdit()
        self._onedrive_folder_edit.setPlaceholderText("BackupSystem")
        folder_col.addWidget(self._onedrive_folder_edit)
        row1.addLayout(folder_col)
        layout.addLayout(row1)

        token_col = QVBoxLayout()
        token_col.addWidget(QLabel("Access Token"))
        self._onedrive_token_edit = QLineEdit()
        self._onedrive_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._onedrive_token_edit.setPlaceholderText(
            "Paste a Microsoft Graph API access token (Files.ReadWrite scope)"
        )
        token_col.addWidget(self._onedrive_token_edit)
        hint = QLabel(
            '<a href="https://learn.microsoft.com/en-us/graph/auth-v2-user">'
            "How to obtain a token</a>"
        )
        hint.setOpenExternalLinks(True)
        token_col.addWidget(hint)
        layout.addLayout(token_col)

        return page

    # -- Google Drive page ----------------------------------------------------

    def _build_gdrive_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        folder_col = QVBoxLayout()
        folder_col.addWidget(QLabel("Backup Folder Name"))
        self._gdrive_folder_edit = QLineEdit()
        self._gdrive_folder_edit.setPlaceholderText("BackupSystem")
        folder_col.addWidget(self._gdrive_folder_edit)
        row1.addLayout(folder_col)
        layout.addLayout(row1)

        creds_col = QVBoxLayout()
        creds_col.addWidget(QLabel("OAuth Credentials JSON"))
        self._gdrive_creds_edit = QTextEdit()
        self._gdrive_creds_edit.setFixedHeight(90)
        self._gdrive_creds_edit.setPlaceholderText(
            '{"access_token":"...","refresh_token":"...","client_id":"...","client_secret":"..."}'
        )
        creds_col.addWidget(self._gdrive_creds_edit)
        hint = QLabel(
            '<a href="https://developers.google.com/drive/api/quickstart/python">'
            "How to create OAuth credentials</a>"
        )
        hint.setOpenExternalLinks(True)
        creds_col.addWidget(hint)
        layout.addLayout(creds_col)

        return page

    # -- Dropbox page ---------------------------------------------------------

    def _build_dropbox_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        token_col = QVBoxLayout()
        token_col.addWidget(QLabel("Access Token"))
        self._dropbox_token_edit = QLineEdit()
        self._dropbox_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._dropbox_token_edit.setPlaceholderText("Dropbox long-lived or short-lived access token")
        token_col.addWidget(self._dropbox_token_edit)
        row1.addLayout(token_col)

        folder_col = QVBoxLayout()
        folder_col.addWidget(QLabel("Backup Folder Path"))
        self._dropbox_folder_edit = QLineEdit()
        self._dropbox_folder_edit.setPlaceholderText("/BackupSystem")
        folder_col.addWidget(self._dropbox_folder_edit)
        row1.addLayout(folder_col)
        layout.addLayout(row1)

        hint = QLabel(
            '<a href="https://www.dropbox.com/developers/apps">'
            "Get a token from the Dropbox App Console</a>"
        )
        hint.setOpenExternalLinks(True)
        layout.addWidget(hint)

        return page

    # -- Azure Blob page ------------------------------------------------------

    def _build_azure_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        container_col = QVBoxLayout()
        container_col.addWidget(QLabel("Container Name"))
        self._azure_container_edit = QLineEdit()
        self._azure_container_edit.setPlaceholderText("backups")
        container_col.addWidget(self._azure_container_edit)
        row1.addLayout(container_col)
        layout.addLayout(row1)

        conn_col = QVBoxLayout()
        conn_col.addWidget(QLabel("Connection String"))
        self._azure_conn_edit = QLineEdit()
        self._azure_conn_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._azure_conn_edit.setPlaceholderText(
            "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;..."
        )
        conn_col.addWidget(self._azure_conn_edit)
        layout.addLayout(conn_col)

        return page

    # -- SFTP page ------------------------------------------------------------

    def _build_sftp_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)

        row1 = QHBoxLayout()
        host_col = QVBoxLayout()
        host_col.addWidget(QLabel("Host"))
        self._sftp_host_edit = QLineEdit()
        self._sftp_host_edit.setPlaceholderText("sftp.example.com")
        host_col.addWidget(self._sftp_host_edit)
        row1.addLayout(host_col)

        port_col = QVBoxLayout()
        port_col.addWidget(QLabel("Port"))
        self._sftp_port_edit = QLineEdit()
        self._sftp_port_edit.setPlaceholderText("22")
        self._sftp_port_edit.setFixedWidth(70)
        port_col.addWidget(self._sftp_port_edit)
        row1.addLayout(port_col)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        user_col = QVBoxLayout()
        user_col.addWidget(QLabel("Username"))
        self._sftp_user_edit = QLineEdit()
        user_col.addWidget(self._sftp_user_edit)
        row2.addLayout(user_col)

        pwd_col = QVBoxLayout()
        pwd_col.addWidget(QLabel("Password"))
        self._sftp_pwd_edit = QLineEdit()
        self._sftp_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_col.addWidget(self._sftp_pwd_edit)
        row2.addLayout(pwd_col)

        dir_col = QVBoxLayout()
        dir_col.addWidget(QLabel("Remote Directory"))
        self._sftp_dir_edit = QLineEdit()
        self._sftp_dir_edit.setPlaceholderText("/backups")
        dir_col.addWidget(self._sftp_dir_edit)
        row2.addLayout(dir_col)
        layout.addLayout(row2)

        return page

    # ------------------------------------------------------------------ settings / status / buttons

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Backup Settings")
        layout = QHBoxLayout(box)

        sched_col = QVBoxLayout()
        sched_col.addWidget(QLabel("Schedule"))
        self._schedule_combo = QComboBox()
        self._schedule_combo.addItems(["Hourly", "Daily", "Weekly"])
        self._schedule_combo.currentTextChanged.connect(self._on_schedule_type_changed)
        sched_col.addWidget(self._schedule_combo)
        layout.addLayout(sched_col)

        time_col = QVBoxLayout()
        self._time_label = QLabel("Time (HH:MM)")
        time_col.addWidget(self._time_label)
        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        time_col.addWidget(self._time_edit)
        layout.addLayout(time_col)

        ret_col = QVBoxLayout()
        ret_col.addWidget(QLabel("Keep Last N Backups"))
        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(1, 9999)
        self._retention_spin.setValue(30)
        ret_col.addWidget(self._retention_spin)
        layout.addLayout(ret_col)

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

        self._update_btn = QPushButton("Check for Updates")
        self._update_btn.clicked.connect(self._on_check_updates)
        row.addWidget(self._update_btn)

        row.addStretch()

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._on_test_connection)
        row.addWidget(self._test_btn)

        self._save_btn = QPushButton("Save Settings")
        self._save_btn.clicked.connect(self._on_save)
        row.addWidget(self._save_btn)

        self._backup_btn = QPushButton("▶  Backup Now")
        self._backup_btn.setStyleSheet(
            "QPushButton { background-color: #1d4ed8; color: white; "
            "font-weight: bold; padding: 6px 18px; }"
        )
        self._backup_btn.clicked.connect(self._on_backup_now)
        row.addWidget(self._backup_btn)

        return row

    # --------------------------------------------------------- provider switching

    def _on_provider_changed(self, idx: int):
        _, provider_val, page_idx = _PROVIDERS[idx]
        self._storage_stack.setCurrentIndex(page_idx)
        if page_idx == 0:
            self._refresh_s3_page(provider_val)

    def _refresh_s3_page(self, provider: str) -> None:
        show_ep = provider != "aws_s3"
        self._s3_endpoint_label.setVisible(show_ep)
        self._s3_endpoint_edit.setVisible(show_ep)

        show_region = provider in ("aws_s3", "minio")
        self._s3_region_label.setVisible(show_region)
        self._s3_region_edit.setVisible(show_region)

        placeholders = {
            "ionos":        "s3-eu-central-1.ionoscloud.com",
            "minio":        "minio.example.com:9000",
            "backblaze_b2": "s3.us-west-001.backblazeb2.com",
        }
        self._s3_endpoint_edit.setPlaceholderText(
            placeholders.get(provider, "s3.example.com")
        )

    # --------------------------------------------------------- config <-> UI

    def _current_provider_value(self) -> str:
        _, val, _ = _PROVIDERS[self._provider_combo.currentIndex()]
        return val

    def _load_config_to_ui(self):
        self._folders_list.clear()
        for folder in self._config.get("folders", []):
            self._folders_list.addItem(folder)

        # Provider selector
        provider = self._config.get("storage_provider", "ionos")
        combo_idx = _VALUE_TO_IDX.get(provider, 0)
        self._provider_combo.setCurrentIndex(combo_idx)
        # Stack + S3 page layout triggered by signal, but call manually for first load.
        _, _, page_idx = _PROVIDERS[combo_idx]
        self._storage_stack.setCurrentIndex(page_idx)
        if page_idx == 0:
            self._refresh_s3_page(provider)

        # S3 fields
        self._s3_endpoint_edit.setText(self._config.get("s3_endpoint", ""))
        self._s3_region_edit.setText(self._config.get("s3_region", ""))
        self._s3_bucket_edit.setText(self._config.get("s3_bucket", ""))
        self._s3_access_key_edit.setText(self._config.get("s3_access_key", ""))
        self._s3_secret_key_edit.setText(self._config.get("s3_secret_key", ""))

        # OneDrive fields
        self._onedrive_folder_edit.setText(self._config.get("onedrive_folder", "BackupSystem"))
        self._onedrive_token_edit.setText(self._config.get("onedrive_access_token", ""))

        # Google Drive fields
        self._gdrive_folder_edit.setText(self._config.get("gdrive_folder", "BackupSystem"))
        self._gdrive_creds_edit.setPlainText(self._config.get("gdrive_credentials_json", ""))

        # Dropbox fields
        self._dropbox_token_edit.setText(self._config.get("dropbox_access_token", ""))
        self._dropbox_folder_edit.setText(self._config.get("dropbox_folder", "/BackupSystem"))

        # Azure fields
        self._azure_container_edit.setText(self._config.get("azure_container", "backups"))
        self._azure_conn_edit.setText(self._config.get("azure_connection_string", ""))

        # SFTP fields
        self._sftp_host_edit.setText(self._config.get("sftp_host", ""))
        self._sftp_port_edit.setText(str(self._config.get("sftp_port", "22")))
        self._sftp_user_edit.setText(self._config.get("sftp_username", ""))
        self._sftp_pwd_edit.setText(self._config.get("sftp_password", ""))
        self._sftp_dir_edit.setText(self._config.get("sftp_remote_dir", "/backups"))

        # Schedule / retention
        sched = self._config.get("schedule_type", "daily").capitalize()
        idx = self._schedule_combo.findText(sched)
        if idx >= 0:
            self._schedule_combo.setCurrentIndex(idx)
        t = QTime.fromString(self._config.get("schedule_time", "02:00"), "HH:mm")
        self._time_edit.setTime(t if t.isValid() else QTime(2, 0))
        try:
            self._retention_spin.setValue(
                max(1, int(self._config.get("retention_count") or 30))
            )
        except (TypeError, ValueError):
            self._retention_spin.setValue(30)
        self._on_schedule_type_changed(self._schedule_combo.currentText())

    def _collect_config(self) -> dict:
        cfg = dict(self._config)
        cfg["folders"] = [
            self._folders_list.item(i).text()
            for i in range(self._folders_list.count())
        ]

        # Provider
        cfg["storage_provider"] = self._current_provider_value()

        # S3 fields (always collected — populated regardless of current page)
        cfg["s3_endpoint"] = self._s3_endpoint_edit.text().strip()
        cfg["s3_region"] = self._s3_region_edit.text().strip()
        cfg["s3_bucket"] = self._s3_bucket_edit.text().strip()
        cfg["s3_access_key"] = self._s3_access_key_edit.text().strip()
        cfg["s3_secret_key"] = self._s3_secret_key_edit.text().strip()

        # OneDrive
        cfg["onedrive_folder"] = self._onedrive_folder_edit.text().strip() or "BackupSystem"
        cfg["onedrive_access_token"] = self._onedrive_token_edit.text().strip()

        # Google Drive
        cfg["gdrive_folder"] = self._gdrive_folder_edit.text().strip() or "BackupSystem"
        cfg["gdrive_credentials_json"] = self._gdrive_creds_edit.toPlainText().strip()

        # Dropbox
        cfg["dropbox_access_token"] = self._dropbox_token_edit.text().strip()
        cfg["dropbox_folder"] = self._dropbox_folder_edit.text().strip() or "/BackupSystem"

        # Azure
        cfg["azure_container"] = self._azure_container_edit.text().strip() or "backups"
        cfg["azure_connection_string"] = self._azure_conn_edit.text().strip()

        # SFTP
        cfg["sftp_host"] = self._sftp_host_edit.text().strip()
        cfg["sftp_port"] = self._sftp_port_edit.text().strip() or "22"
        cfg["sftp_username"] = self._sftp_user_edit.text().strip()
        cfg["sftp_password"] = self._sftp_pwd_edit.text().strip()
        cfg["sftp_remote_dir"] = self._sftp_dir_edit.text().strip() or "/backups"

        # Schedule / retention
        cfg["schedule_type"] = self._schedule_combo.currentText().lower()
        cfg["schedule_time"] = self._time_edit.time().toString("HH:mm")
        cfg["retention_count"] = max(1, self._retention_spin.value())

        return cfg

    # ---------------------------------------------------------------- slots

    def _on_add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder to Back Up")
        if not path:
            return
        existing = [self._folders_list.item(i).text()
                    for i in range(self._folders_list.count())]
        if path not in existing:
            self._folders_list.addItem(path)

    def _on_remove_folder(self):
        row = self._folders_list.currentRow()
        if row >= 0:
            self._folders_list.takeItem(row)

    def _on_schedule_type_changed(self, text: str):
        self._time_edit.setVisible(text in ("Daily", "Weekly"))
        self._time_label.setVisible(text in ("Daily", "Weekly"))

    def _on_save(self):
        self._config = self._collect_config()
        try:
            save_config(self._config)
        except RuntimeError as e:
            QMessageBox.critical(self, "Save Failed", str(e))
            return
        save_encryption_password(self._password_edit.text())
        self._restart_scheduler()
        self._status_label.setText("Settings saved.")

    def _on_test_connection(self):
        cfg = self._collect_config()
        provider = cfg.get("storage_provider", "ionos")
        missing = self._missing_fields(cfg, provider)
        if missing:
            QMessageBox.warning(
                self, "Missing Fields",
                f"Please fill in the required fields: {', '.join(missing)}"
            )
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Testing…")
        self._conn_thread = _ConnectionTestThread(cfg, parent=self)
        self._conn_thread.result.connect(self._on_connection_result)
        self._conn_thread.start()

    @staticmethod
    def _missing_fields(cfg: dict, provider: str) -> list:
        if provider in ("ionos", "minio", "backblaze_b2"):
            return [k for k in ("s3_endpoint", "s3_bucket", "s3_access_key", "s3_secret_key")
                    if not cfg.get(k)]
        if provider == "aws_s3":
            return [k for k in ("s3_bucket", "s3_access_key", "s3_secret_key")
                    if not cfg.get(k)]
        if provider == "onedrive":
            return [k for k in ("onedrive_access_token",) if not cfg.get(k)]
        if provider == "google_drive":
            return [k for k in ("gdrive_credentials_json",) if not cfg.get(k)]
        if provider == "dropbox":
            return [k for k in ("dropbox_access_token",) if not cfg.get(k)]
        if provider == "azure_blob":
            return [k for k in ("azure_connection_string", "azure_container")
                    if not cfg.get(k)]
        if provider == "sftp":
            return [k for k in ("sftp_host", "sftp_username") if not cfg.get(k)]
        return []

    def _on_connection_result(self, ok: bool):
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test Connection")
        if ok:
            QMessageBox.information(self, "Connection OK",
                                    "Successfully connected to the storage backend.")
        else:
            QMessageBox.critical(self, "Connection Failed",
                                 "Could not connect. Check your credentials and settings.")

    def _on_backup_now(self):
        if self._worker and self._worker.isRunning():
            return
        if self._folders_list.count() == 0:
            QMessageBox.warning(self, "No Folders",
                                "Add at least one folder to back up.")
            return
        if not self._password_edit.text():
            QMessageBox.warning(self, "Password Required",
                                "Enter your encryption password before running a backup.")
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
        cfg.pop("password", None)

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
        try:
            save_config(self._config)
        except RuntimeError as e:
            self._append_log(f"WARNING: could not persist last_run timestamp: {e}")

    # -------------------------------------------------------------- scheduler

    def _restart_scheduler(self):
        if hasattr(self, "_timer"):
            self._timer.stop()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_scheduler_tick)
        self._timer.start(60_000)
        self._compute_next_run()

    def _compute_next_run(self):
        cfg = self._config
        now = datetime.now()
        stype = cfg.get("schedule_type", "daily")
        t_str = cfg.get("schedule_time", "02:00") or "02:00"
        try:
            h, m = (int(x) for x in t_str.split(":"))
            if not (0 <= h < 24 and 0 <= m < 60):
                raise ValueError("out of range")
        except (ValueError, AttributeError):
            h, m = 2, 0

        if stype == "hourly":
            self._next_run = (
                now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            )
        elif stype == "daily":
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            self._next_run = (
                candidate if candidate > now else candidate + timedelta(days=1)
            )
        elif stype == "weekly":
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            days_ahead = (6 - now.weekday()) % 7
            if days_ahead == 0:
                self._next_run = (
                    candidate if candidate > now else candidate + timedelta(days=7)
                )
            else:
                self._next_run = candidate + timedelta(days=days_ahead)

    def _on_scheduler_tick(self):
        if self._next_run and datetime.now() >= self._next_run:
            self._compute_next_run()
            if self._worker and self._worker.isRunning():
                self._append_log("Scheduled backup skipped — previous backup still running.")
                return
            password = self._password_edit.text() or load_encryption_password()
            if not password:
                self._append_log("Scheduled backup skipped — password not set.")
                return
            cfg = self._collect_config()
            cfg["password"] = password
            self._start_backup(cfg)

    # --------------------------------------------------------- auto-update

    def _check_for_updates_silently(self):
        self._update_check_thread = _UpdateCheckThread(self._version, parent=self)
        self._update_check_thread.update_available.connect(self._on_update_available)
        self._update_check_thread.start()

    def _on_check_updates(self):
        if hasattr(self, "_update_check_thread") and self._update_check_thread.isRunning():
            return
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Checking…")
        self._update_check_thread = _UpdateCheckThread(self._version, parent=self)
        self._update_check_thread.update_available.connect(self._on_update_available)
        self._update_check_thread.no_update.connect(self._on_no_update)
        self._update_check_thread.start()

    def _on_no_update(self):
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Check for Updates")
        QMessageBox.information(
            self, "Up to date",
            f"You are running the latest version (v{self._version})."
        )

    def _on_update_available(self, latest: str, url: str, checksum_url: str):
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Check for Updates")
        if not checksum_url:
            QMessageBox.information(
                self, "Update Available",
                f"Version {latest} is available, but no SHA-256 checksum asset was found "
                f"in the release.\n\nAuto-update requires integrity verification. "
                f"Please download manually from the GitHub releases page.",
            )
            return
        reply = QMessageBox.question(
            self, "Update Available",
            f"Version {latest} is available (you have v{self._version}).\n"
            f"The download will be SHA-256 verified before installation.\n\nDownload and install now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_download(url, checksum_url)

    def _start_download(self, url: str, checksum_url: str = ""):
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Downloading…")
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._dl_thread = _UpdateDownloadThread(url, checksum_url=checksum_url, parent=self)
        self._dl_thread.progress.connect(self._progress_bar.setValue)
        self._dl_thread.done.connect(self._on_download_done)
        self._dl_thread.start()

    def _on_download_done(self, path: str):
        import shutil
        self._progress_bar.setVisible(False)
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Check for Updates")
        if not path:
            QMessageBox.critical(
                self, "Update Failed",
                "Could not download or verify the update.\n"
                "The file may have failed its integrity check. Please try again later."
            )
            return
        reply = QMessageBox.question(
            self, "Install Update",
            "Download complete and verified. The application will restart to apply the update.\n\nRestart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if install_update(path):
                from PyQt6.QtWidgets import QApplication
                QApplication.quit()
            else:
                QMessageBox.information(
                    self, "Manual Install Required",
                    f"Auto-update is only supported in the installed .exe.\n\nNew file is at:\n{path}",
                )
        else:
            tmp_dir = os.path.dirname(path)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # -------------------------------------------------------- window lifecycle

    def request_quit(self):
        from PyQt6.QtWidgets import QApplication
        running = []
        if self._worker and self._worker.isRunning():
            running.append("a backup")
        if hasattr(self, "_dl_thread") and self._dl_thread.isRunning():
            running.append("an update download")
        if running:
            reply = QMessageBox.question(
                self, "Quit",
                f"BackupSystem is currently running {' and '.join(running)}.\n\nQuit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        for thread in [self._worker,
                       getattr(self, "_dl_thread", None),
                       getattr(self, "_update_check_thread", None),
                       getattr(self, "_conn_thread", None)]:
            if thread and thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(3000)
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
