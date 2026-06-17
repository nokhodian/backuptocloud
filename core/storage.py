import os
from typing import Callable, Optional

import boto3
from botocore.config import Config


class IONOSStorage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )

    def upload(
        self,
        local_path: str,
        object_key: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        file_size = os.path.getsize(local_path)
        transferred = [0]

        def _callback(bytes_amount: int) -> None:
            transferred[0] += bytes_amount
            if progress_cb:
                progress_cb(transferred[0], file_size)

        self._client.upload_file(local_path, self._bucket, object_key, Callback=_callback)

    def list_backups(self) -> list:
        response = self._client.list_objects_v2(Bucket=self._bucket, Prefix="backup-")
        contents = response.get("Contents", [])
        return sorted(obj["Key"] for obj in contents)

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def test_connection(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:
            return False
