import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


def test_load_config_returns_defaults_when_no_file(tmp_path):
    with patch("config.config_manager._config_path", return_value=tmp_path / "config.json"):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folders"] == []
    assert cfg["retention_count"] == 30
    assert cfg["schedule_type"] == "daily"
    assert cfg["storage_provider"] == "ionos"


def test_save_and_load_roundtrip(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("config.config_manager._config_path", return_value=config_file), \
         patch("config.config_manager._keyring_set", return_value=True), \
         patch("config.config_manager._keyring_get", return_value=None), \
         patch("config.config_manager._keyring_delete"):
        from config.config_manager import load_config, save_config
        cfg = load_config()
        cfg["folders"] = ["C:\\Users\\Test\\Docs"]
        cfg["retention_count"] = 7
        save_config(cfg)
        loaded = load_config()
    assert loaded["folders"] == ["C:\\Users\\Test\\Docs"]
    assert loaded["retention_count"] == 7


def test_load_config_merges_missing_keys(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"folders": ["C:\\\\old"], "retention_count": 10}')
    with patch("config.config_manager._config_path", return_value=config_file), \
         patch("config.config_manager._keyring_get", return_value=None):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folders"] == ["C:\\old"]
    assert cfg["retention_count"] == 10
    assert cfg["schedule_type"] == "daily"  # default still present


def test_load_config_migrates_old_folder_keys(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"folder1": "C:\\\\Docs", "folder2": "D:\\\\Photos"}'
    )
    with patch("config.config_manager._config_path", return_value=config_file), \
         patch("config.config_manager._keyring_get", return_value=None):
        from config.config_manager import load_config
        cfg = load_config()
    assert "C:\\Docs" in cfg["folders"]
    assert "D:\\Photos" in cfg["folders"]
    assert "folder1" not in cfg
    assert "folder2" not in cfg


def test_load_config_migrates_ionos_to_s3_keys(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"ionos_endpoint": "s3.example.com", "ionos_bucket": "my-bucket"}'
    )
    with patch("config.config_manager._config_path", return_value=config_file), \
         patch("config.config_manager._keyring_get", return_value=None):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["s3_endpoint"] == "s3.example.com"
    assert cfg["s3_bucket"] == "my-bucket"
    assert "ionos_endpoint" not in cfg
    assert cfg["storage_provider"] == "ionos"


def test_load_config_handles_corrupt_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{ not valid json }")
    with patch("config.config_manager._config_path", return_value=config_file), \
         patch("config.config_manager._keyring_get", return_value=None):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["retention_count"] == 30  # fell back to defaults
