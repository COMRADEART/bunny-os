# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render a validated plan as a kickstart, for Anaconda to execute.

## Why a kickstart and not direct DBus configuration

§2 gives the installer engine authority over partitioning, encryption, deployment
and the bootloader, and gives the Bunny surface presentation only. A kickstart is
the form in which Anaconda has always accepted that division: it is a document
describing *what* is wanted, which Anaconda then validates itself and either
performs or refuses. Configuring Anaconda's storage module property by property
over DBus would put this code in the position of deciding partition layout — the
exact thing §2 says it must not do.

It is also the only form that can be **read before it is run**. A reviewer, a
test, or a person pressing "Installation details" can look at the document that
is about to erase a disk. A sequence of DBus property writes cannot be looked at.

## The payload is never composed here

This is the safety rule of the module. A kickstart's payload directive —
``ostreecontainer``, ``ostreesetup``, ``liveimg`` — is what decides *which
operating system* gets written. Composing one from a guess about how
image-builder tagged the ISO would mean an installer that writes something other
than the system on the medium, and it would look exactly like a working
installer until someone checked what was installed.

So :func:`payload_directives` **extracts** it from the ISO's own kickstart, and
:func:`render` refuses to produce a document if it did not find one. A missing
payload is not defaulted, and there is no fallback string anywhere in this file.

## Secrets

The passphrase and the account password are the two values that must appear in
the rendered text — kickstart has no indirection for them. They arrive as
arguments, are never logged, and :func:`render` is expected to be called by
something that writes the result to a 0600 file on tmpfs and unlinks it after
Anaconda has read it. :func:`redacted` renders the same document with both
replaced, and that is the version that goes to the audit log, the advanced
disclosure and any report.

The account password is rendered ``--iscrypted``: :func:`crypt_password` hashes
it before it reaches the document, so the plaintext never exists in the file even
for the moment it is on disk. The LUKS passphrase cannot be hashed — the whole
point is that it unlocks a volume — which is why the file is on tmpfs.
"""

from __future__ import annotations

import re
import secrets as _secrets
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "PAYLOAD_COMMANDS",
    "KickstartError",
    "crypt_password",
    "payload_directives",
    "redacted",
    "render",
]

#: The kickstart commands that decide which operating system is installed. One
#: of these must be present or nothing is rendered.
PAYLOAD_COMMANDS = ("ostreecontainer", "ostreesetup", "liveimg", "url")

#: Commands this module supplies itself, and which must therefore be dropped from
#: the ISO's kickstart when it is used as a base — otherwise the medium's
#: defaults and the person's choices both appear and the last one wins silently.
#:
#: That is not hypothetical. The first render of this module kept the medium's
#: ``firewall --disabled`` *after* its own ``firewall --enabled``, and kickstart
#: takes the last occurrence — so a document that read as hardened would have
#: installed a system with the firewall off. `_assert_no_duplicate_commands`
#: below is the structural guard; this list is the fix it enforces.
_SUPERSEDED = (
    # display mode
    "text", "graphical", "cmdline",
    # locale and identity
    "lang", "keyboard", "timezone", "rootpw", "user", "network",
    # storage
    "ignoredisk", "clearpart", "part", "partition", "autopart", "zerombr",
    "bootloader", "reqpart",
    # security posture
    "selinux", "firewall", "authselect", "auth",
    # what happens at the end — §27 gives the restart to the person
    "reboot", "shutdown", "halt", "poweroff",
)

#: Commands legitimately repeatable in one kickstart.
_REPEATABLE = frozenset({"part", "partition", "volgroup", "logvol", "raid", "btrfs", "repo"})

_SAFE_TEXT = re.compile(r"^[A-Za-z0-9 ._@+:/-]{0,128}$")
_DEVICE = re.compile(r"^[a-z0-9]+$")


class KickstartError(ValueError):
    """The plan cannot be rendered as a kickstart, and no document is produced."""


def _quote(value: str) -> str:
    """Single-quote a value for kickstart, refusing anything that could escape.

    Kickstart is parsed with shell-like word splitting, so a value containing a
    quote is a value that can add a directive. Refusing is correct rather than
    escaping: every field that reaches here is one a person typed into a form
    with its own validator, and a display name containing a quote character is a
    thing to reject at the form, not to smuggle through here.
    """
    if "'" in value or "\n" in value or "\r" in value:
        raise KickstartError(f"unsafe kickstart value: {value!r}")
    return f"'{value}'"


#: The base64 alphabet crypt(3) salts use. Not the standard one — crypt has its
#: own ordering and a salt built from the standard alphabet is still accepted,
#: but this is the conventional set.
_SALT_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _libcrypt():
    """The platform's libcrypt, or ``None``.

    **Python 3.14 removed the `crypt` module** (PEP 594), and Fedora 44 — which
    is what the live installer runs — ships Python 3.14. So the obvious import
    is gone on exactly the platform this code executes on, and discovering that
    at install time would mean an installer that collects an account and then
    cannot create it.

    ctypes into libxcrypt rather than a Python reimplementation of yescrypt or
    sha512-crypt: this is the same library `/etc/shadow` is verified against, so
    a hash it produces is a hash that logs in. A reimplementation would be a
    second opinion about a password, which is not a thing to have two of.
    """
    import ctypes
    import ctypes.util

    for name in ("libcrypt.so.2", "libcrypt.so.1", ctypes.util.find_library("crypt")):
        if not name:
            continue
        try:
            library = ctypes.CDLL(name, use_errno=True)
        except OSError:
            continue
        library.crypt.restype = ctypes.c_char_p
        library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        return library
    return None


def crypt_password(password: str, *, salt: str | None = None) -> str:
    """A crypt(3) hash, so the plaintext never reaches the document.

    yescrypt where libxcrypt offers it, sha512-crypt otherwise; both are what an
    ``authselect``-configured Fedora accepts in ``/etc/shadow``. Raises rather
    than falling back to anything weaker, and raises rather than writing a
    plaintext password into a kickstart — a silently downgraded credential is
    the kind of thing found years later.
    """
    if not password:
        raise KickstartError("refusing to hash an empty password")

    library = _libcrypt()
    if library is not None:
        for prefix in ("$y$j9T$", "$6$"):
            chosen = salt or prefix + "".join(
                _secrets.choice(_SALT_ALPHABET) for _ in range(16))
            result = library.crypt(password.encode("utf-8"), chosen.encode("ascii"))
            if result:
                hashed = result.decode("ascii")
                # libxcrypt signals a rejected setting by returning a string
                # starting with '*', which is not a hash and would lock the
                # account if it reached /etc/shadow.
                if hashed and not hashed.startswith("*"):
                    return hashed
            if salt:                                    # an explicit salt is not retried
                break

    # Fedora's installer environment has openssl; a developer workstation may
    # not have libcrypt at all. sha512 only, because `openssl passwd` has no
    # yescrypt.
    import shutil
    import subprocess

    openssl = shutil.which("openssl")
    if openssl:
        arguments = [openssl, "passwd", "-6"]
        if salt is not None:
            # `openssl passwd` takes a bare salt, not a full crypt setting, and
            # ignores the argument entirely if it is not passed with -salt. The
            # first version of this omitted it, so re-hashing with a stored hash
            # as the salt produced a *different* hash every time — a silent
            # failure that looks exactly like a wrong password.
            if not salt.startswith("$6$"):
                raise KickstartError(
                    "this platform has no libcrypt, and openssl can only "
                    f"reproduce sha512-crypt hashes, not {salt.split('$')[1:2]}"
                )
            parts = salt.split("$")
            if len(parts) < 3:
                raise KickstartError(f"malformed crypt setting: {salt!r}")
            arguments += ["-salt", parts[2]]
        arguments.append("-stdin")
        completed = subprocess.run(
            arguments, input=password, capture_output=True, text=True, timeout=30,
        )
        candidate = completed.stdout.strip()
        if completed.returncode == 0 and candidate.startswith("$6$"):
            return candidate

    raise KickstartError(
        "no crypt(3) implementation is available to hash the account password. "
        "Python 3.14 removed the `crypt` module and neither libxcrypt nor "
        "openssl could be used; the installer will not put a plaintext password "
        "in a kickstart"
    )


def payload_directives(base: Iterable[str]) -> tuple[str, ...]:
    """The lines from the ISO's kickstart that decide what gets installed.

    Returned verbatim, including their options: the container reference, the
    transport, and whether signature verification is on are image-builder's
    decisions and are not this module's to restate.
    """
    found: list[str] = []
    for line in base:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        command = stripped.split(None, 1)[0]
        if command in PAYLOAD_COMMANDS:
            found.append(stripped)
    return tuple(found)


def _preserved(base: Iterable[str]) -> tuple[str, ...]:
    """Lines from the ISO's kickstart that are kept as they are.

    Everything that is neither a payload directive nor something this module
    supplies. `%packages`, `%post` and `%addon` sections included: an ISO that
    ships one has a reason, and dropping it would change what is installed.
    """
    kept: list[str] = []
    in_section = False
    for line in base:
        stripped = line.strip()
        if stripped.startswith("%end"):
            kept.append(stripped)
            in_section = False
            continue
        if stripped.startswith("%"):
            in_section = True
            kept.append(stripped)
            continue
        if in_section:
            kept.append(line.rstrip())
            continue
        if not stripped or stripped.startswith("#"):
            continue
        command = stripped.split(None, 1)[0]
        if command in PAYLOAD_COMMANDS or command in _SUPERSEDED:
            continue
        kept.append(stripped)
    return tuple(kept)


def _device_name(plan: Mapping[str, Any]) -> str:
    target = plan.get("targetDisk")
    if not isinstance(target, Mapping):
        raise KickstartError("the plan has no target disk")
    path = str(target.get("devicePath", ""))
    if not path.startswith("/dev/"):
        raise KickstartError(f"target disk is not a device path: {path!r}")
    name = path[len("/dev/"):]
    # Anaconda's --drives takes a kernel name, not a path. A name with a slash
    # in it would be a device-mapper or by-id path, which this installer does
    # not plan against.
    if not _DEVICE.fullmatch(name):
        raise KickstartError(f"unsupported target device name: {name!r}")
    return name


def _partition_lines(plan: Mapping[str, Any], device: str, *, passphrase: str | None) -> list[str]:
    """The layout, from the validated plan and from nothing else.

    Sizes come out of `storage.planning`, which produced them, and are converted
    to the mebibytes kickstart counts in. The system partition is the only one
    that may be encrypted, and the passphrase is required exactly when the plan
    says encryption is enabled — a mismatch raises rather than producing a
    document that would either prompt unexpectedly or leave a disk unencrypted.
    """
    encryption = plan.get("encryption")
    encrypted = bool(isinstance(encryption, Mapping) and encryption.get("enabled"))
    if encrypted and not passphrase:
        raise KickstartError("the plan enables encryption but no passphrase was supplied")
    if passphrase and not encrypted:
        raise KickstartError("a passphrase was supplied for an unencrypted plan")

    lines: list[str] = []
    partitions = plan.get("partitions")
    if not isinstance(partitions, Sequence) or not partitions:
        raise KickstartError("the plan has no partitions")

    for item in partitions:
        if not isinstance(item, Mapping):
            raise KickstartError("a partition entry is not an object")
        role = str(item.get("role", ""))
        size_mib = max(1, int(item.get("sizeBytes", 0)) // (1024 ** 2))
        if role == "efi":
            lines.append(f"part /boot/efi --fstype=efi --size={size_mib} --ondisk={device}")
        elif role == "boot":
            lines.append(f"part /boot --fstype=ext4 --size={size_mib} --ondisk={device}")
        elif role == "system":
            if encrypted:
                lines.append(
                    f"part / --fstype=ext4 --grow --ondisk={device} --encrypted "
                    f"--luks-version=luks2 --passphrase={_quote(passphrase or '')}"
                )
            else:
                lines.append(f"part / --fstype=ext4 --grow --ondisk={device}")
        else:
            raise KickstartError(f"unsupported partition role in plan: {role!r}")
    return lines


def render(
    *,
    plan: Mapping[str, Any],
    choices: Mapping[str, Any],
    base: Sequence[str],
    password_hash: str,
    passphrase: str | None = None,
) -> str:
    """The document Anaconda will execute.

    ``base`` is the ISO's own kickstart, read from the medium. ``choices`` is the
    `setup_state.Choices` record. Neither the disk nor the encryption setting is
    taken from ``choices``: both come from ``plan``, which is the document the
    backend validated, so a surface that disagreed with the validated plan cannot
    change what is written.
    """
    payload = payload_directives(base)
    if not payload:
        raise KickstartError(
            "the installation medium's kickstart contains no payload directive "
            f"({', '.join(PAYLOAD_COMMANDS)}); refusing to render an installation "
            "that would not write the system on this medium"
        )

    device = _device_name(plan)
    locale = choices.get("locale", {})
    account = choices.get("account", {})

    language = str(locale.get("language", "en-GB")).replace("-", "_")
    layout = str(locale.get("keyboardLayout", "gb"))
    timezone = str(locale.get("timezone", "Europe/London"))
    username = str(account.get("username", ""))
    display_name = str(account.get("displayName", ""))
    device_name = str(account.get("deviceName", "")).strip()

    if not _SAFE_TEXT.fullmatch(layout) or not _SAFE_TEXT.fullmatch(timezone):
        raise KickstartError("keyboard layout or timezone contains unexpected characters")
    if not re.fullmatch(r"^[a-z_][a-z0-9_-]{0,31}$", username):
        raise KickstartError(f"invalid username for kickstart: {username!r}")
    if not password_hash.startswith("$"):
        raise KickstartError("the account password must be supplied already hashed")

    lines: list[str] = [
        "# Generated by Bunny OS setup from a backend-validated installation plan.",
        "# Every destructive directive below names the disk the plan targets.",
        "text --non-interactive",
        f"lang {language}.UTF-8",
        f"keyboard --xlayouts={_quote(layout)}",
        f"timezone {timezone} --utc",
    ]
    if device_name:
        if not re.fullmatch(r"^[a-z0-9][a-z0-9-]{0,62}$", device_name):
            raise KickstartError(f"invalid device name: {device_name!r}")
        lines.append(f"network --hostname={device_name}")

    lines += [
        # §14: the first user is a conventional administrator and root is locked,
        # which is what `users.validation` already requires of the plan.
        "rootpw --lock",
        f"user --name={username} --gecos={_quote(display_name)} --groups=wheel "
        f"--iscrypted --password={_quote(password_hash)}",
        "",
        "# Storage. The only disk named anywhere in this document:",
        f"ignoredisk --only-use={device}",
        f"clearpart --all --drives={device} --initlabel",
    ]
    lines += _partition_lines(plan, device, passphrase=passphrase)
    lines += [
        "",
        "bootloader --location=mbr",
        "selinux --enforcing",
        "firewall --enabled",
        "",
        "# Payload, taken verbatim from the installation medium's own kickstart:",
    ]
    lines += list(payload)

    preserved = _preserved(base)
    if preserved:
        lines += ["", "# Preserved from the installation medium:"] + list(preserved)

    # Deliberately no `reboot`. §27 hands the restart to the person on the
    # completion screen; a kickstart that rebooted would take the machine away
    # while they were still reading what happened.
    document = "\n".join(lines) + "\n"
    _assert_no_duplicate_commands(document)
    return document


def _assert_no_duplicate_commands(document: str) -> None:
    """Refuse a document in which any command is set twice.

    Kickstart takes the **last** occurrence of a command, so a duplicate is not
    a tidiness problem: it is a setting that reads one way and behaves another.
    The failure this exists to prevent was real — the medium's
    ``firewall --disabled`` outlived this module's ``firewall --enabled`` and the
    rendered document looked correct.

    Checking the rendered text rather than the inputs is deliberate. A list of
    superseded commands can fall behind the list of commands emitted, and the
    two drifting apart is invisible; the output cannot drift from itself.
    """
    seen: dict[str, int] = {}
    in_section = False
    for line in document.splitlines():
        stripped = line.strip()
        if stripped.startswith("%end"):
            in_section = False
            continue
        if stripped.startswith("%"):
            in_section = True
            continue
        if in_section or not stripped or stripped.startswith("#"):
            continue
        command = stripped.split(None, 1)[0]
        if command in _REPEATABLE:
            continue
        seen[command] = seen.get(command, 0) + 1
    duplicated = sorted(name for name, count in seen.items() if count > 1)
    if duplicated:
        raise KickstartError(
            "the rendered kickstart sets these commands more than once, and "
            "kickstart takes the last one: " + ", ".join(duplicated)
        )


def redacted(document: str) -> str:
    """The same document with both secrets removed, for logs and for the screen."""
    document = re.sub(r"(--passphrase=)\S+", r"\1'[redacted]'", document)
    document = re.sub(r"(--password=)\S+", r"\1'[redacted]'", document)
    return document
