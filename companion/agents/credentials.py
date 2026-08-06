# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Credentials: obtained at the moment of use, reported only as presence.

The §5 rule list — no keys in repository files, task records, descriptors,
event payloads, command arguments, logs, or protocol responses — is enforced
by one type decision: a resolved credential is a :class:`Secret`, whose
``repr`` and ``str`` are the word ``<secret>``, which serializes to nothing
(``to_json`` raises), and whose value exists only for the adapter call that
needs it. Everything that records anything records a
:class:`CredentialStatus`, which has no value field to leak.

Sources, in the order a configuration may name them:

``environment``
    An explicitly named process environment variable. Named, not enumerated:
    there is no "find me a key" scan and no environment dump anywhere in this
    package (§5 forbids exactly that diagnostic).
``credential-file``
    A private file under an approved directory. Refused when it is a symlink
    (the link target is whoever wrote the link), group- or world-readable
    (0600 or stricter), owned by someone else, or outside the approved
    locations. These are the four §5 rejections, each with its own message.
``secret-service``
    The desktop Secret Service over D-Bus, where the ``secretstorage``
    binding is installed. A genuine adapter: absence reports unavailable,
    never success.

A future hardware-backed source is a new kind here — the reference schema
already admits it so configurations do not need a version bump to name one.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AgentSchemaError, CredentialRefused

__all__ = [
    "CREDENTIAL_KINDS",
    "CredentialReference",
    "CredentialStatus",
    "credential_status",
    "MAX_SECRET_BYTES",
    "Secret",
    "resolve_credential",
]

CREDENTIAL_KINDS = ("none", "environment", "credential-file", "secret-service", "hardware-backed")

MAX_SECRET_BYTES = 4096


class Secret:
    """A value that refuses to be written down.

    Not a dataclass on purpose: dataclasses volunteer their fields to
    ``repr``, ``asdict`` and comparison, and every one of those is a channel.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise CredentialRefused("a secret must be a non-empty string")
        if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
            raise CredentialRefused(f"a secret beyond {MAX_SECRET_BYTES} bytes is not a credential")
        self._value = value

    def reveal(self) -> str:
        """The one sanctioned read, named so a grep finds every use."""
        return self._value

    def __repr__(self) -> str:
        return "<secret>"

    def __str__(self) -> str:
        return "<secret>"

    def __eq__(self, other: object) -> bool:
        # Equality would let code branch on the value; a credential is not data.
        return NotImplemented  # type: ignore[return-value]

    def __hash__(self) -> int:
        raise TypeError("a secret is not hashable; it must not be a dictionary key")

    def to_json(self) -> None:
        raise CredentialRefused("a secret does not serialize")


@dataclass(frozen=True)
class CredentialReference:
    """Where a credential *would* come from. Never the credential."""

    kind: str = "none"
    locator: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CREDENTIAL_KINDS:
            raise AgentSchemaError(f"credential kind {self.kind!r} is not one of {CREDENTIAL_KINDS}")
        if self.kind == "none" and self.locator:
            raise AgentSchemaError("kind 'none' names nothing; a locator contradicts it")
        if self.kind != "none" and not self.locator:
            raise AgentSchemaError(f"kind {self.kind!r} requires a locator")
        if len(self.locator) > 512:
            raise AgentSchemaError("credential locator exceeds bounds")

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "locator": self.locator}


@dataclass(frozen=True)
class CredentialStatus:
    """What may be recorded about a credential: that it is there, not what it is."""

    kind: str
    present: bool
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "present": self.present, "detail": self.detail}


def _resolve_environment(name: str) -> Secret:
    if not name.isidentifier():
        raise CredentialRefused(f"environment variable name {name!r} is not a plain identifier")
    value = os.environ.get(name, "")
    if not value:
        raise CredentialRefused(f"environment variable {name} is absent or empty")
    return Secret(value.strip())


def _resolve_file(locator: str, approved_directories: tuple[Path, ...]) -> Secret:
    if not approved_directories:
        raise CredentialRefused("no approved credential directories are configured")
    path = Path(locator)
    if not path.is_absolute():
        raise CredentialRefused("a credential file is named by absolute path")
    resolved_parents = tuple(directory.resolve() for directory in approved_directories)
    try:
        # lstat first: a symlink is refused before anything follows it.
        info = os.lstat(path)
    except OSError as error:
        raise CredentialRefused(f"credential file cannot be read: {error.strerror or error}") from None
    if stat.S_ISLNK(info.st_mode):
        raise CredentialRefused(
            "credential file is a symlink; the link's author, not the file's, would choose the secret"
        )
    if not stat.S_ISREG(info.st_mode):
        raise CredentialRefused("credential file is not a regular file")
    parent = path.parent.resolve()
    if not any(parent == approved or approved in parent.parents for approved in resolved_parents):
        raise CredentialRefused(
            f"credential file is outside the approved locations "
            f"({', '.join(str(item) for item in resolved_parents)})"
        )
    if os.name == "posix":
        if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise CredentialRefused(
                "credential file is group- or world-accessible; 0600 or stricter is required"
            )
        if info.st_uid != os.getuid():
            raise CredentialRefused("credential file is owned by someone else")
    if info.st_size > MAX_SECRET_BYTES:
        raise CredentialRefused(f"credential file exceeds {MAX_SECRET_BYTES} bytes")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise CredentialRefused("credential file is empty")
    return Secret(content)


def _resolve_secret_service(locator: str) -> Secret:
    try:  # pragma: no cover - exercised only where the binding is installed
        import secretstorage  # type: ignore[import-not-found]
    except ImportError:
        raise CredentialRefused(
            "the Secret Service binding (secretstorage) is not installed; "
            "this source is unavailable, not empty"
        ) from None
    try:  # pragma: no cover - requires a desktop session bus
        connection = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(connection)
        if collection.is_locked():
            raise CredentialRefused("the Secret Service collection is locked")
        for item in collection.search_items({"bunny-os-credential": locator}):
            secret = item.get_secret()
            return Secret(secret.decode("utf-8").strip())
        raise CredentialRefused(f"no Secret Service item carries bunny-os-credential={locator!r}")
    except CredentialRefused:
        raise
    except Exception as error:  # pragma: no cover - bus faults are environmental
        raise CredentialRefused(f"Secret Service lookup failed: {type(error).__name__}") from None


def resolve_credential(
    reference: CredentialReference,
    *,
    approved_directories: tuple[Path, ...] = (),
) -> Secret:
    """Resolve at the moment of use. Nothing caches the returned value."""
    if reference.kind == "none":
        raise CredentialRefused("this provider declares no credential; there is nothing to resolve")
    if reference.kind == "environment":
        return _resolve_environment(reference.locator)
    if reference.kind == "credential-file":
        return _resolve_file(reference.locator, approved_directories)
    if reference.kind == "secret-service":
        return _resolve_secret_service(reference.locator)
    raise CredentialRefused(f"credential kind {reference.kind!r} has no resolver in this build")


def credential_status(
    reference: CredentialReference,
    *,
    approved_directories: tuple[Path, ...] = (),
) -> CredentialStatus:
    """Presence, for descriptors and diagnostics. The value never transits here."""
    if reference.kind == "none":
        return CredentialStatus(kind="none", present=True, detail="no credential required")
    try:
        secret = resolve_credential(reference, approved_directories=approved_directories)
    except CredentialRefused as refusal:
        return CredentialStatus(kind=reference.kind, present=False, detail=str(refusal))
    # The secret was resolvable; drop it immediately. Presence is the report.
    del secret
    return CredentialStatus(kind=reference.kind, present=True, detail="credential present")
