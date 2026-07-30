"""Cryptographic executor boundary.

Bunny OS implements no cipher, mode, KDF, or key-agreement protocol. This module
locates a reviewed backend and refuses every operation when none is present.

**Detection, never fallback.** The soft-import shape here is borrowed from
``scripts/task.py``'s optional ``jsonschema`` import, but the semantics are
deliberately different. That precedent degrades a *check*: absent the library,
JSON syntax is still validated and the run continues. Degrading a *guarantee*
would be far worse — a stub returning plausible ciphertext would let every
downstream test pass while nothing was encrypted. So an absent backend sets
``available: false`` and makes ``require_backend()`` raise; it never substitutes
a weaker construction and never returns unencrypted bytes.

The openssl CLI cannot supply the whole surface: it does HKDF, RFC 3394 key
wrap and CSPRNG, but ``openssl enc`` refuses AEAD outright ("AEAD ciphers not
supported") and there is no CLI subcommand that seals with caller-supplied
associated data. Object sealing therefore needs an in-process reviewed library.
"""

from __future__ import annotations

import shutil
from typing import Any

from sync.backends import reference

EXIT_UNAVAILABLE = 78

#: The operations a reviewed backend must provide, and the primitive each needs.
REQUIRED_OPERATIONS = {
    "derive-root-key": "HKDF-SHA256 over the recovery secret with label bunny-os/sync/v1/user-root-key",
    "derive-subkey": "HKDF-SHA256 with the per-purpose label from sync.keys.DERIVATION_LABELS",
    "wrap-key": "RFC 3394 AES key wrap under a device wrapping key",
    "unwrap-key": "RFC 3394 AES key unwrap under a device wrapping key",
    "seal-object": "AES-256-GCM with the envelope associated data bound",
    "open-object": "AEAD open with associated-data verification",
    "generate-recovery-phrase": "CSPRNG entropy encoded against a reviewed 2048-word list",
}

#: Acceptable backends. None is vendored; each must be installed and reviewed.
ACCEPTABLE_BACKENDS = (
    "the cryptography package over OpenSSL, for AES-256-GCM, HKDF-SHA256 and RFC 3394 key wrap",
    "libsodium via the system package, additionally for XChaCha20-Poly1305",
)


class CryptoBackendUnavailable(RuntimeError):
    """Raised when a cryptographic operation is requested with no reviewed backend."""

    def __init__(self, operation: str, detail: str | None = None) -> None:
        self.operation = operation
        suffix = f" {detail}" if detail else ""
        super().__init__(
            f"sync cryptography operation {operation!r} is unavailable: no reviewed cryptographic "
            f"backend is installed.{suffix} No data was encrypted, decrypted, derived, or uploaded."
        )


def backend_available() -> bool:
    return bool(reference.AVAILABLE)


def backend_status() -> dict[str, Any]:
    """Report whether a reviewed cryptographic backend is present."""
    detail = reference.status()
    return {
        "available": detail["available"],
        "backend": detail["name"] if detail["available"] else None,
        "reason": (
            "A reviewed cryptographic backend is installed."
            if detail["available"]
            else f"The cryptography package is not importable: {detail['importError']}"
        ),
        "opensslOnPath": bool(shutil.which("openssl")),
        "opensslNote": (
            "openssl provides HKDF, RFC 3394 key wrap and CSPRNG, but 'openssl enc' refuses AEAD, "
            "so object sealing cannot be done from the CLI."
        ),
        "acceptableBackends": list(ACCEPTABLE_BACKENDS),
        "requiredOperations": dict(REQUIRED_OPERATIONS),
        "supportedAlgorithms": detail["supportedAlgorithms"] if detail["available"] else [],
        "unsupportedAlgorithms": detail["unsupportedAlgorithms"],
        "writesPerformed": False,
        "exitCode": 0 if detail["available"] else EXIT_UNAVAILABLE,
    }


def require_backend(operation: str) -> None:
    """Raise unless a reviewed backend can perform ``operation``.

    Callers must invoke this before any cryptographic work, so that an absent
    backend fails loudly and testably at the call site.
    """
    if operation not in REQUIRED_OPERATIONS:
        raise ValueError(f"unknown cryptographic operation {operation!r}")
    if not reference.AVAILABLE:
        raise CryptoBackendUnavailable(operation, reference.IMPORT_ERROR)


def _checked(operation: str):
    require_backend(operation)
    return reference


def derive_root_key(recovery_secret: bytes, *, salt: bytes = b"") -> bytes:
    from sync.keys import DERIVATION_LABELS

    return _checked("derive-root-key").derive_key(
        recovery_secret, label=DERIVATION_LABELS["user-root-key"], salt=salt
    )


def derive_subkey(parent: bytes, purpose: str, *, salt: bytes = b"") -> bytes:
    from sync.keys import DERIVATION_LABELS

    if purpose not in DERIVATION_LABELS:
        raise ValueError(f"unknown derivation purpose {purpose!r}")
    return _checked("derive-subkey").derive_key(
        parent, label=DERIVATION_LABELS[purpose], salt=salt
    )


def wrap_key(wrapping_key: bytes, key_to_wrap: bytes) -> bytes:
    return _checked("wrap-key").wrap_key(wrapping_key, key_to_wrap)


def unwrap_key(wrapping_key: bytes, wrapped: bytes) -> bytes:
    return _checked("unwrap-key").unwrap_key(wrapping_key, wrapped)


def seal_object(
    key: bytes,
    nonce: bytes,
    plaintext: bytes,
    associated_data: bytes,
    *,
    algorithm: str = "AES-256-GCM",
) -> bytes:
    return _checked("seal-object").seal_object(
        key, nonce, plaintext, associated_data, algorithm=algorithm
    )


def open_object(
    key: bytes,
    nonce: bytes,
    ciphertext: bytes,
    associated_data: bytes,
    *,
    algorithm: str = "AES-256-GCM",
) -> bytes:
    return _checked("open-object").open_object(
        key, nonce, ciphertext, associated_data, algorithm=algorithm
    )


def generate_recovery_entropy() -> bytes:
    return _checked("generate-recovery-phrase").generate_recovery_entropy()


def generate_nonce(algorithm: str = "AES-256-GCM") -> bytes:
    return _checked("seal-object").generate_nonce(algorithm)
