import abc
import os
import re
from typing import Callable, Optional

import boto3
from botocore.config import Config

_ENDPOINT_RE = re.compile(r'^[a-zA-Z0-9.\-:]+$')


class BaseStorage(abc.ABC):
    @abc.abstractmethod
    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        ...

    @abc.abstractmethod
    def list_backups(self) -> list:
        ...

    @abc.abstractmethod
    def delete(self, object_key: str) -> None:
        ...

    @abc.abstractmethod
    def test_connection(self) -> bool:
        ...


# ---------------------------------------------------------------------------
# S3-compatible (IONOS, AWS S3, MinIO, Backblaze B2)
# ---------------------------------------------------------------------------

class S3CompatibleStorage(BaseStorage):
    def __init__(self, bucket: str, access_key: str, secret_key: str,
                 endpoint: str = "", region: str = ""):
        if endpoint and not _ENDPOINT_RE.match(endpoint):
            raise ValueError(f"Invalid endpoint — must be a hostname only, got: {endpoint!r}")
        self._bucket = bucket
        kwargs: dict = dict(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )
        if endpoint:
            kwargs["endpoint_url"] = f"https://{endpoint}"
        if region:
            kwargs["region_name"] = region
        self._client = boto3.client("s3", **kwargs)

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        file_size = os.path.getsize(local_path)
        transferred = [0]

        def _cb(n: int) -> None:
            transferred[0] += n
            if progress_cb:
                progress_cb(transferred[0], file_size)

        self._client.upload_file(local_path, self._bucket, object_key, Callback=_cb)

    def list_backups(self) -> list:
        keys = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix="backup-"):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def test_connection(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:
            return False


class IONOSStorage(S3CompatibleStorage):
    """Backward-compat wrapper preserving the old (endpoint, bucket, key, secret) order."""
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        super().__init__(bucket=bucket, access_key=access_key,
                         secret_key=secret_key, endpoint=endpoint)


# ---------------------------------------------------------------------------
# Microsoft OneDrive (Microsoft Graph API with bearer token)
# ---------------------------------------------------------------------------

class OneDriveStorage(BaseStorage):
    _GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, folder_path: str = "BackupSystem"):
        try:
            import requests as _req  # noqa: F401
        except ImportError:
            raise ImportError("OneDrive requires: pip install requests")
        self._token = access_token
        self._folder = folder_path.strip("/")

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _ensure_folder(self) -> None:
        import requests
        url = f"{self._GRAPH}/me/drive/root:/{self._folder}"
        r = requests.get(url, headers=self._h(), timeout=30)
        if r.status_code == 404:
            r2 = requests.post(
                f"{self._GRAPH}/me/drive/root/children",
                headers={**self._h(), "Content-Type": "application/json"},
                json={"name": self._folder, "folder": {}},
                timeout=30,
            )
            r2.raise_for_status()
        elif r.status_code != 200:
            r.raise_for_status()

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        import requests
        self._ensure_folder()
        file_size = os.path.getsize(local_path)
        session_url = (
            f"{self._GRAPH}/me/drive/root:/{self._folder}/{object_key}:/createUploadSession"
        )
        r = requests.post(
            session_url,
            headers={**self._h(), "Content-Type": "application/json"},
            json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
            timeout=30,
        )
        r.raise_for_status()
        upload_url = r.json()["uploadUrl"]

        chunk_size = 10 * 1024 * 1024
        uploaded = 0
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                end = uploaded + len(chunk) - 1
                resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes {uploaded}-{end}/{file_size}",
                        "Content-Length": str(len(chunk)),
                    },
                    data=chunk,
                    timeout=120,
                )
                if resp.status_code not in (200, 201, 202):
                    resp.raise_for_status()
                uploaded += len(chunk)
                if progress_cb:
                    progress_cb(uploaded, file_size)

    def list_backups(self) -> list:
        import requests
        url = f"{self._GRAPH}/me/drive/root:/{self._folder}:/children"
        names = []
        while url:
            r = requests.get(url, headers=self._h(), timeout=30)
            if r.status_code == 404:
                return []
            r.raise_for_status()
            data = r.json()
            names.extend(
                i["name"] for i in data.get("value", [])
                if i["name"].startswith("backup-")
            )
            url = data.get("@odata.nextLink")
        return sorted(names)

    def delete(self, object_key: str) -> None:
        import requests
        url = f"{self._GRAPH}/me/drive/root:/{self._folder}/{object_key}"
        r = requests.delete(url, headers=self._h(), timeout=30)
        if r.status_code != 204:
            r.raise_for_status()

    def test_connection(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self._GRAPH}/me/drive", headers=self._h(), timeout=10)
            return r.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

class GoogleDriveStorage(BaseStorage):
    def __init__(self, credentials_json: str, folder_name: str = "BackupSystem"):
        try:
            from googleapiclient.discovery import build  # noqa: F401
            from google.oauth2.credentials import Credentials  # noqa: F401
        except ImportError:
            raise ImportError(
                "Google Drive requires: pip install google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            )
        self._creds_json = credentials_json
        self._folder_name = folder_name
        self._service = None

    def _svc(self):
        if self._service:
            return self._service
        import json
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        data = json.loads(self._creds_json)
        creds = Credentials(
            token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
        )
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _folder_id(self) -> str:
        svc = self._svc()
        res = svc.files().list(
            q=(
                f"name='{self._folder_name}' and "
                "mimeType='application/vnd.google-apps.folder' and trashed=false"
            ),
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        f = svc.files().create(
            body={"name": self._folder_name,
                  "mimeType": "application/vnd.google-apps.folder"},
            fields="id",
        ).execute()
        return f["id"]

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        from googleapiclient.http import MediaFileUpload
        svc = self._svc()
        fid = self._folder_id()
        # Delete any existing files with this name to maintain overwrite semantics
        existing = svc.files().list(
            q=f"'{fid}' in parents and name='{object_key}' and trashed=false",
            fields="files(id)",
        ).execute()
        for ef in existing.get("files", []):
            svc.files().delete(fileId=ef["id"]).execute()
        file_size = os.path.getsize(local_path)
        media = MediaFileUpload(local_path, resumable=True, chunksize=10 * 1024 * 1024)
        request = svc.files().create(
            body={"name": object_key, "parents": [fid]},
            media_body=media,
            fields="id",
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_cb:
                progress_cb(int(status.resumable_progress), file_size)
        if progress_cb:
            progress_cb(file_size, file_size)

    def list_backups(self) -> list:
        svc = self._svc()
        try:
            fid = self._folder_id()
        except Exception:
            return []
        names = []
        page_token = None
        while True:
            kwargs = dict(
                q=f"'{fid}' in parents and trashed=false and name contains 'backup-'",
                orderBy="name",
                fields="nextPageToken, files(name)",
            )
            if page_token:
                kwargs["pageToken"] = page_token
            res = svc.files().list(**kwargs).execute()
            names.extend(f["name"] for f in res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return sorted(names)

    def delete(self, object_key: str) -> None:
        svc = self._svc()
        fid = self._folder_id()
        res = svc.files().list(
            q=f"'{fid}' in parents and name='{object_key}' and trashed=false",
            fields="files(id)",
        ).execute()
        for f in res.get("files", []):
            svc.files().delete(fileId=f["id"]).execute()

    def test_connection(self) -> bool:
        try:
            self._svc().about().get(fields="user").execute()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Dropbox
# ---------------------------------------------------------------------------

class DropboxStorage(BaseStorage):
    def __init__(self, access_token: str, folder_path: str = "/BackupSystem"):
        try:
            import dropbox as _dbx  # noqa: F401
        except ImportError:
            raise ImportError("Dropbox requires: pip install dropbox")
        self._token = access_token
        self._folder = "/" + folder_path.strip("/")
        self._client = None

    def _dbx(self):
        if self._client is None:
            import dropbox
            self._client = dropbox.Dropbox(self._token)
        return self._client

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        import dropbox
        dbx = self._dbx()
        dest = f"{self._folder}/{object_key}"
        file_size = os.path.getsize(local_path)
        chunk_size = 10 * 1024 * 1024

        with open(local_path, "rb") as f:
            if file_size <= chunk_size:
                dbx.files_upload(f.read(), dest,
                                 mode=dropbox.files.WriteMode.overwrite)
                if progress_cb:
                    progress_cb(file_size, file_size)
                return

            session = dbx.files_upload_session_start(f.read(chunk_size))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=session.session_id, offset=chunk_size
            )
            uploaded = chunk_size
            if progress_cb:
                progress_cb(uploaded, file_size)

            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                if uploaded + len(chunk) >= file_size:
                    dbx.files_upload_session_finish(
                        chunk, cursor,
                        dropbox.files.CommitInfo(
                            path=dest, mode=dropbox.files.WriteMode.overwrite
                        ),
                    )
                else:
                    dbx.files_upload_session_append_v2(chunk, cursor)
                    cursor.offset += len(chunk)
                uploaded += len(chunk)
                if progress_cb:
                    progress_cb(min(uploaded, file_size), file_size)

    def list_backups(self) -> list:
        import dropbox
        try:
            result = self._dbx().files_list_folder(self._folder)
        except dropbox.exceptions.ApiError:
            return []
        return sorted(e.name for e in result.entries
                      if e.name.startswith("backup-"))

    def delete(self, object_key: str) -> None:
        self._dbx().files_delete_v2(f"{self._folder}/{object_key}")

    def test_connection(self) -> bool:
        try:
            self._dbx().users_get_current_account()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Azure Blob Storage
# ---------------------------------------------------------------------------

class AzureBlobStorage(BaseStorage):
    def __init__(self, connection_string: str, container: str):
        try:
            from azure.storage.blob import BlobServiceClient  # noqa: F401
        except ImportError:
            raise ImportError("Azure Blob requires: pip install azure-storage-blob")
        self._conn_str = connection_string
        self._container = container
        self._client = None

    def _svc(self):
        if self._client is None:
            from azure.storage.blob import BlobServiceClient
            self._client = BlobServiceClient.from_connection_string(self._conn_str)
        return self._client

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        file_size = os.path.getsize(local_path)
        blob = self._svc().get_blob_client(
            container=self._container, blob=object_key
        )

        def _hook(current: int, total: Optional[int]) -> None:
            if progress_cb:
                progress_cb(current, file_size)

        with open(local_path, "rb") as f:
            blob.upload_blob(f, overwrite=True, progress_hook=_hook)

    def list_backups(self) -> list:
        cc = self._svc().get_container_client(self._container)
        return sorted(
            b.name for b in cc.list_blobs(name_starts_with="backup-")
        )

    def delete(self, object_key: str) -> None:
        self._svc().get_blob_client(
            container=self._container, blob=object_key
        ).delete_blob()

    def test_connection(self) -> bool:
        try:
            self._svc().get_container_client(
                self._container
            ).get_container_properties()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# SFTP
# ---------------------------------------------------------------------------

class SFTPStorage(BaseStorage):
    def __init__(self, host: str, port: int, username: str, password: str,
                 remote_dir: str = "/backups"):
        try:
            import paramiko as _p  # noqa: F401
        except ImportError:
            raise ImportError("SFTP requires: pip install paramiko")
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._remote_dir = remote_dir.rstrip("/") or "/backups"

    def _connect(self):
        import paramiko
        transport = paramiko.Transport((self._host, self._port))
        transport.connect(username=self._username, password=self._password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        # mkdir -p for nested remote_dir paths
        path = ""
        for part in self._remote_dir.split("/"):
            if not part:
                path = "/"
                continue
            path = f"{path}/{part}".lstrip("/")
            if path != "/":
                path = "/" + path
            try:
                sftp.stat(path)
            except FileNotFoundError:
                sftp.mkdir(path)
        return transport, sftp

    def upload(self, local_path: str, object_key: str,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        file_size = os.path.getsize(local_path)
        transport, sftp = self._connect()
        try:
            def _cb(transferred: int, total: int) -> None:
                if progress_cb:
                    progress_cb(transferred, file_size)
            sftp.put(local_path, f"{self._remote_dir}/{object_key}", callback=_cb)
        finally:
            sftp.close()
            transport.close()

    def list_backups(self) -> list:
        transport, sftp = self._connect()
        try:
            return sorted(
                f for f in sftp.listdir(self._remote_dir)
                if f.startswith("backup-")
            )
        finally:
            sftp.close()
            transport.close()

    def delete(self, object_key: str) -> None:
        transport, sftp = self._connect()
        try:
            sftp.remove(f"{self._remote_dir}/{object_key}")
        finally:
            sftp.close()
            transport.close()

    def test_connection(self) -> bool:
        try:
            transport, sftp = self._connect()
            sftp.close()
            transport.close()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_storage(cfg: dict) -> BaseStorage:
    provider = cfg.get("storage_provider", "ionos")
    if provider in ("ionos", "aws_s3", "minio", "backblaze_b2"):
        return S3CompatibleStorage(
            bucket=cfg.get("s3_bucket", ""),
            access_key=cfg.get("s3_access_key", ""),
            secret_key=cfg.get("s3_secret_key", ""),
            endpoint=cfg.get("s3_endpoint", ""),
            region=cfg.get("s3_region", ""),
        )
    if provider == "onedrive":
        return OneDriveStorage(
            access_token=cfg.get("onedrive_access_token", ""),
            folder_path=cfg.get("onedrive_folder", "BackupSystem"),
        )
    if provider == "google_drive":
        return GoogleDriveStorage(
            credentials_json=cfg.get("gdrive_credentials_json", "{}"),
            folder_name=cfg.get("gdrive_folder", "BackupSystem"),
        )
    if provider == "dropbox":
        return DropboxStorage(
            access_token=cfg.get("dropbox_access_token", ""),
            folder_path=cfg.get("dropbox_folder", "/BackupSystem"),
        )
    if provider == "azure_blob":
        return AzureBlobStorage(
            connection_string=cfg.get("azure_connection_string", ""),
            container=cfg.get("azure_container", "backups"),
        )
    if provider == "sftp":
        return SFTPStorage(
            host=cfg.get("sftp_host", ""),
            port=int(cfg.get("sftp_port") or 22),
            username=cfg.get("sftp_username", ""),
            password=cfg.get("sftp_password", ""),
            remote_dir=cfg.get("sftp_remote_dir", "/backups"),
        )
    raise ValueError(f"Unknown storage provider: {provider!r}")
