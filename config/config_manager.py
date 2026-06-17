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
