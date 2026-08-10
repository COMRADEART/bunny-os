# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way a capsule refuses, named separately.

Each name is a different sentence to a person and a different next move:

``CapsuleSchemaError``
    a malformed identity, manifest or path. The request cannot be understood.
``CapsuleUnavailable``
    the machine cannot run a capsule at all — no backend present, no session,
    no user namespaces. The honest answer is "not here", and §22 requires it be
    given rather than worked around by running the application unconfined.
``CapsuleIsolationError``
    an isolation plan could not be built, or could not be built *completely*.
    This is the one that must never degrade into a launch: an application whose
    sandbox could not be constructed does not start.
``CapsuleContainmentError``
    something tried to reach outside a capsule's own tree — a path that resolved
    elsewhere, a bind that would have crossed into another capsule's private
    data, a reset whose target was not inside the capsule root. Always audited.
``CapsuleStateError``
    an operation asked for from the wrong lifecycle state: launching a removed
    capsule, resetting one that is running.
``CapsuleBusy``
    exactly one attempt owns a capsule's lifecycle at a time and another holds
    it. Distinguished from a state error because the remedy is to wait.
``CapsuleExportRefused``
    an artefact could not leave the capsule: no approved destination, a
    destination outside the user's own directories, or an overwrite of an input
    that was never authorised for writing.
"""

from __future__ import annotations

__all__ = [
    "CapsuleBusy",
    "CapsuleContainmentError",
    "CapsuleError",
    "CapsuleExportRefused",
    "CapsuleIsolationError",
    "CapsuleSchemaError",
    "CapsuleStateError",
    "CapsuleUnavailable",
]


class CapsuleError(Exception):
    """Base for every refusal produced by the capsule runtime."""

    code = "capsule-error"


class CapsuleSchemaError(CapsuleError):
    code = "malformed"


class CapsuleUnavailable(CapsuleError):
    code = "unavailable"


class CapsuleIsolationError(CapsuleError):
    code = "isolation-failed"


class CapsuleContainmentError(CapsuleError):
    code = "containment"


class CapsuleStateError(CapsuleError):
    code = "wrong-state"


class CapsuleBusy(CapsuleError):
    code = "busy"


class CapsuleExportRefused(CapsuleError):
    code = "export-refused"
