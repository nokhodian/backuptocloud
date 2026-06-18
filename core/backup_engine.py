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
    backup_done = pyqtSignal(bool, str)  # success, message

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config)  # own copy so caller's pop() doesn't affect us

    def run(self):
        try:
            self._execute()
        except Exception as exc:
            self.log_line.emit(f"ERROR: {exc}")
            self.backup_done.emit(False, str(exc))

    def _execute(self):
        cfg = self._config
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
        enc_name = f"backup-{timestamp}.zip.enc"

        valid_folders = [f for f in cfg.get("folders", []) if f and os.path.isdir(f)]
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
                if total > 0:
                    pct = 50 + int((transferred / total) * 40)
                    self.progress.emit(pct)

            _upload_with_retry(storage, enc_path, enc_name, _progress_cb, log_fn=self.log_line.emit, worker=self)
            self.progress.emit(90)

            self.log_line.emit(f"[{timestamp}] Applying retention policy...")
            _prune(storage, cfg.get("retention_count", 30))
            self.progress.emit(100)

            size_mb = file_size / (1024 * 1024)
            msg = f"Backup complete — {size_mb:.1f} MB uploaded"
            self.log_line.emit(f"[{timestamp}] {msg}")
            self.backup_done.emit(True, msg)


def _upload_with_retry(storage: IONOSStorage, local_path: str, object_key: str, progress_cb, log_fn=None, worker=None) -> None:
    import time
    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays):
        try:
            storage.upload(local_path, object_key, progress_cb)
            return
        except Exception as exc:
            if attempt == len(delays) - 1:
                raise
            if log_fn:
                log_fn(f"Upload attempt {attempt + 1} failed ({exc}), retrying in {delay}s...")
            # Sleep in 1-second slices so a quit request is detected promptly.
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if worker and worker.isInterruptionRequested():
                    raise InterruptedError("Backup cancelled")
                time.sleep(max(0.0, min(1.0, deadline - time.monotonic())))


def _zip_folders(folders: list, zip_path: str) -> None:
    valid = [f for f in folders if f and os.path.isdir(f)]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in valid:
            # Build a unique archive prefix from the full path so two folders
            # with the same basename (e.g. C:\docs and D:\docs) don't collide.
            safe_prefix = folder.replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
            for root, _dirs, files in os.walk(folder):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    # ZIP spec requires forward slashes; normalize for cross-platform extractors.
                    rel = os.path.relpath(full_path, folder).replace("\\", "/")
                    arcname = f"{safe_prefix}/{rel}"
                    zf.write(full_path, arcname)


def _prune(storage: IONOSStorage, retention_count: int) -> None:
    keys = storage.list_backups()
    excess = len(keys) - retention_count
    if excess > 0:
        for key in keys[:excess]:
            storage.delete(key)
