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
