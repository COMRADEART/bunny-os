# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""OS-keystore probe and per-record DEK wrap.

ADR 0008 wants a random per-record DEK wrapped by a scoped OS-keystore KEK.
This module does that when a real backend is present, and degrades when it
is not.

* **Live probe:** looks for ``secret-tool`` (Linux Secret Service CLI) and a
  D-Bus session. Missing tools, missing bus, or a daemon that will not talk
  are labelled ``NOT_RUN`` / ``unavailable``. The probe never invents
  success.
* **Wrap:** SHAKE-256 + HMAC-SHA256 of the 32-byte DEK under that KEK, same
  stdlib envelope as body sealing. Python's stdlib has no AES; this is
  **not** AES-256-GCM / AES-KW and is not labelled as such.
* **Fallback:** write the DEK as an adjacent ``0600`` file, as Memory Core
  already does. The companion does not crash.
* **Injected backend:** tests supply an in-memory KEK store. That is a
  fixture, not a Fedora Secret Service PASS.

Copying ``keys/`` + ``records/`` recovers plaintext only on the fallback
path. When wrap actually ran, the on-disk DEK file is a wrap document and
the KEK is not in the tree.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
import secrets
import shutil
import subprocess
from typing import Mapping, Protocol

from companion.errors import MemoryError
from companion.memory.crypto import DEK_BYTES, SCHEME
from companion.memory.record import (
    CRYPTO_STATUS_KEYSTORE_NOT_RUN,
    CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
    CRYPTO_STATUS_KEYSTORE_WRAPPED,
)

__all__ = [
    "KEK_SCOPE",
    "WRAP_KIND",
    "InjectedKeystore",
    "KeystoreBackend",
    "KeystoreProbe",
    "SecretToolKeystore",
    "dek_blob_is_wrapped",
    "encode_wrapped_dek",
    "injected_probe",
    "materialize_dek",
    "probe_os_keystore",
    "unavailable_probe",
    "unwrap_dek",
    "wrap_dek",
]

KEK_SCOPE = "bunny-os.memory.kek"
WRAP_KIND = "keystore-wrapped-dek"
_WRAP_DOMAIN = b"dek-wrap-v1"
_NONCE_BYTES = 16
_SECRET_TOOL_TIMEOUT = 8
_LABEL = "Bunny OS Memory KEK"


class KeystoreBackend(Protocol):
    """Something that can hold the scoped KEK. Tests inject this."""

    name: str

    def get_or_create_kek(self, scope: str) -> bytes: ...

    def get_kek(self, scope: str) -> bytes | None: ...


@dataclass(frozen=True)
class KeystoreProbe:
    """Honest result of looking for an OS keystore. Not a PASS badge."""

    available: bool
    backend_name: str
    status: str
    detail: str
    secret_tool_path: str | None = None
    dbus_session: bool = False
    live_fedora: str = "NOT_RUN"
    aes_gcm: str = "NOT VERIFIED"

    def to_json(self) -> dict[str, object]:
        return {
            "available": self.available,
            "backend": self.backend_name,
            "keystoreWrap": self.status,
            "detail": self.detail,
            "secretToolPath": self.secret_tool_path,
            "dbusSession": self.dbus_session,
            "keystoreLiveFedora": self.live_fedora,
            "keystoreAesGcm": f"os-keystore-wrap {self.aes_gcm}",
        }


class InjectedKeystore:
    """In-memory KEK store for tests. Not an OS keystore."""

    name = "injected"

    def __init__(self, store: dict[str, bytes] | None = None) -> None:
        self.store = store if store is not None else {}

    def get_or_create_kek(self, scope: str) -> bytes:
        existing = self.store.get(scope)
        if existing is not None:
            if len(existing) != DEK_BYTES:
                raise MemoryError("injected KEK must be 32 bytes")
            return existing
        kek = secrets.token_bytes(DEK_BYTES)
        self.store[scope] = kek
        return kek

    def get_kek(self, scope: str) -> bytes | None:
        kek = self.store.get(scope)
        if kek is None:
            return None
        if len(kek) != DEK_BYTES:
            raise MemoryError("injected KEK must be 32 bytes")
        return kek


class SecretToolKeystore:
    """Linux Secret Service via ``secret-tool``. Used only after a live probe."""

    name = "secret-tool"

    def __init__(self, binary: str) -> None:
        self.binary = binary

    def get_or_create_kek(self, scope: str) -> bytes:
        existing = self.get_kek(scope)
        if existing is not None:
            return existing
        kek = secrets.token_bytes(DEK_BYTES)
        self._store(scope, kek)
        roundtrip = self.get_kek(scope)
        if roundtrip != kek:
            raise MemoryError("secret-tool stored a KEK that would not round-trip")
        return kek

    def get_kek(self, scope: str) -> bytes | None:
        result = _run_secret_tool(
            self.binary,
            "lookup",
            "application",
            "bunny-os",
            "service",
            "bunny-memory-kek",
            "scope",
            scope,
        )
        if result.returncode != 0:
            if _looks_like_missing_secret(result):
                return None
            raise MemoryError(
                "secret-tool lookup failed; OS-keystore is not usable"
            )
        try:
            kek = bytes.fromhex(result.stdout.strip())
        except ValueError as exc:
            raise MemoryError("secret-tool returned a KEK that is not hex") from exc
        if len(kek) != DEK_BYTES:
            raise MemoryError("secret-tool returned a KEK that is not 32 bytes")
        return kek

    def _store(self, scope: str, kek: bytes) -> None:
        result = _run_secret_tool(
            self.binary,
            "store",
            "--label",
            _LABEL,
            "application",
            "bunny-os",
            "service",
            "bunny-memory-kek",
            "scope",
            scope,
            stdin=kek.hex(),
        )
        if result.returncode != 0:
            raise MemoryError("secret-tool could not store the scoped KEK")


def probe_os_keystore() -> tuple[KeystoreProbe, KeystoreBackend | None]:
    """Runtime probe. Absence is NOT_RUN / unavailable, never a fake wrap."""
    dbus_session = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    path = shutil.which("secret-tool")
    if path is None:
        return (
            KeystoreProbe(
                available=False,
                backend_name="none",
                status=CRYPTO_STATUS_KEYSTORE_NOT_RUN,
                detail="secret-tool not on PATH; OS-keystore wrap not attempted",
                secret_tool_path=None,
                dbus_session=dbus_session,
            ),
            None,
        )
    if not dbus_session:
        return (
            KeystoreProbe(
                available=False,
                backend_name="secret-tool",
                status=CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
                detail=(
                    "secret-tool is on PATH but DBUS_SESSION_BUS_ADDRESS is "
                    "unset; Secret Service was not claimed as present"
                ),
                secret_tool_path=path,
                dbus_session=False,
            ),
            None,
        )
    result = _run_secret_tool(
        path,
        "lookup",
        "application",
        "bunny-os",
        "service",
        "bunny-memory-kek",
        "scope",
        "bunny-os-probe-canary",
    )
    if _looks_like_bus_failure(result):
        return (
            KeystoreProbe(
                available=False,
                backend_name="secret-tool",
                status=CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
                detail=(
                    "secret-tool could not talk to Secret Service "
                    f"(exit {result.returncode}); wrap not claimed"
                ),
                secret_tool_path=path,
                dbus_session=True,
            ),
            None,
        )
    if not (
        result.returncode == 0
        or result.returncode == 1
        or _looks_like_missing_secret(result)
    ):
        return (
            KeystoreProbe(
                available=False,
                backend_name="secret-tool",
                status=CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
                detail=(
                    "secret-tool lookup returned an unexpected status "
                    f"(exit {result.returncode}); wrap not claimed"
                ),
                secret_tool_path=path,
                dbus_session=True,
            ),
            None,
        )
    return (
        KeystoreProbe(
            available=True,
            backend_name="secret-tool",
            status=CRYPTO_STATUS_KEYSTORE_WRAPPED,
            detail="secret-tool answered; scoped KEK wrap is available",
            secret_tool_path=path,
            dbus_session=True,
            live_fedora="NOT_RUN",
        ),
        SecretToolKeystore(path),
    )


def injected_probe(backend: KeystoreBackend) -> KeystoreProbe:
    return KeystoreProbe(
        available=True,
        backend_name=backend.name,
        status=CRYPTO_STATUS_KEYSTORE_WRAPPED,
        detail=f"injected keystore backend {backend.name!r}; not a live OS probe",
        secret_tool_path=None,
        dbus_session=False,
        live_fedora="NOT_RUN",
    )


def unavailable_probe(*, detail: str = "injected keystore-absent fixture") -> KeystoreProbe:
    return KeystoreProbe(
        available=False,
        backend_name="none",
        status=CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
        detail=detail,
        secret_tool_path=None,
        dbus_session=False,
        live_fedora="NOT_RUN",
    )


def wrap_dek(dek: bytes, kek: bytes, *, scope: str = KEK_SCOPE) -> dict[str, object]:
    if len(dek) != DEK_BYTES:
        raise MemoryError("DEK must be 32 bytes")
    if len(kek) != DEK_BYTES:
        raise MemoryError("KEK must be 32 bytes")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    stream = hashlib.shake_256(kek + _WRAP_DOMAIN + nonce).digest(len(dek))
    ciphertext = bytes(a ^ b for a, b in zip(dek, stream))
    tag = hmac.new(kek, _WRAP_DOMAIN + nonce + ciphertext, hashlib.sha256).digest()
    return {
        "kind": WRAP_KIND,
        "scheme": SCHEME,
        "kekScope": scope,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "iv": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def unwrap_dek(document: Mapping[str, object], kek: bytes) -> bytes:
    if str(document.get("kind") or "") != WRAP_KIND:
        raise MemoryError("DEK wrap document has an unknown kind")
    if str(document.get("scheme") or "") != SCHEME:
        raise MemoryError("DEK wrap uses an unknown scheme")
    if len(kek) != DEK_BYTES:
        raise MemoryError("KEK must be 32 bytes")
    try:
        nonce = base64.b64decode(str(document["iv"]))
        ciphertext = base64.b64decode(str(document["ciphertext"]))
        tag = base64.b64decode(str(document["tag"]))
    except (KeyError, ValueError) as exc:
        raise MemoryError("DEK wrap document is incomplete") from exc
    expected = hmac.new(kek, _WRAP_DOMAIN + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise MemoryError("DEK wrap HMAC failed; KEK missing or wrong")
    stream = hashlib.shake_256(kek + _WRAP_DOMAIN + nonce).digest(len(ciphertext))
    dek = bytes(a ^ b for a, b in zip(ciphertext, stream))
    if len(dek) != DEK_BYTES:
        raise MemoryError("unwrapped DEK is not 32 bytes")
    return dek


def encode_wrapped_dek(document: Mapping[str, object]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def materialize_dek(blob: bytes, backend: KeystoreBackend | None) -> bytes:
    """Turn on-disk DEK material into the 32-byte record DEK."""
    if blob.startswith(b"{"):
        try:
            document = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryError("DEK wrap document is not JSON") from exc
        if not isinstance(document, dict):
            raise MemoryError("DEK wrap document is not a JSON object")
        if backend is None:
            raise MemoryError(
                "DEK is keystore-wrapped but OS-keystore is unavailable; "
                "body cannot be opened"
            )
        scope = str(document.get("kekScope") or KEK_SCOPE)
        kek = backend.get_kek(scope)
        if kek is None:
            raise MemoryError("scoped KEK is missing from the OS keystore")
        return unwrap_dek(document, kek)
    if len(blob) != DEK_BYTES:
        raise MemoryError("DEK file is neither a 32-byte key nor a wrap document")
    return blob


def dek_blob_is_wrapped(blob: bytes) -> bool:
    return blob.startswith(b"{")


def _run_secret_tool(
    binary: str, *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [binary, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_SECRET_TOOL_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MemoryError("secret-tool disappeared during use") from exc
    except subprocess.TimeoutExpired as exc:
        raise MemoryError("secret-tool timed out") from exc


def _stderr_text(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stderr or ''} {result.stdout or ''}".lower()


def _looks_like_bus_failure(result: subprocess.CompletedProcess[str]) -> bool:
    text = _stderr_text(result)
    needles = (
        "cannot autolaunch",
        "no such file",
        "connection refused",
        "serviceunknown",
        "not connected",
        "dbus",
        "failed to connect",
        "timed out",
    )
    if result.returncode == 0:
        return False
    if _looks_like_missing_secret(result):
        return False
    return any(needle in text for needle in needles) or result.returncode < 0


def _looks_like_missing_secret(result: subprocess.CompletedProcess[str]) -> bool:
    text = _stderr_text(result)
    return any(
        needle in text
        for needle in (
            "no such secret",
            "not found",
            "doesn't exist",
            "does not exist",
            "cannot find",
        )
    )
