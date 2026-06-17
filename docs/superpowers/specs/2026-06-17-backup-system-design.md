# Backup System — Design Spec
Date: 2026-06-17

## Overview

A Windows desktop application that backs up two user-selected folders, compresses and AES-256 encrypts them into a timestamped archive, and uploads to IONOS Object Storage. Supports scheduled automatic backups, manual triggers, configurable retention, and a system tray icon alongside a full GUI window.

---

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| UI framework | PyQt6 |
| Cloud upload | boto3 (S3-compatible, points to IONOS endpoint) |
| Encryption | `cryptography` library (AES-256-GCM) |
| Scheduling | Background thread with `schedule` library |
| Packaging | PyInstaller → single `.exe` |
| Config storage | `config.json` in `%APPDATA%\BackupSystem\` |

---

## Architecture

Four layers with single responsibilities:

1. **UI Layer** — PyQt6 main window + system tray icon
2. **Backup Engine** — zip → encrypt → upload → prune
3. **Scheduler** — background thread, fires engine on interval
4. **Config Store** — JSON file persisting all settings

---

## File Structure

```
backupsystem/
├── main.py                  # Entry point, launches PyQt6 app
├── ui/
│   ├── main_window.py       # Main window widget
│   └── tray.py              # System tray icon + context menu
├── core/
│   ├── backup_engine.py     # zip → encrypt → upload → prune
│   ├── scheduler.py         # Background scheduler thread
│   ├── encryption.py        # AES-256-GCM encrypt/decrypt helpers
│   └── storage.py           # boto3 wrapper for IONOS upload/list/delete
├── config/
│   └── config_manager.py    # Read/write config.json
├── assets/
│   └── icon.ico             # Tray + window icon
└── requirements.txt
```

---

## UI

### Main Window Sections

1. **Backup Folders** — two Browse buttons, one path field each
2. **IONOS Credentials** — endpoint URL, bucket name, access key, secret key (masked)
3. **Settings row** — schedule dropdown (Hourly / Daily at HH:MM / Weekly), retention count input, encryption password field
4. **Status panel** — last backup result (success/fail), timestamp, size uploaded
5. **Log panel** — scrollable monospace log of the last run's output
6. **Action buttons** — "Backup Now" (blue, prominent), "Save Settings", "Test Connection"

### System Tray

- Icon in Windows taskbar notification area
- Right-click menu: **Backup Now** | **Open** | **Quit**
- Balloon/toast notifications on backup success or failure

---

## Backup Engine Flow

For each backup run:

1. Collect both configured folder paths (skip any that don't exist, log warning)
2. Zip contents into a temp file: `backup-YYYY-MM-DD-HH-MM.zip`
3. AES-256-GCM encrypt the zip using the user's password → `backup-YYYY-MM-DD-HH-MM.zip.enc`
4. Delete the unencrypted temp zip
5. Upload `.zip.enc` to IONOS bucket via boto3 with progress callback → updates UI progress bar
6. List all objects in bucket matching `backup-*.zip.enc`, sorted by date
7. Delete oldest objects beyond the configured retention count
8. Emit result event (success/failure, bytes uploaded, duration) to UI and log

---

## Encryption

- Algorithm: AES-256-GCM (authenticated encryption — detects corruption or wrong password)
- Key derivation: PBKDF2-HMAC-SHA256, 390,000 iterations, random 16-byte salt stored in file header
- File format: `[16-byte salt][12-byte nonce][ciphertext][16-byte auth tag]`
- Password stored nowhere — only used at runtime when backup runs

---

## Scheduler

- Runs in a `threading.Thread` (daemon=True) alongside the Qt event loop
- Options: Hourly, Daily (with configurable time HH:MM), Weekly (day + time)
- On wake: calls backup engine, emits Qt signal to update UI (thread-safe)
- Persists next-run time so a restart doesn't skip a scheduled backup

---

## Config (config.json)

Stored at `%APPDATA%\BackupSystem\config.json`:

```json
{
  "folder1": "C:\\Users\\You\\Documents",
  "folder2": "C:\\Users\\You\\Projects",
  "ionos_endpoint": "s3-eu-central-1.ionoscloud.com",
  "ionos_bucket": "my-backups",
  "ionos_access_key": "...",
  "ionos_secret_key": "...",
  "schedule_type": "daily",
  "schedule_time": "02:00",
  "retention_count": 30,
  "last_run": "2026-06-17T02:00:00"
}
```

Credentials stored in plaintext in `%APPDATA%` (user-only directory). Encryption password is **never** stored.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| IONOS unreachable | Retry 3× with exponential backoff (5s, 15s, 45s), then fail with log entry + tray notification |
| Wrong encryption password | AES-GCM auth tag mismatch caught, user prompted to re-enter |
| Folder not found | Log warning, skip that folder, continue with the other |
| Disk full during zip | Catch `OSError`, clean up temp file, log error |
| Missing credentials | Validate on "Save Settings" and "Backup Now" — show inline error before attempting |
| Backup in progress | "Backup Now" button disabled during a run to prevent double-trigger |

---

## Packaging

- PyInstaller one-file mode: `pyinstaller --onefile --windowed --icon=assets/icon.ico main.py`
- Output: `dist/BackupSystem.exe` — no Python installation required on target machine
- Bundle size: ~40–60 MB expected
- Windows 10/11 target

---

## Out of Scope

- macOS / Linux support
- Incremental / differential backups (full zip per run)
- Restore functionality (user downloads from IONOS manually)
- Multiple backup profiles
- Email notifications
