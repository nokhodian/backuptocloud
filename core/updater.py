import hashlib
import json
import logging
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse

GITHUB_REPO = "nokhodian/backuptocloud"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_ALLOWED_DOWNLOAD_HOSTS = {"objects.githubusercontent.com", "github.com"}


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0, 0, 0)


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Download URL must use HTTPS, got: {parsed.scheme!r}")
    if parsed.netloc not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(f"Download URL host not allowed: {parsed.netloc!r}")


def _verify_sha256(file_path: str, expected_hex: str) -> bool:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hex.strip().lower()


def fetch_latest_release() -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "BackupSystem-Updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def check_for_update(current_version: str) -> tuple[str | None, str | None, str | None]:
    """Returns (latest_version, download_url, checksum_url) or (None, None, None)."""
    try:
        release = fetch_latest_release()
        latest_tag = release.get("tag_name", "").lstrip("v")
        if not latest_tag:
            return None, None, None
        if _parse_version(latest_tag) > _parse_version(current_version):
            assets = release.get("assets", [])
            exe_url = None
            sha_url = None
            for asset in assets:
                name = asset["name"].lower()
                if name.endswith(".exe"):
                    exe_url = asset["browser_download_url"]
                elif name.endswith(".exe.sha256") or name == "sha256sums.txt":
                    sha_url = asset["browser_download_url"]
            if exe_url:
                return latest_tag, exe_url, sha_url
    except ssl.SSLCertVerificationError as e:
        logging.error("TLS certificate validation failed during update check: %s", e)
    except OSError:
        pass
    except Exception:
        pass
    return None, None, None


def download_update(
    download_url: str,
    checksum_url: str | None = None,
    progress_cb=None,
    worker=None,
) -> str | None:
    """
    Downloads the new .exe and verifies its SHA-256.
    checksum_url is required — returns None if absent (no unverified installs).
    progress_cb receives (bytes_downloaded, total_bytes).
    worker is a QThread whose isInterruptionRequested() is polled during download.
    Returns the verified file path, or None on any failure (including hash mismatch).
    Cleans up its temp directory on any failure; caller owns the directory on success.
    """
    if not checksum_url:
        logging.error("Update rejected: no checksum asset in release — refusing unverified install")
        return None

    tmp_dir = None
    try:
        _validate_download_url(download_url)
        tmp_dir = tempfile.mkdtemp(prefix="backupsystem_update_")
        new_exe = os.path.join(tmp_dir, "BackupSystem_new.exe")

        req = urllib.request.Request(download_url, headers={"User-Agent": "BackupSystem-Updater"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(new_exe, "wb") as f:
                while True:
                    if worker and worker.isInterruptionRequested():
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        return None
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        progress_cb(downloaded, total)

        _validate_download_url(checksum_url)
        sha_req = urllib.request.Request(
            checksum_url, headers={"User-Agent": "BackupSystem-Updater"}
        )
        with urllib.request.urlopen(sha_req, timeout=30) as resp:
            checksum_text = resp.read().decode("utf-8")
        # Handle both single-entry ("HASH  BackupSystem.exe") and multi-entry
        # sha256sums.txt. Find the line whose filename token contains "backupsystem"
        # and ends in ".exe" — covers both BackupSystem.exe and BackupSystem-1.2.3.exe.
        expected_hex = None
        for line in checksum_text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                fname = parts[-1].lower()
                if "backupsystem" in fname and fname.endswith(".exe"):
                    expected_hex = parts[0]
                    break
            elif len(parts) == 1 and len(parts[0]) == 64 and all(c in "0123456789abcdefABCDEF" for c in parts[0]):
                # Bare 64-char hex hash (single-asset release with no filename column).
                expected_hex = parts[0]
                break
        if not expected_hex:
            logging.error("SHA-256 checksum file did not contain a hash for BackupSystem.exe")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None
        if not _verify_sha256(new_exe, expected_hex):
            logging.error("SHA-256 verification failed for downloaded update — aborting")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        return new_exe  # caller (install_update) owns tmp_dir until the .bat runs
    except Exception as exc:
        logging.error("Update download failed: %s", exc)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


def install_update(new_exe_path: str) -> bool:
    """
    Writes a .bat that replaces the running .exe after exit, then launches it.
    Only works when running as a frozen PyInstaller bundle.
    Returns True if the update was scheduled (app should now quit).
    """
    if not getattr(sys, "frozen", False):
        return False

    current_exe = os.path.abspath(sys.executable)
    bat_dir = os.path.dirname(new_exe_path)
    bat_path = os.path.join(bat_dir, "do_update.bat")

    bat_lines = [
        "@echo off",
        "timeout /t 2 /nobreak >nul",
        f'move /Y "{new_exe_path}" "{current_exe}"',
        f'start "" "{current_exe}"',
        'del "%~f0"',
    ]
    with open(bat_path, "w") as f:
        f.write("\r\n".join(bat_lines) + "\r\n")

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return True
