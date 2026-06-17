# config/config_manager.py
import json
import os
from pathlib import Path

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "BackupSystem"
_CREDENTIAL_KEYS = ("ionos_access_key", "ionos_secret_key")

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
        cfg = dict(DEFAULT_CONFIG)
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cfg = {**DEFAULT_CONFIG, **data}

    if _KEYRING_AVAILABLE:
        for key in _CREDENTIAL_KEYS:
            value = keyring.get_password(_KEYRING_SERVICE, key)
            if value is not None:
                cfg[key] = value

    return cfg


def save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    safe = {k: v for k, v in config.items() if k not in _CREDENTIAL_KEYS}

    if _KEYRING_AVAILABLE:
        for key in _CREDENTIAL_KEYS:
            value = config.get(key, "")
            if value:
                keyring.set_password(_KEYRING_SERVICE, key, value)
            else:
                try:
                    keyring.delete_password(_KEYRING_SERVICE, key)
                except Exception:
                    pass
    else:
        # keyring not available — fall back to JSON (with warning in safe dict)
        safe["ionos_access_key"] = config.get("ionos_access_key", "")
        safe["ionos_secret_key"] = config.get("ionos_secret_key", "")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2)
