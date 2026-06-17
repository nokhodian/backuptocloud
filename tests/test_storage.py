import os
import pytest
from unittest.mock import MagicMock, patch, call
from core.storage import IONOSStorage


@pytest.fixture
def mock_boto_client():
    with patch("core.storage.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        yield mock_client


def make_storage(mock_boto_client):
    return IONOSStorage("s3.example.com", "my-bucket", "ACCESS", "SECRET")


def test_list_backups_returns_sorted_keys(mock_boto_client):
    mock_boto_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "backup-2026-06-17-02-00.zip.enc"},
            {"Key": "backup-2026-06-15-02-00.zip.enc"},
            {"Key": "backup-2026-06-16-02-00.zip.enc"},
        ]
    }
    storage = make_storage(mock_boto_client)
    keys = storage.list_backups()
    assert keys == [
        "backup-2026-06-15-02-00.zip.enc",
        "backup-2026-06-16-02-00.zip.enc",
        "backup-2026-06-17-02-00.zip.enc",
    ]


def test_list_backups_returns_empty_when_no_objects(mock_boto_client):
    mock_boto_client.list_objects_v2.return_value = {}
    storage = make_storage(mock_boto_client)
    assert storage.list_backups() == []


def test_delete_calls_delete_object(mock_boto_client):
    storage = make_storage(mock_boto_client)
    storage.delete("backup-2026-06-15-02-00.zip.enc")
    mock_boto_client.delete_object.assert_called_once_with(
        Bucket="my-bucket", Key="backup-2026-06-15-02-00.zip.enc"
    )


def test_test_connection_returns_true_on_success(mock_boto_client):
    storage = make_storage(mock_boto_client)
    assert storage.test_connection() is True
    mock_boto_client.head_bucket.assert_called_once_with(Bucket="my-bucket")


def test_test_connection_returns_false_on_error(mock_boto_client):
    mock_boto_client.head_bucket.side_effect = Exception("Connection refused")
    storage = make_storage(mock_boto_client)
    assert storage.test_connection() is False


def test_upload_calls_upload_file(mock_boto_client, tmp_path):
    test_file = tmp_path / "test.zip.enc"
    test_file.write_bytes(b"encrypted data")
    storage = make_storage(mock_boto_client)
    storage.upload(str(test_file), "backup-2026-06-17-02-00.zip.enc")
    mock_boto_client.upload_file.assert_called_once()
    args, kwargs = mock_boto_client.upload_file.call_args
    assert args[0] == str(test_file)
    assert args[1] == "my-bucket"
    assert args[2] == "backup-2026-06-17-02-00.zip.enc"
