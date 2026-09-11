# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-record DEK envelope for sensitive MemoryRecord bodies.

Honest about what this is and is not:

* **This is:** a stdlib SHAKE-256 keystream + HMAC-SHA256 envelope, with a
  random 32-byte DEK. When an OS keystore is available the DEK is wrapped
  by a scoped KEK before the adjacent ``0600`` file is written. Erasing one
  DEK (wrapped or not) shreds that record and does not touch any other.
  Indexes, transcripts and recall hits receive refs, hashes and
  classification — not plaintext.
* **This is not:** AES-256-GCM. Python stdlib has no AES. OS-keystore wrap
  is probed at runtime; missing Secret Service is ``NOT_RUN`` /
  ``unavailable``, not a fake wrap. Live Fedora keystore remains
  **NOT_RUN** until a real image probe runs. See
  :mod:`companion.memory.keystore`.

No extra packages. No npm.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets

from companion.errors import MemoryError
from companion.memory.record import CRYPTO_STATUS_FILE_DEK, CRYPTO_STATUS_KEYSTORE_NOT_RUN

__all__ = [
    "DEK_BYTES",
    "SCHEME",
    "dek_path",
    "generate_dek",
    "open_body",
    "read_dek_material",
    "seal_body",
    "shred_dek",
    "write_dek",
    "write_dek_material",
]

DEK_BYTES = 32
SCHEME = "shake256-hmac-v1"
_NONCE_BYTES = 16


def dek_path(keys_root: Path, record_id: str) -> Path:
    return keys_root / f"{record_id}.dek"


def generate_dek() -> bytes:
    return secrets.token_bytes(DEK_BYTES)


def write_dek_material(keys_root: Path, record_id: str, blob: bytes) -> Path:
    """Key-first: DEK material lands before ciphertext is acknowledged."""
    if not blob:
        raise MemoryError("DEK material must not be empty")
    keys_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        keys_root.chmod(0o700)
    except OSError:
        pass
    path = dek_path(keys_root, record_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, blob)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def write_dek(keys_root: Path, record_id: str, dek: bytes) -> Path:
    if len(dek) != DEK_BYTES:
        raise MemoryError("DEK must be 32 bytes")
    return write_dek_material(keys_root, record_id, dek)


def read_dek_material(keys_root: Path, record_id: str) -> bytes:
    path = dek_path(keys_root, record_id)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            piece = os.read(descriptor, 4096)
            if not piece:
                break
            chunks.append(piece)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def shred_dek(keys_root: Path, record_id: str) -> bool:
    """Overwrite then unlink. Missing is success — already shredded."""
    path = dek_path(keys_root, record_id)
    if not path.exists():
        return False
    try:
        size = path.stat().st_size
        with open(path, "r+b") as handle:
            handle.write(os.urandom(max(size, DEK_BYTES)))
            handle.flush()
            os.fsync(handle.fileno())
        path.unlink()
    except OSError as exc:
        raise MemoryError(f"could not shred DEK for {record_id}: {exc}") from exc
    return True


def seal_body(
    plaintext: bytes,
    dek: bytes,
    *,
    keystore_wrap: str = CRYPTO_STATUS_KEYSTORE_NOT_RUN,
) -> dict[str, object]:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    stream = hashlib.shake_256(dek + nonce).digest(len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(dek, nonce + ciphertext, hashlib.sha256).digest()
    return {
        "kind": "wrapped",
        "scheme": SCHEME,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "iv": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "cryptoStatus": CRYPTO_STATUS_FILE_DEK,
        "keystoreWrap": keystore_wrap,
    }


def open_body(sealed: dict[str, object], dek: bytes) -> bytes:
    if str(sealed.get("scheme") or "") != SCHEME:
        raise MemoryError("sensitive body uses an unknown wrap scheme")
    try:
        nonce = base64.b64decode(str(sealed["iv"]))
        ciphertext = base64.b64decode(str(sealed["ciphertext"]))
        tag = base64.b64decode(str(sealed["tag"]))
    except (KeyError, ValueError) as exc:
        raise MemoryError("sensitive body wrap is incomplete") from exc
    expected = hmac.new(dek, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise MemoryError("sensitive body HMAC failed; DEK missing or shredded")
    stream = hashlib.shake_256(dek + nonce).digest(len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))
