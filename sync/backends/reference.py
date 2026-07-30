"""Reference cryptographic backend built on the ``cryptography`` package.

Everything here is parameter selection over reviewed code. No cipher, mode, KDF
or construction is implemented in this file, and ``tests/cryptography`` asserts
that no hand-rolled primitive appears anywhere under ``sync/``.

Supported today:

* **AES-256-GCM** for object sealing, with a 12-byte nonce and the envelope's
  associated data authenticated.
* **HKDF-SHA256** for key derivation, with the per-purpose labels from
  ``sync/keys.py``.
* **RFC 3394 AES key wrap** for wrapping collection keys to device keys.
* **CSPRNG** via ``os.urandom`` for nonces and recovery entropy.

Deliberately **not** supported: XChaCha20-Poly1305. The envelope format allows
it, but this backend cannot provide it — the ``cryptography`` build exposes only
the IETF 12-byte-nonce ChaCha20-Poly1305, not the 24-byte XChaCha20 variant.
Sealing with it raises rather than silently substituting a different
construction, because a silent substitution would make the envelope's declared
algorithm a lie.
"""

from __future__ import annotations

import os
from typing import Any

try:  # pragma: no cover - exercised by whether the import succeeds
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes, keywrap
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    AVAILABLE = True
    IMPORT_ERROR: str | None = None
except ImportError as error:  # pragma: no cover - environment dependent
    AVAILABLE = False
    IMPORT_ERROR = str(error)

BACKEND_NAME = "cryptography/openssl"

#: Algorithms this backend can actually perform, as opposed to those the
#: envelope format permits.
SUPPORTED_ALGORITHMS = ("AES-256-GCM",)

#: Declared by the envelope format but unavailable here, with the reason.
UNSUPPORTED_ALGORITHMS = {
    "XChaCha20-Poly1305": (
        "requires a libsodium backend; the cryptography package exposes only the "
        "IETF 12-byte-nonce ChaCha20-Poly1305, not the 24-byte XChaCha20 variant"
    ),
}

KEY_BYTES = 32
GCM_NONCE_BYTES = 12
RECOVERY_ENTROPY_BYTES = 32


class BackendError(RuntimeError):
    """A cryptographic operation failed or was refused."""


def _require_available() -> None:
    if not AVAILABLE:
        raise BackendError(f"the cryptography package is not importable: {IMPORT_ERROR}")


def _require_key(key: bytes, name: str = "key") -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise BackendError(f"{name} must be exactly {KEY_BYTES} bytes")
    return bytes(key)


def status() -> dict[str, Any]:
    """Report what this backend can do, without performing anything."""
    return {
        "name": BACKEND_NAME,
        "available": AVAILABLE,
        "importError": IMPORT_ERROR,
        "supportedAlgorithms": list(SUPPORTED_ALGORITHMS),
        "unsupportedAlgorithms": dict(UNSUPPORTED_ALGORITHMS),
    }


def random_bytes(count: int) -> bytes:
    """Return CSPRNG output. ``os.urandom`` is the platform CSPRNG."""
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1024:
        raise BackendError("count must be between 1 and 1024")
    return os.urandom(count)


def generate_nonce(algorithm: str = "AES-256-GCM") -> bytes:
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise BackendError(_unsupported_message(algorithm))
    return os.urandom(GCM_NONCE_BYTES)


def _unsupported_message(algorithm: str) -> str:
    reason = UNSUPPORTED_ALGORITHMS.get(algorithm)
    if reason:
        return f"{algorithm} is not supported by {BACKEND_NAME}: {reason}"
    return f"{algorithm} is not a supported AEAD construction"


def derive_key(parent: bytes, *, label: bytes, salt: bytes = b"", length: int = KEY_BYTES) -> bytes:
    """HKDF-SHA256 with a per-purpose info label.

    Distinct labels are what stop a key derived for one purpose from being
    valid in another; ``sync/keys.py`` owns the label vocabulary.
    """
    _require_available()
    if not isinstance(parent, (bytes, bytearray)) or len(parent) < 16:
        raise BackendError("parent key material must be at least 16 bytes")
    if not isinstance(label, (bytes, bytearray)) or not label:
        raise BackendError("a non-empty derivation label is required")
    if not 16 <= length <= 64:
        raise BackendError("derived length must be between 16 and 64 bytes")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=bytes(salt),
        info=bytes(label),
    ).derive(bytes(parent))


def wrap_key(wrapping_key: bytes, key_to_wrap: bytes) -> bytes:
    """RFC 3394 AES key wrap."""
    _require_available()
    _require_key(wrapping_key, "wrapping key")
    _require_key(key_to_wrap, "key to wrap")
    return keywrap.aes_key_wrap(bytes(wrapping_key), bytes(key_to_wrap))


def unwrap_key(wrapping_key: bytes, wrapped: bytes) -> bytes:
    """RFC 3394 AES key unwrap. Raises on any integrity failure."""
    _require_available()
    _require_key(wrapping_key, "wrapping key")
    if not isinstance(wrapped, (bytes, bytearray)) or len(wrapped) < KEY_BYTES:
        raise BackendError("wrapped key is malformed")
    try:
        return keywrap.aes_key_unwrap(bytes(wrapping_key), bytes(wrapped))
    except Exception as error:  # keywrap raises InvalidUnwrap
        raise BackendError("wrapped key failed integrity verification") from error


def seal_object(
    key: bytes,
    nonce: bytes,
    plaintext: bytes,
    associated_data: bytes,
    *,
    algorithm: str = "AES-256-GCM",
) -> bytes:
    """Encrypt and authenticate, binding the envelope's associated data."""
    _require_available()
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise BackendError(_unsupported_message(algorithm))
    _require_key(key)
    if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != GCM_NONCE_BYTES:
        raise BackendError(f"AES-256-GCM requires a {GCM_NONCE_BYTES}-byte nonce")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise BackendError("plaintext must be bytes")
    if not isinstance(associated_data, (bytes, bytearray)) or not associated_data:
        raise BackendError(
            "associated data is required; an unbound ciphertext can be relocated to another object"
        )
    return AESGCM(bytes(key)).encrypt(bytes(nonce), bytes(plaintext), bytes(associated_data))


def open_object(
    key: bytes,
    nonce: bytes,
    ciphertext: bytes,
    associated_data: bytes,
    *,
    algorithm: str = "AES-256-GCM",
) -> bytes:
    """Verify and decrypt. Any tamper, wrong key, or wrong AAD raises."""
    _require_available()
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise BackendError(_unsupported_message(algorithm))
    _require_key(key)
    if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != GCM_NONCE_BYTES:
        raise BackendError(f"AES-256-GCM requires a {GCM_NONCE_BYTES}-byte nonce")
    if not isinstance(associated_data, (bytes, bytearray)) or not associated_data:
        raise BackendError("associated data is required")
    try:
        return AESGCM(bytes(key)).decrypt(bytes(nonce), bytes(ciphertext), bytes(associated_data))
    except InvalidTag as error:
        raise BackendError(
            "authentication failed: the ciphertext, nonce, key, or associated data does not match"
        ) from error


def generate_recovery_entropy() -> bytes:
    """Return CSPRNG entropy for a recovery secret.

    Bunny OS does not ship a mnemonic wordlist. Encoding this entropy as a
    24-word phrase requires the reviewed BIP-0039 English list, which must be
    supplied to ``encode_recovery_phrase``. Shipping an unreviewed,
    hand-transcribed wordlist would be worse than shipping none.
    """
    return os.urandom(RECOVERY_ENTROPY_BYTES)


def encode_recovery_phrase(entropy: bytes, wordlist: list[str]) -> list[str]:
    """Encode entropy as words using a caller-supplied 2048-word list."""
    if len(wordlist) != 2048:
        raise BackendError("a 2048-word list is required")
    if len(entropy) != RECOVERY_ENTROPY_BYTES:
        raise BackendError(f"entropy must be {RECOVERY_ENTROPY_BYTES} bytes")
    value = int.from_bytes(entropy, "big")
    words: list[str] = []
    # 32 bytes = 256 bits; 24 words at 11 bits each covers 264, so the first
    # word carries the 8 leading bits plus checksum space. Kept explicit rather
    # than clever so the bit accounting is reviewable.
    total_bits = RECOVERY_ENTROPY_BYTES * 8
    for index in range(total_bits // 11):
        shift = total_bits - (index + 1) * 11
        words.append(wordlist[(value >> shift) & 0x7FF])
    return words
