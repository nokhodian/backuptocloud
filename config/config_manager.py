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

# All keys whose values live in the OS keyring, never on disk.
_CREDENTIAL_KEYS = (
    "s3_access_key",
    "s3_secret_key",
    "onedrive_access_token",
    "gdrive_credentials_json",
    "dropbox_access_token",
    "azure_connection_string",
    "sftp_password",
)
_PASSWORD_KEY = "encryption_password"

DEFAULT_CONFIG: dict = {
    "folders": [],
    # Storage provider selection
    "storage_provider": "ionos",
    # S3-compatible (IONOS, AWS S3, MinIO, Backblaze B2)
    "s3_endpoint": "",      # hostname only; empty = AWS default
    "s3_region": "",        # e.g. "us-east-1"
    "s3_bucket": "",
    "s3_access_key": "",    # keyring
    "s3_secret_key": "",    # keyring
    # Microsoft OneDrive
    "onedrive_folder": "BackupSystem",
    "onedrive_access_token": "",  # keyring
    # Google Drive
    "gdrive_folder": "BackupSystem",
    "gdrive_credentials_json": "",  # keyring (full token JSON)
    # Dropbox
    "dropbox_folder": "/BackupSystem",
    "dropbox_access_token": "",  # keyring
    # Azure Blob Storage
    "azure_container": "backups",
    "azure_connection_string": "",  # keyring
    # SFTP
    "sftp_host": "",
    "sftp_port": "22",
    "sftp_username": "",
    "sftp_remote_dir": "/backups",
    "sftp_password": "",  # keyring
    # Backup settings
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
    import logging
    path = _config_path()
    if not path.exists():
        cfg = dict(DEFAULT_CONFIG)
    else:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cfg = {**DEFAULT_CONFIG, **data}
        except (json.JSONDecodeError, OSError) as exc:
            logging.warning("Config file unreadable (%s) — starting with defaults", exc)
            cfg = dict(DEFAULT_CONFIG)

    # Migrate old folder1/folder2 keys to the folders list.
    if "folder1" in cfg or "folder2" in cfg:
        migrated = [f for f in [cfg.pop("folder1", ""), cfg.pop("folder2", "")] if f]
        if migrated and not cfg.get("folders"):
            cfg["folders"] = migrated

    if not isinstance(cfg.get("folders"), list):
        cfg["folders"] = []

    # Migrate old ionos_ JSON keys to new s3_ prefix.
    if "ionos_endpoint" in cfg or "ionos_bucket" in cfg:
        if not cfg.get("storage_provider"):
            cfg["storage_provider"] = "ionos"
        if not cfg.get("s3_endpoint"):
            cfg["s3_endpoint"] = cfg.pop("ionos_endpoint", "")
        else:
            cfg.pop("ionos_endpoint", None)
        if not cfg.get("s3_bucket"):
            cfg["s3_bucket"] = cfg.pop("ionos_bucket", "")
        else:
            cfg.pop("ionos_bucket", None)

    # Migrate old ionos_ keyring keys to new s3_ prefix.
    for old_key, new_key in [("ionos_access_key", "s3_access_key"),
                               ("ionos_secret_key", "s3_secret_key")]:
        old_val = _keyring_get(old_key)
        if old_val and not _keyring_get(new_key):
            _keyring_set(new_key, old_val)
            _keyring_delete(old_key)

    # Load all credential keys from keyring.
    for key in _CREDENTIAL_KEYS:
        value = _keyring_get(key)
        if value is not None:
            cfg[key] = value

    return cfg


def save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    excluded = set(_CREDENTIAL_KEYS) | {"password"}
    safe = {k: v for k, v in config.items() if k not in excluded}

    for key in _CREDENTIAL_KEYS:
        value = config.get(key, "")
        if value:
            if not _keyring_set(key, value):
                raise RuntimeError(
                    "Secure credential storage (keyring) is unavailable.\n"
                    "Cannot save credentials safely.\n"
                    "Please ensure the 'keyring' package and a keyring backend are installed."
                )
        else:
            _keyring_delete(key)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2)


def save_encryption_password(password: str) -> bool:
    if not password:
        _keyring_delete(_PASSWORD_KEY)
        return True
    return _keyring_set(_PASSWORD_KEY, password)


def load_encryption_password() -> str | None:
    return _keyring_get(_PASSWORD_KEY)
