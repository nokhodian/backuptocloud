import json
import os
import subprocess
import sys
import tempfile
import urllib.request

GITHUB_REPO = "nokhodian/backuptocloud"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0, 0, 0)


def fetch_latest_release() -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "BackupSystem-Updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def check_for_update(current_version: str) -> tuple[str | None, str | None]:
    """Returns (latest_version, download_url) if a newer version exists, else (None, None)."""
    try:
        release = fetch_latest_release()
        latest_tag = release.get("tag_name", "").lstrip("v")
        if not latest_tag:
            return None, None
        if _parse_version(latest_tag) > _parse_version(current_version):
            for asset in release.get("assets", []):
                if asset["name"].lower().endswith(".exe"):
                    return latest_tag, asset["browser_download_url"]
    except Exception:
        pass
    return None, None


def download_update(download_url: str, progress_cb=None) -> str | None:
    """
    Downloads the new .exe to a temp directory.
    progress_cb receives (bytes_downloaded, total_bytes).
    Returns the path to the downloaded file, or None on failure.
    """
    try:
        tmp_dir = tempfile.mkdtemp(prefix="backupsystem_update_")
        new_exe = os.path.join(tmp_dir, "BackupSystem_new.exe")
        req = urllib.request.Request(download_url, headers={"User-Agent": "BackupSystem-Updater"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(new_exe, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        progress_cb(downloaded, total)
        return new_exe
    except Exception:
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
