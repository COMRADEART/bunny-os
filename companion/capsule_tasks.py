# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an application task *is*, before anything runs it.

This module is the contract between the Companion, which knows what the user
asked for, and the Capsule, which knows how to run something safely. It holds no
authority of its own: it declares operations, validates the arguments one is
given, and names the failures. Nothing here launches, grants, or decides.

**Operations are a closed table, not a string.** A user's sentence never becomes
a command. What a request can reach is one of the entries in :data:`OPERATIONS`,
each of which states the capability it needs, the program it runs, how its
arguments are built from a validated parameter set, and the permission it will
have to ask for. A model may suggest which entry applies; it cannot add one, and
it cannot alter one. This is the same shape as
:mod:`companion.desktop.catalogue` and for the same reason — the alternative is
an ``argv`` assembled from text somebody typed.

**The program comes from the catalogue entry, not from here and not from the
request.** :data:`OPERATIONS` names a *capability* and a parameter schema; which
application supplies that capability is resolved against the installed
application catalogue at run time, and the executable path is whatever that
application's manifest says. An operation cannot name a binary.

**Failures are typed because the audit needs them to be.** §23's list is
:data:`FAILURE_CODES`, and each has a sentence a person can read attached to it.
The user-facing wording stays plain — "I couldn't start this app safely, so I
didn't run it" — while the record keeps which of eleven distinct things went
wrong. Collapsing them into one exception would make the wording honest and the
record useless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .errors import CompanionError

__all__ = [
    "FAILURE_CODES",
    "FAILURE_SENTENCES",
    "OPERATIONS",
    "ApplicationTaskRequest",
    "CapsuleTaskFailure",
    "OperationDescriptor",
    "operation",
    "output_name_for",
]


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #

#: §23. Every one of these is a different thing that happened, and the
#: distinction survives into the audit record even where the sentence a person
#: reads is the same.
FAILURE_CODES = (
    "APP_UNAVAILABLE",
    "PERMISSION_DENIED",
    "PERMISSION_EXPIRED",
    "TRUST_UNAVAILABLE",
    "CAPSULE_BACKEND_UNAVAILABLE",
    "CAPSULE_LAUNCH_FAILED",
    "CAPSULE_EXITED",
    "TASK_CANCELLED",
    "OUTPUT_MISSING",
    "OUTPUT_EXPORT_FAILED",
    "SECURITY_POLICY_BLOCKED",
)

#: What Bunny says. Plain, first person, and never a mechanism: §49 wants
#: "I couldn't start this app safely", not "bwrap: unshare: EPERM". The
#: mechanism lives in the failure's ``detail`` and in the audit record, where a
#: person who asks for details can reach it.
#:
#: Two codes deliberately share a sentence. ``CAPSULE_BACKEND_UNAVAILABLE`` and
#: ``CAPSULE_LAUNCH_FAILED`` are "Bunny would not run this without a sandbox"
#: told to somebody who does not care which half of the sandbox was missing —
#: and they stay separate codes because the person reading the audit does care.
FAILURE_SENTENCES: Mapping[str, str] = {
    "APP_UNAVAILABLE": "I don't have an app on this computer that can do that.",
    "PERMISSION_DENIED": "You didn't allow access to that file, so I stopped.",
    "PERMISSION_EXPIRED": "That permission had run out, so I asked nothing and did nothing.",
    "TRUST_UNAVAILABLE": "I couldn't check what you'd allowed, so I didn't go ahead.",
    "CAPSULE_BACKEND_UNAVAILABLE": "I couldn't start this app safely, so I didn't run it.",
    "CAPSULE_LAUNCH_FAILED": "I couldn't start this app safely, so I didn't run it.",
    "CAPSULE_EXITED": "The app stopped before it finished.",
    "TASK_CANCELLED": "I stopped, as you asked.",
    "OUTPUT_MISSING": "The app finished but didn't produce the file, so there's nothing to save.",
    "OUTPUT_EXPORT_FAILED": "I made the file but couldn't save it where you wanted.",
    "SECURITY_POLICY_BLOCKED": "This isn't something I'm allowed to do here.",
}


class CapsuleTaskFailure(CompanionError):
    """A typed failure of an application task.

    Carries the code, the sentence, and a ``detail`` that may name a mechanism.
    The detail reaches the audit record and the "Details" button; it never
    reaches the first line a person reads.

    A :class:`~companion.errors.CompanionError`, and that matters more than it
    looks. The runtime catches ``CompanionError`` and turns it into a failed
    task with a reason; anything else escapes. This was a plain ``Exception``,
    and a task whose operation could not be prepared — no input file, in the
    first booted journey — neither failed nor advanced. It sat in
    ``waiting_for_executor`` until the probe's window ran out, which reads as a
    hang rather than as the refusal it was.
    """

    def __init__(self, code: str, detail: str = "", *, retryable: bool = False) -> None:
        if code not in FAILURE_CODES:
            raise ValueError(f"unknown capsule task failure code: {code!r}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"{code}: {detail}" if detail else code)

    @property
    def sentence(self) -> str:
        return FAILURE_SENTENCES[self.code]

    def as_record(self) -> Mapping[str, Any]:
        return {
            "code": self.code,
            "sentence": self.sentence,
            "detail": self.detail,
            "retryable": self.retryable,
        }


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

#: A bounded positive integer, so that a parameter cannot be a sentence, a path,
#: a flag, or a number large enough to be a denial of service against the
#: machine that has to allocate it.
_MAX_PIXELS = 16384
_MIN_PIXELS = 16

#: Output names are built by Bunny, from the input's own name plus a suffix from
#: the operation. Neither the user's text nor the application's output ever
#: chooses the name, so a file cannot be written under a name that means
#: something to a shell, a desktop file scanner, or another application.
_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class OperationDescriptor:
    """One thing Bunny knows how to ask an application to do.

    ``capability`` is what the application catalogue is searched for.
    ``parameters`` is a closed schema: a key not named here is refused rather
    than passed through, so an argument nobody designed cannot reach a program.
    """

    operation_id: str
    #: What Bunny says it is doing, first person, present tense.
    summary: str
    capability: str
    #: name -> (kind, required). Kinds are ``"pixels"`` and ``"name-suffix"``;
    #: both validate to something that cannot be a path or a flag.
    parameters: Mapping[str, tuple[str, bool]]
    #: The permission categories this operation will ask for. Read-only file
    #: access for everything here: an operation that needed to *modify* the
    #: user's original would ask for ``write`` and say so in the prompt.
    permissions: tuple[str, ...] = ("files",)
    #: §43. The first operation is deliberately ``none``: destination
    #: allowlisting is not a boundary in this build, so an operation that wanted
    #: the network would be relying on something the evidence says is a
    #: declaration rather than a fence.
    network: str = "none"
    #: Whether the user's original file is touched. False everywhere here, and
    #: the completion sentence says so.
    modifies_input: bool = False
    #: Seconds. A deterministic local image operation that has not finished in
    #: this long has not finished.
    timeout_seconds: float = 120.0
    #: What is appended to the input's stem to name the result.
    output_suffix: str = "-bunny"
    #: The file extensions this operation accepts as input.
    input_extensions: tuple[str, ...] = ()

    def validate(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Return the validated parameter set, or raise.

        Refuses unknown keys rather than ignoring them. An ignored key is a
        parameter somebody believes is in effect and is not, which is how a
        resize to 1024 silently becomes a resize to the default.
        """
        unknown = sorted(set(parameters) - set(self.parameters))
        if unknown:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                f"{self.operation_id} has no parameter {unknown[0]!r}",
            )
        validated: dict[str, Any] = {}
        for name, (kind, required) in self.parameters.items():
            if name not in parameters:
                if required:
                    raise CapsuleTaskFailure(
                        "SECURITY_POLICY_BLOCKED", f"{self.operation_id} needs {name}"
                    )
                continue
            validated[name] = _validate_parameter(self.operation_id, name, kind, parameters[name])
        return validated


def _validate_parameter(operation_id: str, name: str, kind: str, value: Any) -> Any:
    if kind == "pixels":
        if isinstance(value, bool) or not isinstance(value, int):
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED", f"{operation_id}.{name} must be a whole number of pixels"
            )
        if not _MIN_PIXELS <= value <= _MAX_PIXELS:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                f"{operation_id}.{name} must be between {_MIN_PIXELS} and {_MAX_PIXELS}",
            )
        return int(value)
    raise CapsuleTaskFailure("SECURITY_POLICY_BLOCKED", f"unknown parameter kind {kind!r}")


#: The operations this build can perform. One, deliberately: §29 asks for the
#: architecture to be proved by a deterministic local operation before anything
#: interesting is attempted, and a table with one row is a table.
OPERATIONS: Mapping[str, OperationDescriptor] = {
    "image.resize": OperationDescriptor(
        operation_id="image.resize",
        summary="make a smaller copy of an image",
        capability="resize-image",
        parameters={"width": ("pixels", True)},
        permissions=("files",),
        network="none",
        modifies_input=False,
        output_suffix="-resized",
        input_extensions=(".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"),
    ),
}


def operation(operation_id: str) -> OperationDescriptor:
    """The descriptor, or a typed refusal. Never a default."""
    descriptor = OPERATIONS.get(operation_id)
    if descriptor is None:
        raise CapsuleTaskFailure(
            "SECURITY_POLICY_BLOCKED", f"{operation_id!r} is not an operation Bunny performs"
        )
    return descriptor


def output_name_for(descriptor: OperationDescriptor, source: Path) -> str:
    """The result's file name, built by Bunny from the input's.

    Not chosen by the user, not chosen by the application, and sanitised on the
    way through: a stem containing a path separator, a leading dash, or a
    control character becomes one that does not.
    """
    stem = _SAFE_STEM.sub("_", source.stem).lstrip("-._") or "image"
    suffix = source.suffix.lower()
    if suffix and not _SAFE_STEM.sub("", suffix.lstrip(".")):
        suffix = ""
    return f"{stem}{descriptor.output_suffix}{suffix or '.png'}"


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ApplicationTaskRequest:
    """§6. Everything needed to run one application task, and nothing else.

    Note what is absent, and why each absence is deliberate:

    * no Companion task history — an application has no business knowing what
      else the user has asked for;
    * no model reasoning — §28 forbids logging it and there is nowhere here to
      put it;
    * no provider credentials, no Trust database handle, no runtime reference;
    * no destination directory chosen by the application;
    * no free-text command.

    ``inputs`` are host paths the *user* named. They are not yet authorised;
    authorisation happens later and against these exact paths, which is what
    makes substitution detectable.
    """

    task_id: str
    #: The user's own words, kept for the record and for the prompt's context
    #: line. Never parsed into a command, never passed into the sandbox.
    user_intent: str
    operation_id: str
    parameters: Mapping[str, Any]
    inputs: tuple[Path, ...]
    destination: Path
    #: Resolved by the application resolver, from the catalogue. Empty until
    #: then, and a request with an empty application id cannot be launched.
    application_id: str = ""
    interactive: bool = False

    def __post_init__(self) -> None:
        if not self.task_id:
            raise CapsuleTaskFailure("SECURITY_POLICY_BLOCKED", "an application task needs a task id")
        if not self.inputs:
            raise CapsuleTaskFailure("SECURITY_POLICY_BLOCKED", "an application task needs an input")

    @property
    def descriptor(self) -> OperationDescriptor:
        return operation(self.operation_id)

    def validated_parameters(self) -> dict[str, Any]:
        return self.descriptor.validate(self.parameters)

    def as_record(self) -> Mapping[str, Any]:
        """For the audit. The user's intent is summarised, not quoted in full:
        §28 forbids logging private content, and a request can contain a file
        name a person would not want in a log they later share."""
        return {
            "taskId": self.task_id,
            "operationId": self.operation_id,
            "applicationId": self.application_id,
            "parameters": dict(self.validated_parameters()),
            "inputCount": len(self.inputs),
            "inputNames": [path.name for path in self.inputs],
            "interactive": self.interactive,
        }
