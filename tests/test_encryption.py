import os
import pytest
from cryptography.exceptions import InvalidTag
from core.encryption import encrypt_file, decrypt_file


def test_encrypt_decrypt_roundtrip(tmp_path):
    src = tmp_path / "plain.txt"
    enc = tmp_path / "plain.txt.enc"
    dec = tmp_path / "plain_restored.txt"
    src.write_bytes(b"Hello, backup world!")

    encrypt_file(str(src), str(enc), "my-secret-password")
    decrypt_file(str(enc), str(dec), "my-secret-password")

    assert dec.read_bytes() == b"Hello, backup world!"


def test_wrong_password_raises(tmp_path):
    src = tmp_path / "data.bin"
    enc = tmp_path / "data.bin.enc"
    dec = tmp_path / "data_out.bin"
    src.write_bytes(b"sensitive data")

    encrypt_file(str(src), str(enc), "correct-password")

    with pytest.raises(InvalidTag):
        decrypt_file(str(enc), str(dec), "wrong-password")


def test_encrypted_file_has_salt_nonce_prefix(tmp_path):
    src = tmp_path / "file.txt"
    enc = tmp_path / "file.txt.enc"
    src.write_bytes(b"data")

    encrypt_file(str(src), str(enc), "pass")

    # 16 salt + 12 nonce = 28 bytes header minimum
    assert enc.stat().st_size > 28


def test_different_runs_produce_different_ciphertext(tmp_path):
    src = tmp_path / "file.txt"
    src.write_bytes(b"same content")
    enc1 = tmp_path / "enc1.bin"
    enc2 = tmp_path / "enc2.bin"

    encrypt_file(str(src), str(enc1), "pass")
    encrypt_file(str(src), str(enc2), "pass")

    assert enc1.read_bytes() != enc2.read_bytes()
