import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


def test_load_config_returns_defaults_when_no_file(tmp_path):
    with patch("config.config_manager._config_path", return_value=tmp_path / "config.json"):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folder1"] == ""
    assert cfg["retention_count"] == 30
    assert cfg["schedule_type"] == "daily"


def test_save_and_load_roundtrip(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("config.config_manager._config_path", return_value=config_file):
        from config.config_manager import load_config, save_config
        cfg = load_config()
        cfg["folder1"] = "C:\\Users\\Test\\Docs"
        cfg["retention_count"] = 7
        save_config(cfg)
        loaded = load_config()
    assert loaded["folder1"] == "C:\\Users\\Test\\Docs"
    assert loaded["retention_count"] == 7


def test_load_config_merges_missing_keys(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"folder1": "C:\\\\old"}')
    with patch("config.config_manager._config_path", return_value=config_file):
        from config.config_manager import load_config
        cfg = load_config()
    assert cfg["folder1"] == "C:\\old"
    assert cfg["retention_count"] == 30  # default still present
