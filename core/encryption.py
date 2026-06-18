# core/encryption.py
import math
import os
import struct
import tempfile
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
    # Compute total chunk count upfront (one stat call) so we can bind both the
    # chunk index AND the total into each chunk's AAD.  This detects both
    # reordering and truncation attacks on stored ciphertext.
    file_size = os.path.getsize(src_path)
    total_chunks = math.ceil(file_size / _CHUNK_SIZE) if file_size > 0 else 0

    salt = os.urandom(_SALT_SIZE)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    with open(src_path, "rb") as inp, open(dst_path, "wb") as out:
        out.write(salt)
        # Write placeholder for chunk count; will seek back and overwrite.
        chunk_count_offset = out.tell()
        out.write(struct.pack(">I", 0))

        count = 0
        while True:
            chunk = inp.read(_CHUNK_SIZE)
            if not chunk:
                break
            nonce = os.urandom(_NONCE_SIZE)
            # AAD binds (chunk_index, total_chunks) so both reordering and
            # truncation of the ciphertext stream are detected on decrypt.
            aad = struct.pack(">II", count, total_chunks)
            ciphertext = aesgcm.encrypt(nonce, chunk, aad)
            out.write(nonce)
            out.write(struct.pack(">I", len(ciphertext)))
            out.write(ciphertext)
            count += 1

        # Patch the placeholder with the real chunk count.
        out.seek(chunk_count_offset)
        out.write(struct.pack(">I", count))


def decrypt_file(src_path: str, dst_path: str, password: str) -> None:
    # Decrypt to an unpredictable temp file in the same directory as dst_path so
    # os.replace() is atomic (same filesystem). Rename only after all chunks
    # authenticate; delete the temp file on any error.
    dst_dir = os.path.dirname(dst_path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dst_dir)
    try:
        with open(src_path, "rb") as inp:
            salt = inp.read(_SALT_SIZE)
            num_chunks = struct.unpack(">I", inp.read(4))[0]
            key = _derive_key(password, salt)
            aesgcm = AESGCM(key)

            with os.fdopen(tmp_fd, "wb") as out:
                tmp_fd = None  # fdopen took ownership
                for chunk_index in range(num_chunks):
                    nonce = inp.read(_NONCE_SIZE)
                    chunk_len = struct.unpack(">I", inp.read(4))[0]
                    ciphertext = inp.read(chunk_len)
                    # AAD must match encrypt_file: (chunk_index, total_chunks).
                    aad = struct.pack(">II", chunk_index, num_chunks)
                    out.write(aesgcm.decrypt(nonce, ciphertext, aad))

        os.replace(tmp_path, dst_path)
    except Exception:
        if tmp_fd is not None:
            os.close(tmp_fd)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
