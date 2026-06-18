# config/config_manager.py
import json
import os
from pathlib import Path

try:
    import keyring
    import keyring.errors
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "BackupSystem"
_CREDENTIAL_KEYS = ("ionos_access_key", "ionos_secret_key")
_PASSWORD_KEY = "encryption_password"

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


def _keyring_get(key: str) -> str | None:
    if not _KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(_KEYRING_SERVICE, key)
    except Exception:
        return None


def _keyring_set(key: str, value: str) -> bool:
    """Returns True on success, False if keyring is unavailable or raises."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, key, value)
        return True
    except Exception:
        return False


def _keyring_delete(key: str) -> None:
    if not _KEYRING_AVAILABLE:
        return
    try:
        keyring.delete_password(_KEYRING_SERVICE, key)
    except Exception:
        pass


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        cfg = dict(DEFAULT_CONFIG)
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cfg = {**DEFAULT_CONFIG, **data}

    for key in _CREDENTIAL_KEYS:
        value = _keyring_get(key)
        if value is not None:
            cfg[key] = value

    return cfg


def save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Never write credentials or password to JSON regardless of keyring status.
    excluded = set(_CREDENTIAL_KEYS) | {"password"}
    safe = {k: v for k, v in config.items() if k not in excluded}

    for key in _CREDENTIAL_KEYS:
        value = config.get(key, "")
        if value:
            if not _keyring_set(key, value):
                raise RuntimeError(
                    "Secure credential storage (keyring) is unavailable.\n"
                    "Cannot save IONOS credentials safely.\n"
                    "Please ensure the 'keyring' package and a keyring backend are installed."
                )
        else:
            _keyring_delete(key)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2)


def save_encryption_password(password: str) -> bool:
    """Stores the encryption password in the OS keyring. Returns True on success."""
    if not password:
        _keyring_delete(_PASSWORD_KEY)
        return True
    return _keyring_set(_PASSWORD_KEY, password)


def load_encryption_password() -> str | None:
    """Retrieves the stored encryption password, or None if not set."""
    return _keyring_get(_PASSWORD_KEY)
