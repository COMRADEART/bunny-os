"""Cryptographic executor boundary.

Bunny OS does not implement AEAD, HKDF, or key agreement in Python. The
repository's established practice is to call a reviewed implementation out of
process — see ``build/scripts/sign-stable-rc.py``, which uses ``openssl pkeyutl``
rather than importing a crypto library.

In a source-only checkout no reviewed sync cryptography backend is installed, so
every operation here reports itself unavailable and performs no work. This is the
same honest-degradation pattern as ``installer/bin/bunny-installer-backend``, which
exits 78 (``EX_CONFIG``) rather than pretending to install.

Reporting "unavailable" is deliberate. A stub that returned plausible-looking
ciphertext would be far worse than a refusal, because downstream tests would pass
while no encryption occurred.
"""

from __future__ import annotations

import shutil
from typing import Any

EXIT_UNAVAILABLE = 78

#: The operations a reviewed backend must provide, and the primitive each requires.
REQUIRED_OPERATIONS = {
    "derive-root-key": "HKDF-SHA256 over the recovery secret with label bunny-os/sync/v1/user-root-key",
    "derive-subkey": "HKDF-SHA256 with the per-purpose label from sync.keys.DERIVATION_LABELS",
    "wrap-key": "AEAD key wrapping under a device wrapping key",
    "unwrap-key": "AEAD key unwrapping under a device wrapping key",
    "seal-object": "XChaCha20-Poly1305 or AES-256-GCM with the envelope associated data bound",
    "open-object": "AEAD open with associated-data verification",
    "generate-recovery-phrase": "CSPRNG draw over a 2048-word list with checksum",
}

#: Acceptable backends. None is vendored; each must be installed and reviewed.
ACCEPTABLE_BACKENDS = (
    "libsodium via the system package, for XChaCha20-Poly1305 and BLAKE2b",
    "OpenSSL 3 via openssl(1) or a reviewed binding, for AES-256-GCM and HKDF",
)


class CryptoBackendUnavailable(RuntimeError):
    """Raised when a cryptographic operation is requested with no reviewed backend."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(
            f"sync cryptography operation {operation!r} is unavailable: no reviewed cryptographic "
            "backend is installed in this source-only build. No data was encrypted, decrypted, "
            "derived, or uploaded."
        )


def backend_status() -> dict[str, Any]:
    """Report whether a reviewed cryptographic backend is present."""
    openssl = shutil.which("openssl")
    return {
        "available": False,
        "reason": (
            "The reviewed Bunny OS sync cryptography backend is not installed. "
            "Detecting openssl on PATH is not sufficient: the sync backend must be a reviewed, "
            "version-pinned component, and no such component ships in this checkout."
        ),
        "opensslOnPath": bool(openssl),
        "acceptableBackends": list(ACCEPTABLE_BACKENDS),
        "requiredOperations": dict(REQUIRED_OPERATIONS),
        "writesPerformed": False,
        "exitCode": EXIT_UNAVAILABLE,
    }


def require_backend(operation: str) -> None:
    """Raise ``CryptoBackendUnavailable`` for every operation.

    This function exists so that any code path that would perform real
    cryptography fails loudly and testably rather than silently degrading.
    """
    if operation not in REQUIRED_OPERATIONS:
        raise ValueError(f"unknown cryptographic operation {operation!r}")
    raise CryptoBackendUnavailable(operation)
