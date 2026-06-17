# core/encryption.py
import os
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_SALT_SIZE = 16
_NONCE_SIZE = 12
_ITERATIONS = 390_000
_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(src_path: str, dst_path: str, password: str) -> None:
    salt = os.urandom(_SALT_SIZE)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    # First pass: count chunks
    chunks = []
    with open(src_path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)

    with open(dst_path, "wb") as out:
        # Write header: salt + chunk count
        out.write(salt)
        out.write(struct.pack(">I", len(chunks)))

        for chunk in chunks:
            nonce = os.urandom(_NONCE_SIZE)
            ciphertext = aesgcm.encrypt(nonce, chunk, None)
            out.write(nonce)
            out.write(struct.pack(">I", len(ciphertext)))
            out.write(ciphertext)


def decrypt_file(src_path: str, dst_path: str, password: str) -> None:
    with open(src_path, "rb") as inp:
        salt = inp.read(_SALT_SIZE)
        num_chunks = struct.unpack(">I", inp.read(4))[0]
        key = _derive_key(password, salt)
        aesgcm = AESGCM(key)

        with open(dst_path, "wb") as out:
            for _ in range(num_chunks):
                nonce = inp.read(_NONCE_SIZE)
                chunk_len = struct.unpack(">I", inp.read(4))[0]
                ciphertext = inp.read(chunk_len)
                plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                out.write(plaintext)
