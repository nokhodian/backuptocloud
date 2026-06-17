import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_SALT_SIZE = 16
_NONCE_SIZE = 12
_ITERATIONS = 390_000


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
    nonce = os.urandom(_NONCE_SIZE)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    with open(src_path, "rb") as f:
        plaintext = f.read()

    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    with open(dst_path, "wb") as f:
        f.write(salt + nonce + ciphertext)


def decrypt_file(src_path: str, dst_path: str, password: str) -> None:
    with open(src_path, "rb") as f:
        data = f.read()

    salt = data[:_SALT_SIZE]
    nonce = data[_SALT_SIZE:_SALT_SIZE + _NONCE_SIZE]
    ciphertext = data[_SALT_SIZE + _NONCE_SIZE:]

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    with open(dst_path, "wb") as f:
        f.write(plaintext)
