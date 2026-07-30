# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time recovery-key creation and confirmation helpers."""

from __future__ import annotations

import hashlib
import secrets


ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_recovery_key() -> str:
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(8)]
    return "-".join(groups)


def confirmation_digest(key: str) -> str:
    normalized = key.replace("-", "").upper()
    if len(normalized) != 40 or any(character not in ALPHABET for character in normalized):
        raise ValueError("invalid recovery key")
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def confirm_recovery_key(key: str, repeated: str) -> bool:
    return secrets.compare_digest(confirmation_digest(key), confirmation_digest(repeated))

