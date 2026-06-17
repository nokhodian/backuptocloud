# Backup System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop app that backs up two folders as AES-256-GCM encrypted timestamped zip archives uploaded to IONOS Object Storage, with a PyQt6 system tray + main window GUI.

**Architecture:** Core logic (encryption, storage, backup engine) is fully decoupled from the PyQt6 UI. The backup runs in a `QThread` subclass (`BackupWorker`) that emits Qt signals for progress and log updates. A `QTimer` in the main window drives scheduled backups — fires every 60 seconds, checks if it's time to run. The encryption password lives in memory only (the UI field), never written to disk.

**Tech Stack:** Python 3.11+, PyQt6, boto3 (S3-compatible), cryptography (AES-256-GCM), schedule, PyInstaller

---

## File Map

```
backupsystem/
├── main.py                       # Entry point — creates QApplication, MainWindow, TrayIcon
├── requirements.txt              # All Python dependencies
├── config/
│   ├── __init__.py
│   └── config_manager.py         # load_config() / save_config() → %APPDATA%\BackupSystem\config.json
├── core/
│   ├── __init__.py
│   ├── encryption.py             # encrypt_file() / decrypt_file() — AES-256-GCM + PBKDF2
│   ├── storage.py                # IONOSStorage — upload / list_backups / delete / test_connection
│   └── backup_engine.py          # BackupWorker(QThread) — zip → encrypt → upload → prune
├── ui/
│   ├── __init__.py
│   ├── main_window.py            # MainWindow(QMainWindow) — all settings + status + log + buttons
│   └── tray.py                   # TrayIcon(QSystemTrayIcon) — right-click menu
├── assets/
│   └── icon.png                  # App icon (generated in Task 9; used as tray + window icon)
└── tests/
    ├── __init__.py
    ├── test_config_manager.py
    ├── test_encryption.py
    ├── test_storage.py
    └── test_backup_engine.py
```

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `config/__init__.py`, `core/__init__.py`, `ui/__init__.py`, `tests/__init__.py`, `assets/` dir

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p config core ui assets tests
touch config/__init__.py core/__init__.py ui/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
PyQt6>=6.6.0
boto3>=1.34.0
cryptography>=42.0.0
```

- [ ] **Step 3: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: All packages install without error.

- [ ] **Step 4: Verify installs**

```bash
python -c "import PyQt6; import boto3; import cryptography; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git init
git add requirements.txt config/__init__.py core/__init__.py ui/__init__.py tests/__init__.py
git commit -m "feat: project skeleton"
```

---

### Task 2: Config Manager

**Files:**
- Create: `config/config_manager.py`
- Create: `tests/test_config_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_manager.py
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


def test_load_config_returns_defaults_when_no_file(tmp_path):
    with patch("config.config_manager._config_path", return_value=tmp_path / "config.json"):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folder1"] == ""
    assert cfg["retention_count"] == 30
    assert cfg["schedule_type"] == "daily"


def test_save_and_load_roundtrip(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("config.config_manager._config_path", return_value=config_file):
        from config.config_manager import load_config, save_config
        cfg = load_config()
        cfg["folder1"] = "C:\\Users\\Test\\Docs"
        cfg["retention_count"] = 7
        save_config(cfg)
        loaded = load_config()
    assert loaded["folder1"] == "C:\\Users\\Test\\Docs"
    assert loaded["retention_count"] == 7


def test_load_config_merges_missing_keys(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"folder1": "C:\\\\old"}')
    with patch("config.config_manager._config_path", return_value=config_file):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folder1"] == "C:\\old"
    assert cfg["retention_count"] == 30  # default still present
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config_manager.py -v
```

Expected: ImportError or ModuleNotFoundError — `config_manager` doesn't exist yet.

- [ ] **Step 3: Implement config_manager.py**

```python
# config/config_manager.py
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "folder1": "",
    "folder2": "",
    "ionos_endpoint": "",
    "ionos_bucket": "",
    "ionos_access_key": "",
    "ionos_secret_key": "",
    "schedule_type": "daily",
    "schedule_time": "02:00",
    "retention_count": 30,
    "last_run": None,
}


def _config_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "BackupSystem" / "config.json"


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {**DEFAULT_CONFIG, **data}


def save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config_manager.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add config/config_manager.py tests/test_config_manager.py
git commit -m "feat: config manager with load/save and defaults"
```

---

### Task 3: Encryption Module

**Files:**
- Create: `core/encryption.py`
- Create: `tests/test_encryption.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_encryption.py
import os
import pytest
from cryptography.exceptions import InvalidTag
from core.encryption import encrypt_file, decrypt_file


def test_encrypt_decrypt_roundtrip(tmp_path):
    src = tmp_path / "plain.txt"
    enc = tmp_path / "plain.txt.enc"
    dec = tmp_path / "plain_restored.txt"
    src.write_bytes(b"Hello, backup world!")

    encrypt_file(str(src), str(enc), "my-secret-password")
    decrypt_file(str(enc), str(dec), "my-secret-password")

    assert dec.read_bytes() == b"Hello, backup world!"


def test_wrong_password_raises(tmp_path):
    src = tmp_path / "data.bin"
    enc = tmp_path / "data.bin.enc"
    dec = tmp_path / "data_out.bin"
    src.write_bytes(b"sensitive data")

    encrypt_file(str(src), str(enc), "correct-password")

    with pytest.raises(InvalidTag):
        decrypt_file(str(enc), str(dec), "wrong-password")


def test_encrypted_file_has_salt_nonce_prefix(tmp_path):
    src = tmp_path / "file.txt"
    enc = tmp_path / "file.txt.enc"
    src.write_bytes(b"data")

    encrypt_file(str(src), str(enc), "pass")

    # 16 salt + 12 nonce = 28 bytes header minimum
    assert enc.stat().st_size > 28


def test_different_runs_produce_different_ciphertext(tmp_path):
    src = tmp_path / "file.txt"
    src.write_bytes(b"same content")
    enc1 = tmp_path / "enc1.bin"
    enc2 = tmp_path / "enc2.bin"

    encrypt_file(str(src), str(enc1), "pass")
    encrypt_file(str(src), str(enc2), "pass")

    assert enc1.read_bytes() != enc2.read_bytes()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_encryption.py -v
```

Expected: ImportError — `core.encryption` doesn't exist yet.

- [ ] **Step 3: Implement encryption.py**

```python
# core/encryption.py
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_SALT_SIZE = 16
_NONCE_SIZE = 12
_ITERATIONS = 390_000


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(src_path: str, dst_path: str, password: str) -> None:
    salt = os.urandom(_SALT_SIZE)
    nonce = os.urandom(_NONCE_SIZE)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    with open(src_path, "rb") as f:
        plaintext = f.read()

    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    with open(dst_path, "wb") as f:
        f.write(salt + nonce + ciphertext)


def decrypt_file(src_path: str, dst_path: str, password: str) -> None:
    with open(src_path, "rb") as f:
        data = f.read()

    salt = data[:_SALT_SIZE]
    nonce = data[_SALT_SIZE:_SALT_SIZE + _NONCE_SIZE]
    ciphertext = data[_SALT_SIZE + _NONCE_SIZE:]

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    with open(dst_path, "wb") as f:
        f.write(plaintext)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_encryption.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/encryption.py tests/test_encryption.py
git commit -m "feat: AES-256-GCM encryption with PBKDF2 key derivation"
```

---

### Task 4: Storage Module (IONOS/S3)

**Files:**
- Create: `core/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage.py
import os
import pytest
from unittest.mock import MagicMock, patch, call
from core.storage import IONOSStorage


@pytest.fixture
def mock_boto_client():
    with patch("core.storage.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        yield mock_client


def make_storage(mock_boto_client):
    return IONOSStorage("s3.example.com", "my-bucket", "ACCESS", "SECRET")


def test_list_backups_returns_sorted_keys(mock_boto_client):
    mock_boto_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "backup-2026-06-17-02-00.zip.enc"},
            {"Key": "backup-2026-06-15-02-00.zip.enc"},
            {"Key": "backup-2026-06-16-02-00.zip.enc"},
        ]
    }
    storage = make_storage(mock_boto_client)
    keys = storage.list_backups()
    assert keys == [
        "backup-2026-06-15-02-00.zip.enc",
        "backup-2026-06-16-02-00.zip.enc",
        "backup-2026-06-17-02-00.zip.enc",
    ]


def test_list_backups_returns_empty_when_no_objects(mock_boto_client):
    mock_boto_client.list_objects_v2.return_value = {}
    storage = make_storage(mock_boto_client)
    assert storage.list_backups() == []


def test_delete_calls_delete_object(mock_boto_client):
    storage = make_storage(mock_boto_client)
    storage.delete("backup-2026-06-15-02-00.zip.enc")
    mock_boto_client.delete_object.assert_called_once_with(
        Bucket="my-bucket", Key="backup-2026-06-15-02-00.zip.enc"
    )


def test_test_connection_returns_true_on_success(mock_boto_client):
    storage = make_storage(mock_boto_client)
    assert storage.test_connection() is True
    mock_boto_client.head_bucket.assert_called_once_with(Bucket="my-bucket")


def test_test_connection_returns_false_on_error(mock_boto_client):
    mock_boto_client.head_bucket.side_effect = Exception("Connection refused")
    storage = make_storage(mock_boto_client)
    assert storage.test_connection() is False


def test_upload_calls_upload_file(mock_boto_client, tmp_path):
    test_file = tmp_path / "test.zip.enc"
    test_file.write_bytes(b"encrypted data")
    storage = make_storage(mock_boto_client)
    storage.upload(str(test_file), "backup-2026-06-17-02-00.zip.enc")
    mock_boto_client.upload_file.assert_called_once()
    args, kwargs = mock_boto_client.upload_file.call_args
    assert args[0] == str(test_file)
    assert args[1] == "my-bucket"
    assert args[2] == "backup-2026-06-17-02-00.zip.enc"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_storage.py -v
```

Expected: ImportError — `core.storage` doesn't exist yet.

- [ ] **Step 3: Implement storage.py**

```python
# core/storage.py
import os
from typing import Callable, Optional

import boto3
from botocore.config import Config


class IONOSStorage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )

    def upload(
        self,
        local_path: str,
        object_key: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        file_size = os.path.getsize(local_path)
        transferred = [0]

        def _callback(bytes_amount: int) -> None:
            transferred[0] += bytes_amount
            if progress_cb:
                progress_cb(transferred[0], file_size)

        self._client.upload_file(local_path, self._bucket, object_key, Callback=_callback)

    def list_backups(self) -> list:
        response = self._client.list_objects_v2(Bucket=self._bucket, Prefix="backup-")
        contents = response.get("Contents", [])
        return sorted(obj["Key"] for obj in contents)

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def test_connection(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_storage.py -v
```

Expected: 6 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/storage.py tests/test_storage.py
git commit -m "feat: IONOS S3-compatible storage wrapper"
```

---

### Task 5: Backup Engine (QThread)

**Files:**
- Create: `core/backup_engine.py`
- Create: `tests/test_backup_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_engine.py
import os
import zipfile
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
import sys

# QApplication required for QThread
app = QApplication.instance() or QApplication(sys.argv)


def make_config(tmp_path, folder1, folder2=""):
    return {
        "folder1": str(folder1),
        "folder2": str(folder2),
        "ionos_endpoint": "s3.example.com",
        "ionos_bucket": "bucket",
        "ionos_access_key": "key",
        "ionos_secret_key": "secret",
        "retention_count": 3,
        "password": "test-password",
    }


def test_zip_folders_includes_all_files(tmp_path):
    from core.backup_engine import _zip_folders

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("hello")
    (folder / "b.txt").write_text("world")
    sub = folder / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("nested")

    zip_path = str(tmp_path / "out.zip")
    _zip_folders([str(folder)], zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any("a.txt" in n for n in names)
    assert any("b.txt" in n for n in names)
    assert any("c.txt" in n for n in names)


def test_zip_folders_skips_missing_folder(tmp_path):
    from core.backup_engine import _zip_folders

    real_folder = tmp_path / "real"
    real_folder.mkdir()
    (real_folder / "file.txt").write_text("data")

    zip_path = str(tmp_path / "out.zip")
    _zip_folders([str(real_folder), "/nonexistent/path"], zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert len(zf.namelist()) == 1


def test_prune_deletes_oldest_beyond_retention(tmp_path):
    from core.backup_engine import _prune

    storage = MagicMock()
    storage.list_backups.return_value = [
        "backup-2026-06-14-02-00.zip.enc",
        "backup-2026-06-15-02-00.zip.enc",
        "backup-2026-06-16-02-00.zip.enc",
        "backup-2026-06-17-02-00.zip.enc",
    ]
    _prune(storage, retention_count=2)

    assert storage.delete.call_count == 2
    storage.delete.assert_any_call("backup-2026-06-14-02-00.zip.enc")
    storage.delete.assert_any_call("backup-2026-06-15-02-00.zip.enc")


def test_prune_does_nothing_within_retention(tmp_path):
    from core.backup_engine import _prune

    storage = MagicMock()
    storage.list_backups.return_value = [
        "backup-2026-06-16-02-00.zip.enc",
        "backup-2026-06-17-02-00.zip.enc",
    ]
    _prune(storage, retention_count=5)
    storage.delete.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_backup_engine.py -v
```

Expected: ImportError — `core.backup_engine` doesn't exist yet.

- [ ] **Step 3: Implement backup_engine.py**

```python
# core/backup_engine.py
import os
import zipfile
import tempfile
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.encryption import encrypt_file
from core.storage import IONOSStorage


class BackupWorker(QThread):
    progress = pyqtSignal(int)      # 0-100
    log_line = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

    def run(self):
        try:
            self._execute()
        except Exception as exc:
            self.log_line.emit(f"ERROR: {exc}")
            self.finished.emit(False, str(exc))

    def _execute(self):
        cfg = self._config
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
        enc_name = f"backup-{timestamp}.zip.enc"

        folders = [cfg.get("folder1", ""), cfg.get("folder2", "")]
        valid_folders = [f for f in folders if f and os.path.isdir(f)]
        if not valid_folders:
            raise ValueError("No valid folders to back up. Check your folder settings.")

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, f"backup-{timestamp}.zip")
            enc_path = os.path.join(tmpdir, enc_name)

            self.log_line.emit(f"[{timestamp}] Zipping {len(valid_folders)} folder(s)...")
            self.progress.emit(10)
            _zip_folders(valid_folders, zip_path)

            self.log_line.emit(f"[{timestamp}] Encrypting archive...")
            self.progress.emit(40)
            encrypt_file(zip_path, enc_path, cfg["password"])
            os.remove(zip_path)

            self.log_line.emit(f"[{timestamp}] Uploading to IONOS...")
            self.progress.emit(50)
            storage = IONOSStorage(
                cfg["ionos_endpoint"],
                cfg["ionos_bucket"],
                cfg["ionos_access_key"],
                cfg["ionos_secret_key"],
            )
            file_size = os.path.getsize(enc_path)

            def _progress_cb(transferred: int, total: int) -> None:
                pct = 50 + int((transferred / total) * 40)
                self.progress.emit(pct)

            _upload_with_retry(storage, enc_path, enc_name, _progress_cb)
            self.progress.emit(90)

            self.log_line.emit(f"[{timestamp}] Applying retention policy...")
            _prune(storage, cfg.get("retention_count", 30))
            self.progress.emit(100)

            size_mb = file_size / (1024 * 1024)
            msg = f"Backup complete — {size_mb:.1f} MB uploaded"
            self.log_line.emit(f"[{timestamp}] {msg}")
            self.finished.emit(True, msg)


def _upload_with_retry(storage: IONOSStorage, local_path: str, object_key: str, progress_cb) -> None:
    import time
    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays):
        try:
            storage.upload(local_path, object_key, progress_cb)
            return
        except Exception:
            if attempt == len(delays) - 1:
                raise
            time.sleep(delay)


def _zip_folders(folders: list, zip_path: str) -> None:
    valid = [f for f in folders if f and os.path.isdir(f)]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in valid:
            folder_name = os.path.basename(folder.rstrip("/\\")) or folder
            for root, _dirs, files in os.walk(folder):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    arcname = os.path.join(folder_name, os.path.relpath(full_path, folder))
                    zf.write(full_path, arcname)


def _prune(storage: IONOSStorage, retention_count: int) -> None:
    keys = storage.list_backups()
    excess = len(keys) - retention_count
    if excess > 0:
        for key in keys[:excess]:
            storage.delete(key)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_backup_engine.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Run the full test suite to check nothing broke**

```bash
pytest tests/ -v
```

Expected: All tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add core/backup_engine.py tests/test_backup_engine.py
git commit -m "feat: backup engine — zip, encrypt, upload, prune in QThread"
```

---

### Task 6: Main Window UI

**Files:**
- Create: `ui/main_window.py`

Note: PyQt6 UI code is tested manually (run the app). No unit tests for this task.

- [ ] **Step 1: Implement main_window.py**

```python
# ui/main_window.py
import sys
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTextEdit, QTimeEdit, QVBoxLayout,
    QWidget, QComboBox, QFrame,
)
from PyQt6.QtCore import QTime

from config.config_manager import load_config, save_config
from core.backup_engine import BackupWorker
from core.storage import IONOSStorage


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
        storage = IONOSStorage(cfg["ionos_endpoint"], cfg["ionos_bucket"], cfg["ionos_access_key"], cfg["ionos_secret_key"])
        ok = storage.test_connection()
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
        self._worker.finished.connect(self._on_backup_finished)
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
```

- [ ] **Step 2: Verify the file has no syntax errors**

```bash
python -m py_compile ui/main_window.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ui/main_window.py
git commit -m "feat: main window UI with folder picker, credentials, schedule, log"
```

---

### Task 7: System Tray Icon

**Files:**
- Create: `ui/tray.py`

- [ ] **Step 1: Implement tray.py**

```python
# ui/tray.py
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject


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
```

- [ ] **Step 2: Verify the file has no syntax errors**

```bash
python -m py_compile ui/tray.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ui/tray.py
git commit -m "feat: system tray icon with Open, Backup Now, Quit menu"
```

---

### Task 8: App Icon

**Files:**
- Create: `assets/icon.png` (generated programmatically)

- [ ] **Step 1: Generate a simple icon using Python**

Run this once to produce the icon file:

```python
# Run as: python create_icon.py
# (delete this file after running)
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (64, 64), (29, 78, 216, 255))  # blue background
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=(255, 255, 255, 40))
    draw.text((16, 18), "B", fill="white")
    img.save("assets/icon.png")
    print("Created assets/icon.png using Pillow")
except ImportError:
    # Pillow not installed — create a minimal 1x1 PNG as placeholder
    import struct, zlib
    def make_png():
        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xffffffff)
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        idat = chunk(b"IDAT", zlib.compress(b"\x00\x1d\x4e\xd8"))
        iend = chunk(b"IEND", b"")
        return sig + ihdr + idat + iend
    with open("assets/icon.png", "wb") as f:
        f.write(make_png())
    print("Created minimal assets/icon.png (install Pillow for a nicer icon)")
```

```bash
python create_icon.py
```

Expected: `assets/icon.png` created.

- [ ] **Step 2: Remove the helper script and commit**

```bash
rm create_icon.py
git add assets/icon.png
git commit -m "feat: add app icon"
```

---

### Task 9: Entry Point — Wire Everything Together

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement main.py**

```python
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
```

- [ ] **Step 2: Verify the file has no syntax errors**

```bash
python -m py_compile main.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Run the full test suite one more time**

```bash
pytest tests/ -v
```

Expected: All tests PASSED.

- [ ] **Step 4: Launch the app to verify it starts**

```bash
python main.py
```

Expected: Window opens with all sections visible. Tray icon appears in taskbar (on Windows) or menu bar (on macOS for testing). Close the window — app stays alive in tray. Right-click tray → Quit exits cleanly.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: entry point wiring MainWindow and TrayIcon"
```

---

### Task 10: Packaging for Windows

**Files:**
- Create: `BackupSystem.spec` (PyInstaller spec)
- Create: `build.bat` (one-click build script for Windows)

> **Note:** PyInstaller must be run **on Windows** to produce a Windows `.exe`. You can develop and test on macOS/Linux, but run this task on the target Windows machine.

- [ ] **Step 1: Install PyInstaller on the Windows build machine**

```bat
pip install pyinstaller
```

- [ ] **Step 2: Create the PyInstaller spec file**

```python
# BackupSystem.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/icon.png', 'assets')],
    hiddenimports=['boto3', 'botocore', 'cryptography'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BackupSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.png',
)
```

- [ ] **Step 3: Create build.bat**

```bat
@echo off
echo Building BackupSystem.exe...
pyinstaller BackupSystem.spec --clean
echo.
echo Done. Find BackupSystem.exe in dist\
pause
```

- [ ] **Step 4: Build the exe (run on Windows)**

```bat
build.bat
```

Expected: `dist\BackupSystem.exe` created (~40-60 MB). No console window opens when run.

- [ ] **Step 5: Smoke-test the exe on Windows**

Double-click `dist\BackupSystem.exe`. Expected:
- App window opens
- Tray icon appears in notification area
- Browse buttons work
- "Test Connection" shows success/failure message
- "Backup Now" with a password entered runs and shows progress

- [ ] **Step 6: Commit**

```bash
git add BackupSystem.spec build.bat
git commit -m "feat: PyInstaller packaging spec and Windows build script"
```

