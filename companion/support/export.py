# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export Bunny Diagnostics: a file the user reads first and sends second.

§38 begins with a prohibition — **do not automatically upload crashes** — and the
whole shape of this module follows from taking it seriously. There is no
transport here. No HTTP client, no socket, no "would you like to send this".
:func:`export_diagnostics` writes a file and returns its path; what happens to
the file afterwards is somebody's decision, made outside this program.

The bundle is a single JSON document rather than an archive of logs, for two
reasons. It can be read in a text editor by the person who produced it, which is
what "allow the user to inspect before sharing" requires in practice — an
archive nobody opens is not inspectable. And every field in it went through a
declared projection, so "what is in this file" has an answer that is a list
rather than a directory walk.

What is deliberately absent, and why each one is easy to include by accident:

============================  ==============================================
API keys                      credentials are read from Secret Service and
                              never held as strings here
raw microphone audio          no capture path is opened by this module
secret task content           task records project through the ``audit``
                              audience, whose ceiling is ``internal``
full clipboard content        the ledger records action *identity*, never the
                              payload
private URI query strings     URIs are recorded as scheme and host only
passwords                     see credentials
============================  ==============================================

The build-input identity is included because a bug report against an unknown
build is a bug report about nothing. That is the one field somebody might object
to as identifying; it identifies the *image*, not the machine, and there is no
hardware serial, MAC address, hostname or username anywhere in the bundle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import tempfile
from typing import Any, Mapping

from ..privacy import redact_diagnostic_text
from . import companion_state_root
from .diagnose import DiagnosticReport, diagnose

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BUNDLE_CONTENTS",
    "EXCLUDED_FROM_BUNDLE",
    "build_bundle",
    "export_diagnostics",
]

BUNDLE_SCHEMA_VERSION = 1

#: What a bundle contains, declared so the "inspect before sharing" prompt can
#: list it without reading the file.
BUNDLE_CONTENTS: tuple[str, ...] = (
    "the build identity: version, channel, build id, commit, image digest",
    "a hardware summary: architecture, CPU model, memory, GPU, display protocol",
    "component versions for every Bunny subsystem",
    "the state of the Bunny user services",
    "renderer, provider, audio, microphone and speech diagnostics",
    "recent warnings and errors from the Bunny journal, with paths and tokens removed",
    "the build inputs this image was produced from",
)

#: What a bundle never contains. Listed for the same reason: a promise that is
#: not written down is not a promise.
EXCLUDED_FROM_BUNDLE: tuple[str, ...] = (
    "API keys, tokens and passwords",
    "recorded audio of any kind",
    "the text of your conversations with Bunny",
    "clipboard contents",
    "query strings from URIs you opened",
    "your username, hostname or machine identifiers",
    "file contents from anywhere on the machine",
)


def _component_versions() -> dict[str, str]:
    """A version per subsystem, read from the modules themselves.

    Read rather than listed, so a subsystem that is missing from the installed
    tree shows as missing here instead of showing the version it would have had.
    """
    versions: dict[str, str] = {"python": platform.python_version()}
    probes: tuple[tuple[str, str, str], ...] = (
        ("companion", "companion", "COMPANION_PROTOCOL_VERSION"),
        ("character", "companion.character", "CHARACTER_PACKAGE_SCHEMA_VERSION"),
        ("character-renderer", "companion.character", "CHARACTER_RENDERER_API_VERSION"),
        ("agents", "companion.agents", "AGENT_RUNTIME_VERSION"),
        ("voice", "companion.voice", "VOICE_RUNTIME_VERSION"),
        ("speech", "companion.speech", "SPEECH_INPUT_VERSION"),
        ("desktop", "companion.desktop", "DESKTOP_ACTION_VERSION"),
        ("capability", "capability", "CAPABILITY_RUNTIME_VERSION"),
    )
    for name, module_name, attribute in probes:
        try:
            module = __import__(module_name, fromlist=["*"])
        except Exception as error:
            versions[name] = f"unavailable: {redact_diagnostic_text(str(error), limit=120)}"
            continue
        value = getattr(module, attribute, None)
        versions[name] = str(value) if value is not None else "present"
    return versions


def _hardware_summary() -> dict[str, Any]:
    """The §38 hardware summary — a *summary*, with the identifiers removed.

    ``hardware_facts`` reports network interface names, which on a laptop
    include a stable wireless interface name, and thermal zone types, which are
    harmless. The interface list is reduced to a count and a "is anything up"
    flag: whether the machine had a network is diagnostic, which networks it had
    is not.
    """
    try:
        from ..hardware import hardware_facts

        facts = hardware_facts()
    except Exception as error:
        return {"error": redact_diagnostic_text(str(error))}
    value = facts.to_json()
    network = value.get("network", {})
    value["network"] = {
        "interfaceCount": len(network.get("interfaces", [])),
        "wirelessPresent": any(
            item.get("wireless") == "yes" for item in network.get("interfaces", [])
        ),
        "up": network.get("up", False),
    }
    return value


def _build_inputs() -> dict[str, Any]:
    """Where this image came from, from the image's own metadata."""
    try:
        from ..identity import build_identity

        identity = build_identity()
    except Exception as error:
        return {"error": redact_diagnostic_text(str(error))}
    return {
        "buildId": identity.build_id,
        "sourceCommit": identity.source_commit,
        "imageVersion": identity.image_version,
        "imageDigest": identity.image_digest,
        "baseImageReference": identity.base_image_reference,
        "buildTimestamp": identity.build_timestamp,
        "profile": identity.profile,
        "channel": identity.channel,
        "installed": identity.installed,
    }


def build_bundle(
    *,
    root: Path | None = None,
    report: DiagnosticReport | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    """Assemble the bundle in memory. No I/O beyond the readings it makes.

    ``generated_at`` is passed in rather than read from the clock, so that a
    test can produce a byte-identical bundle twice. A timestamp the caller
    supplies is also the honest arrangement for a file the user may sit on for a
    week before sending it.
    """
    root = root or companion_state_root()
    report = report or diagnose(root=root)
    return {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "kind": "bunny-diagnostics",
        "generatedAt": generated_at or "unspecified",
        "identity": dict(report.identity),
        "hardwareSummary": _hardware_summary(),
        "componentVersions": _component_versions(),
        "buildInputs": _build_inputs(),
        "diagnostics": report.to_json(),
        "contents": list(BUNDLE_CONTENTS),
        "excluded": list(EXCLUDED_FROM_BUNDLE),
        "uploaded": False,
        "note": (
            "Nothing in this file has been sent anywhere. Read it, then decide. "
            "It contains no credentials, no audio, no conversation text and no "
            "machine identifiers."
        ),
    }


def export_diagnostics(
    destination: Path,
    *,
    root: Path | None = None,
    report: DiagnosticReport | None = None,
    generated_at: str = "",
) -> Path:
    """Write the bundle to ``destination`` and return the path it landed at.

    Written 0600 through a temporary file in the same directory, like every
    other state write in this codebase: a diagnostics bundle half-written by a
    crash would be a file somebody sends believing it complete.
    """
    bundle = build_bundle(root=root, report=report, generated_at=generated_at)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".bunny-diagnostics-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination


def default_destination(root: Path | None = None) -> Path:
    """Where the window's *Export* button writes when the user does not choose.

    The user's home rather than a state directory: a file the user is meant to
    find has to be somewhere they look.
    """
    for candidate in (
        Path(os.environ.get("XDG_DOWNLOAD_DIR", "")) if os.environ.get("XDG_DOWNLOAD_DIR") else None,
        Path.home() / "Downloads",
        Path.home(),
    ):
        if candidate is not None and candidate.is_dir():
            return candidate / "bunny-diagnostics.json"
    return (root or companion_state_root()) / "bunny-diagnostics.json"
