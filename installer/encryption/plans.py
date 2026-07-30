# SPDX-License-Identifier: GPL-3.0-or-later
"""Encryption planning without handling plaintext secrets in protocol data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re


SECRET_REFERENCE = re.compile(r"^(fd:[3-9][0-9]*|installer-secret:[A-Za-z0-9_-]{16,64})$")


@dataclass(frozen=True)
class EncryptionPlan:
    enabled: bool
    format: str = "luks2"
    unlock: str = "password"
    passwordSecretRef: str | None = None
    recoveryKey: bool = True
    tpm2: bool = False
    fallbackPassword: bool = True
    pcrPolicy: tuple[int, ...] = ()

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.enabled:
            if self.passwordSecretRef or self.recoveryKey or self.tpm2:
                errors.append("disabled encryption cannot contain unlock material")
            return tuple(errors)
        if self.format != "luks2":
            errors.append("only LUKS2 is supported")
        if self.unlock not in {"password", "password+tpm2"}:
            errors.append("unsupported unlock mode")
        if not self.passwordSecretRef or not SECRET_REFERENCE.fullmatch(self.passwordSecretRef):
            errors.append("a protected password secret reference is required")
        if self.tpm2 and not self.fallbackPassword:
            errors.append("TPM2 requires a fallback password")
        if self.tpm2 and not self.recoveryKey:
            errors.append("TPM2 requires an independent recovery key")
        if self.tpm2 and not self.pcrPolicy:
            errors.append("TPM2 requires an explicit PCR policy")
        if any(not isinstance(pcr, int) or pcr < 0 or pcr > 23 for pcr in self.pcrPolicy):
            errors.append("invalid TPM PCR index")
        return tuple(errors)

    def public_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["passwordSecretRef"] = "[protected]" if self.passwordSecretRef else None
        value["pcrPolicy"] = list(self.pcrPolicy)
        return value

