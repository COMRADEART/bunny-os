# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which paths may differ after installation, and which must not be in the image.

Two different questions get confused with each other, and confusing them is how
a reproducibility comparison quietly stops comparing anything:

1. *May this path differ between two installed devices?* Yes for a machine id,
   a per-device secret, a runtime cache. That is what an installed system is.
2. *May this path differ between two builds of the same commit?* **No.** If it
   differs between builds it is either build-environment state that should not
   be in the image, or a real difference in the product.

The policy in this module answers the first question only. It is deliberately
**not** an exclusion list for the comparison, and ``policy_paths_are_not_excluded``
exists so that the day somebody wires it into the comparator, a test fails. The
brief's phrasing is exact: *do not use this policy as a generic ignore list for
reproducibility comparison.* A path listed here must be **absent from the
artifact**, not present-and-ignored.

The machine-identity audit is the enforcement of the second half. It runs over
the collected artifact and refuses builder identity by name — and it refuses it
for ``/etc/machine-id`` too, which the comparison currently cannot see at all
because the volatile-path exclusion drops it before any dimension is computed.
Today that file is zero bytes and correct. The exclusion means a build that
wrote a real one would not be detected, and "correct today, undetectable
tomorrow" is not a passing check.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1

CATEGORIES = (
    "first-boot-generated",
    "per-installation-secret",
    "runtime-cache",
    "runtime-database",
    "user-data",
    "system-identity",
    "persistent-configuration",
    "immutable-product-content",
)

#: What must be true of the path *in the immutable artifact*.
DISPOSITIONS = (
    "absent-from-image",
    "empty-placeholder",
    "generated-at-first-boot",
    "safe-immutable-configuration",
)

#: A disposition that requires the path to carry no content in the artifact.
_MUST_BE_EMPTY = frozenset({"empty-placeholder"})
_MUST_BE_ABSENT = frozenset({"absent-from-image", "generated-at-first-boot"})

_REQUIRED_FIELDS = (
    "path",
    "category",
    "disposition",
    "reason",
    "generator",
    "generationTime",
    "owner",
    "permissions",
    "recoveryBehaviour",
    "validationTest",
)

_MODE = re.compile(r"^0[0-7]{3}$")


class MutableStateError(ValueError):
    """Raised when the mutable-state policy is malformed."""


@dataclass(frozen=True)
class MutableStateEntry:
    path: str
    category: str
    disposition: str
    reason: str
    generator: str
    generationTime: str
    owner: str
    permissions: str
    recoveryBehaviour: str
    validationTest: str
    securityRelevance: str = ""

    def matches(self, candidate: str) -> bool:
        return candidate == self.path or fnmatch.fnmatchcase(candidate, self.path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "category": self.category,
            "disposition": self.disposition,
            "reason": self.reason,
            "generator": self.generator,
            "generationTime": self.generationTime,
            "owner": self.owner,
            "permissions": self.permissions,
            "recoveryBehaviour": self.recoveryBehaviour,
            "validationTest": self.validationTest,
            "securityRelevance": self.securityRelevance,
        }


def parse_policy(document: Mapping[str, Any]) -> tuple[MutableStateEntry, ...]:
    if not isinstance(document, Mapping):
        raise MutableStateError("mutable-state policy must be an object")
    if int(document.get("schemaVersion", 0)) != SCHEMA_VERSION:
        raise MutableStateError(f"mutable-state policy schemaVersion must be {SCHEMA_VERSION}")
    raw = document.get("paths")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MutableStateError("mutable-state policy must carry a paths array")

    entries: list[MutableStateEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise MutableStateError("each mutable-state entry must be an object")
        missing = [name for name in _REQUIRED_FIELDS if not str(item.get(name, "")).strip()]
        if missing:
            raise MutableStateError(
                f"mutable-state entry {item.get('path', '<unnamed>')!r} is missing "
                + ", ".join(sorted(missing))
                + ". Every excluded path must state its category, reason, generator, generation "
                "time, owner, permissions, recovery behaviour and validating test — an entry "
                "without them is an unexplained exclusion"
            )
        category = str(item["category"])
        if category not in CATEGORIES:
            raise MutableStateError(
                f"mutable-state entry {item['path']!r}: category {category!r} must be one of "
                + ", ".join(CATEGORIES)
            )
        disposition = str(item["disposition"])
        if disposition not in DISPOSITIONS:
            raise MutableStateError(
                f"mutable-state entry {item['path']!r}: disposition {disposition!r} must be one of "
                + ", ".join(DISPOSITIONS)
            )
        permissions = str(item["permissions"])
        if not _MODE.match(permissions):
            raise MutableStateError(
                f"mutable-state entry {item['path']!r}: permissions {permissions!r} must be an "
                "octal mode such as 0640"
            )
        path = str(item["path"])
        if path.startswith("/"):
            raise MutableStateError(
                f"mutable-state entry {path!r} must be archive-relative (no leading slash), "
                "because that is how the collected artifact names its entries"
            )
        if path in seen:
            raise MutableStateError(f"mutable-state entry {path!r} is recorded twice")
        seen.add(path)
        entries.append(
            MutableStateEntry(
                path=path,
                category=category,
                disposition=disposition,
                reason=str(item["reason"]),
                generator=str(item["generator"]),
                generationTime=str(item["generationTime"]),
                owner=str(item["owner"]),
                permissions=permissions,
                recoveryBehaviour=str(item["recoveryBehaviour"]),
                validationTest=str(item["validationTest"]),
                securityRelevance=str(item.get("securityRelevance", "")),
            )
        )
    return tuple(entries)


def policy_paths_are_not_excluded(
    entries: Iterable[MutableStateEntry], excluded: Iterable[str]
) -> tuple[str, ...]:
    """Policy paths that a comparison exclusion list also covers.

    Any overlap is a defect. A path in this policy must be **absent from the
    artifact**, which the comparison would notice; a path in the exclusion list
    is invisible to the comparison, which means the policy would be enforcing
    nothing. Returning a non-empty tuple is a failure, not a warning.
    """
    excluded = list(excluded)
    return tuple(
        sorted(
            entry.path
            for entry in entries
            if any(entry.matches(candidate) for candidate in excluded)
        )
    )


# --------------------------------------------------------------------------
# Machine identity
# --------------------------------------------------------------------------

#: Paths that carry machine or installation identity. Each is audited by name
#: rather than by pattern, so that a new one has to be added deliberately.
IDENTITY_PATHS: tuple[tuple[str, str, str], ...] = (
    ("etc/hostname", "absent-from-image", "the builder's hostname is not the device's hostname"),
    (
        "etc/machine-id",
        "empty-placeholder",
        "systemd treats an empty machine-id as first boot and generates one on the device; a "
        "populated file would give every installation the builder's identity",
    ),
    ("etc/machine-info", "absent-from-image", "chassis and deployment metadata are per-device"),
    ("var/lib/dbus/machine-id", "absent-from-image", "a second copy of the machine id"),
    ("etc/ssh/ssh_host_rsa_key", "absent-from-image", "a shipped host key is a shipped private key"),
    ("etc/ssh/ssh_host_ecdsa_key", "absent-from-image", "a shipped host key is a shipped private key"),
    ("etc/ssh/ssh_host_ed25519_key", "absent-from-image", "a shipped host key is a shipped private key"),
    ("etc/brlapi.key", "generated-at-first-boot", "the BrlAPI authorisation key is per-device"),
    ("var/lib/systemd/random-seed", "absent-from-image", "a shared seed is not a seed"),
    ("etc/salt/minion_id", "absent-from-image", "an installation identifier"),
    ("var/lib/dhclient", "absent-from-image", "DHCP leases describe the builder's network"),
    ("var/lib/NetworkManager/*.lease", "absent-from-image", "DHCP leases describe the builder's network"),
)


@dataclass(frozen=True)
class IdentityFinding:
    path: str
    expected: str
    observed: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "expected": self.expected,
            "observed": self.observed,
            "ok": self.ok,
            "detail": self.detail,
        }


def audit_machine_identity(
    entries: Mapping[str, Mapping[str, Any]],
    *,
    extra: Iterable[tuple[str, str, str]] = (),
) -> tuple[IdentityFinding, ...]:
    """Audit a collected artifact for machine-specific state.

    ``entries`` maps an archive-relative path to the collector's record for it,
    which carries at least ``type`` and, for regular files, ``size``. The audit
    is over the **whole** entry set, including paths the comparison excludes as
    volatile — that exclusion is exactly what would hide a leaked identity.
    """
    findings: list[IdentityFinding] = []
    for path, expectation, reason in tuple(IDENTITY_PATHS) + tuple(extra):
        matched = sorted(
            name
            for name in entries
            if name == path or fnmatch.fnmatchcase(name, path)
        )
        if expectation in _MUST_BE_ABSENT:
            ok = not matched
            findings.append(
                IdentityFinding(
                    path=path,
                    expected=expectation,
                    observed="absent" if ok else f"present: {', '.join(matched[:5])}",
                    ok=ok,
                    detail=reason,
                )
            )
            continue
        if expectation in _MUST_BE_EMPTY:
            if not matched:
                findings.append(
                    IdentityFinding(
                        path=path,
                        expected=expectation,
                        observed="absent",
                        ok=False,
                        detail=(
                            f"{reason}. The file must exist and be empty: an absent "
                            "machine-id is a different first-boot path and is not what was declared"
                        ),
                    )
                )
                continue
            sizes = {name: int(entries[name].get("size", -1)) for name in matched}
            bad = {name: size for name, size in sizes.items() if size != 0}
            findings.append(
                IdentityFinding(
                    path=path,
                    expected=expectation,
                    observed=(
                        "empty"
                        if not bad
                        else ", ".join(f"{name} is {size} bytes" for name, size in bad.items())
                    ),
                    ok=not bad,
                    detail=reason,
                )
            )
            continue
        findings.append(
            IdentityFinding(
                path=path,
                expected=expectation,
                observed="present" if matched else "absent",
                ok=True,
                detail=reason,
            )
        )
    return tuple(findings)


def evaluate_identity(findings: Iterable[IdentityFinding]) -> dict[str, Any]:
    findings = tuple(findings)
    failed = [f for f in findings if not f.ok]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "checked": len(findings),
        "failed": len(failed),
        "findings": [f.as_dict() for f in findings],
        "result": "BLOCKED" if failed else "PASS",
        "note": (
            "A qualification artifact must not contain builder-host identity. This audit reads "
            "the whole collected entry set, including paths the comparison excludes as volatile, "
            "because that exclusion is what would hide a leak."
        ),
    }


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CATEGORIES",
    "DISPOSITIONS",
    "IDENTITY_PATHS",
    "SCHEMA_VERSION",
    "IdentityFinding",
    "MutableStateEntry",
    "MutableStateError",
    "audit_machine_identity",
    "evaluate_identity",
    "load",
    "parse_policy",
    "policy_paths_are_not_excluded",
]
