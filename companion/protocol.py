# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The private local contract between the runtime and whatever draws it.

One envelope, one direction, a fixed list of operations, and no way to name a
method that is not on the list. That last property is the design: this is not
RPC over the runtime's Python surface, it is a small set of named operations
each with a declared parameter shape, and a request for anything else is refused
before it reaches the runtime. There is no ``eval``, no import by name, no
attribute lookup from the wire, no pickle and no shell.

The transport is a Unix domain socket under ``$XDG_RUNTIME_DIR``, mode 0600 in a
directory mode 0700, with the peer's user id checked where the platform exposes
it. Those are three independent defences and each covers a case the others do
not: the directory mode stops another account reaching the socket at all, the
socket mode stops it if the directory was made permissive, and the peer check
stops it if both were somehow wrong. A local socket is the whole security
boundary here, so it gets all three.

A **developer fallback** exists for platforms with no ``AF_UNIX`` — Windows
being the one that matters, because that is where this is written. It binds
loopback TCP on an ephemeral port and requires a per-run token from a 0600 file
at the same path. It is not what ships, it is refused outright when
``BUNNY_COMPANION_REQUIRE_UNIX=1``, and :meth:`CompanionServer.describe` names
the transport in use so no measurement taken over it can be mistaken for one
taken over the real thing.

Two properties matter more than the wire format.

**A disconnecting client cancels nothing.** Each request is served on its own
connection and the runtime holds no reference to it afterwards. Closing the GTK
window therefore cannot stop a task, because there is nothing to stop: the task
belongs to the runtime's own worker and the socket was only ever how somebody
asked about it.

**Everything is bounded.** The request line, the response, every string, every
list and the number of events one call may return. A companion that will run in
64 MB cannot have a protocol whose worst case is "as much as the peer sends".
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading
from typing import Any, Callable, Mapping, Protocol as TypingProtocol
import uuid

from .ids import valid_id

__all__ = [
    "MAX_EVENT_PAGE",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "OPERATIONS",
    "PROTOCOL_SCHEMA_VERSION",
    "DESKTOP_OPERATIONS",
    "PROVIDER_OPERATIONS",
    "SPEECH_OPERATIONS",
    "CompanionClient",
    "CompanionClientError",
    "CompanionProtocol",
    "CompanionServer",
    "DuplicateRuntime",
    "PeerRefused",
    "ProtocolError",
    "RuntimeGateway",
    "RuntimeSingleton",
    "default_endpoint_path",
    "default_runtime_directory",
]

#: Version of the request and response envelope
#: (``schemas/companion-protocol.schema.json``).
#:
#: A peer naming a different version is refused rather than served with a guess.
#: There is deliberately no negotiation and no "closest supported version": a
#: downgrade that succeeds is a downgrade attack, and this is a local protocol
#: between two halves of the same build, which have no reason to differ.
PROTOCOL_SCHEMA_VERSION = 1

#: The request line ceiling. Generous enough for a task request at
#: :data:`companion.privacy.MAX_REQUEST_LENGTH` with its envelope, and small
#: enough that a peer cannot make the runtime hold a megabyte per connection.
MAX_REQUEST_BYTES = 64 * 1024

#: The response ceiling. A reply that would exceed it is replaced by an error
#: telling the caller to page, rather than truncated — a truncated JSON document
#: is not a shorter answer, it is an unparseable one.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

#: How many events one ``get_events`` call may return.
MAX_EVENT_PAGE = 500

#: How long the server will wait for a peer to finish sending, and the client
#: for a reply. A connection that stalls holds a thread; this is what stops a
#: peer holding all of them by opening connections and going quiet.
SOCKET_TIMEOUT_SECONDS = 30.0

_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700


class ProtocolError(ValueError):
    """A request this protocol will not serve. Carries the wire error code."""

    code = "invalid_request"


class UnknownOperation(ProtocolError):
    code = "unknown_operation"


class RequestTooLarge(ProtocolError):
    code = "request_too_large"


class UnsupportedVersion(ProtocolError):
    code = "unsupported_version"


class PeerRefused(ProtocolError):
    code = "permission_denied"


class DuplicateRuntime(RuntimeError):
    """Another runtime is already listening on this endpoint."""


def default_runtime_directory() -> Path:
    """Where the socket lives.

    ``$XDG_RUNTIME_DIR`` first: it is per-user, mode 0700 by construction, and
    cleared when the session ends, which is exactly the lifetime a socket
    should have. The state directory is the fallback for a session that has no
    runtime directory — a container, or a user logged in over ssh — and is
    created 0700 here rather than trusted to be.
    """
    override = os.environ.get("BUNNY_COMPANION_SOCKET_DIR")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "bunny-companion"
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "bunny-os" / "companion" / "runtime"


def default_endpoint_path() -> Path:
    return default_runtime_directory() / "runtime.sock"


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Parameter:
    """One declared parameter. Undeclared is refused, not ignored."""

    name: str
    kind: str = "string"
    required: bool = False
    default: Any = None
    maximum_length: int = 8192
    minimum: int = 0
    maximum: int = 1 << 31

    def coerce(self, value: Any) -> Any:
        if self.kind == "string":
            if not isinstance(value, str):
                raise ProtocolError(f"{self.name} must be a string")
            if len(value) > self.maximum_length:
                raise RequestTooLarge(
                    f"{self.name} is {len(value)} characters against a limit of {self.maximum_length}"
                )
            return value
        if self.kind == "identifier":
            if not isinstance(value, str) or not valid_id(value):
                raise ProtocolError(f"{self.name} is not a usable identifier")
            return value
        if self.kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProtocolError(f"{self.name} must be an integer")
            if not self.minimum <= value <= self.maximum:
                raise ProtocolError(
                    f"{self.name} must be between {self.minimum} and {self.maximum}"
                )
            return value
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise ProtocolError(f"{self.name} must be true or false")
            return value
        if self.kind == "object":
            if not isinstance(value, Mapping):
                raise ProtocolError(f"{self.name} must be an object")
            if len(value) > 64:
                raise RequestTooLarge(f"{self.name} has too many fields")
            return dict(value)
        raise ProtocolError(f"{self.name} has an unsupported parameter kind")


@dataclass(frozen=True)
class Operation:
    """One thing a client may ask for."""

    name: str
    parameters: tuple[Parameter, ...] = ()
    #: ``True`` when serving this changes something. Reported by ``health`` so a
    #: client — or a person reading a transcript — can see which half of this
    #: protocol is read-only without knowing the implementation.
    mutating: bool = False

    def validate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        declared = {item.name: item for item in self.parameters}
        unknown = sorted(set(params) - set(declared))
        if unknown:
            # Fail closed. An ignored parameter is a parameter a caller believes
            # took effect, and the first time one of them means "and skip the
            # approval" the silence becomes the vulnerability.
            raise ProtocolError(
                f"{self.name} does not accept: {', '.join(unknown)}"
            )
        resolved: dict[str, Any] = {}
        for item in self.parameters:
            if item.name not in params:
                if item.required:
                    raise ProtocolError(f"{self.name} requires {item.name}")
                resolved[item.name] = item.default
                continue
            resolved[item.name] = item.coerce(params[item.name])
        return resolved


#: Every operation this protocol serves. There is no generic filesystem,
#: command, provider or attribute operation here and none may be added: a client
#: is a *view*, and a view that could name a tool would be an executor.
OPERATIONS: Mapping[str, Operation] = {
    item.name: item
    for item in (
        Operation("health"),
        Operation(
            "create_session",
            (
                Parameter("title", "string", maximum_length=200, default="Companion session"),
                Parameter("locality", "string", maximum_length=32, default="device-only"),
                Parameter("allowRemote", "boolean", default=False),
                Parameter("taskLimitUnits", "integer", default=0, maximum=1_000_000),
                Parameter("sessionLimitUnits", "integer", default=0, maximum=1_000_000),
            ),
            mutating=True,
        ),
        Operation("list_sessions"),
        Operation("get_session", (Parameter("sessionId", "identifier", required=True),)),
        Operation(
            "submit_task",
            (
                Parameter("sessionId", "identifier", required=True),
                Parameter("request", "string", required=True, maximum_length=8192),
                Parameter("classification", "string", maximum_length=32, default=None),
                Parameter("costLimitUnits", "integer", default=None, maximum=1_000_000),
                Parameter("run", "boolean", default=True),
            ),
            mutating=True,
        ),
        Operation(
            "list_tasks",
            (Parameter("sessionId", "identifier", default=None),),
        ),
        Operation(
            "get_task",
            (
                Parameter("taskId", "identifier", required=True),
                Parameter("sessionId", "identifier", default=None),
            ),
        ),
        Operation(
            "get_events",
            (
                Parameter("taskId", "identifier", default=None),
                Parameter("sessionId", "identifier", default=None),
                Parameter("afterSequence", "integer", default=0, maximum=1 << 40),
                Parameter("limit", "integer", default=MAX_EVENT_PAGE, minimum=1, maximum=MAX_EVENT_PAGE),
            ),
        ),
        Operation(
            "get_presentation_state",
            (
                Parameter("taskId", "identifier", default=None),
                Parameter("sessionId", "identifier", default=None),
                Parameter("afterSequence", "integer", default=0, maximum=1 << 40),
                Parameter("limit", "integer", default=MAX_EVENT_PAGE, minimum=1, maximum=MAX_EVENT_PAGE),
            ),
        ),
        Operation(
            "resolve_approval",
            (
                # Every binding field §9 names. The runtime checks all of them
                # against the request it recorded; a client that changed any one
                # is refused rather than obeyed.
                Parameter("requestId", "string", required=True, maximum_length=512),
                Parameter("sessionId", "identifier", required=True),
                Parameter("taskId", "identifier", required=True),
                Parameter("planId", "string", required=True, maximum_length=256),
                Parameter("transitionId", "string", required=True, maximum_length=512),
                Parameter("action", "string", required=True, maximum_length=64),
                Parameter("destination", "string", required=True, maximum_length=256),
                Parameter("providerId", "string", default="", maximum_length=256),
                Parameter("dataClassification", "string", required=True, maximum_length=32),
                Parameter("estimatedCostUnits", "integer", default=None, maximum=1_000_000),
                Parameter("destinationFingerprint", "string", default="", maximum_length=128),
                Parameter("decision", "string", required=True, maximum_length=16),
            ),
            mutating=True,
        ),
        Operation(
            "cancel_task",
            (
                Parameter("taskId", "identifier", required=True),
                Parameter("sessionId", "identifier", default=None),
                Parameter("cause", "string", maximum_length=32, default="user"),
                Parameter("detail", "string", maximum_length=512, default=""),
            ),
            mutating=True,
        ),
        Operation(
            "pause_task",
            (
                Parameter("taskId", "identifier", required=True),
                Parameter("sessionId", "identifier", default=None),
            ),
            mutating=True,
        ),
        Operation(
            "resume_task",
            (
                Parameter("taskId", "identifier", required=True),
                Parameter("sessionId", "identifier", default=None),
            ),
            mutating=True,
        ),
        # Focused voice preferences. A complete document is written in one
        # operation so omitted fields can never silently reset an unrelated
        # preference, and no credential-shaped field exists on the surface.
        Operation("settings_voice_get"),
        Operation(
            "settings_voice_set",
            (
                Parameter("voiceInput", "boolean", required=True),
                Parameter("speechResponses", "boolean", required=True),
                Parameter("responseMode", "string", required=True, maximum_length=16),
                Parameter("deviceId", "string", default="", maximum_length=128),
                Parameter("modelId", "string", default="", maximum_length=128),
                Parameter("language", "string", required=True, maximum_length=16),
                Parameter("shortcut", "string", required=True, maximum_length=64),
                Parameter("wakeWord", "string", required=True, maximum_length=16),
            ),
            mutating=True,
        ),
        # -- speech ------------------------------------------------------
        #
        # §17's eight, and deliberately no ninth. Note what none of them takes:
        # no executable, no argument list, no output path, no provider module,
        # no URL, no device handle. ``voice_speak`` does not even take *text* —
        # it takes a caption identifier, and the runtime derives the utterance
        # from the caption it already published. A client cannot make the
        # companion say something the user was not shown, which is §8 enforced
        # by the shape of the request rather than by a check inside it.
        Operation("voice_health"),
        Operation(
            "voice_list",
            (
                Parameter("language", "string", maximum_length=8, default=""),
                Parameter("limit", "integer", default=64, minimum=1, maximum=512),
            ),
        ),
        Operation("voice_status"),
        Operation(
            "voice_speak",
            (
                Parameter("captionId", "identifier", required=True),
                Parameter("priority", "string", maximum_length=32, default=""),
                Parameter("interruptionPolicy", "string", maximum_length=32, default=""),
                Parameter("voiceId", "string", maximum_length=64, default=""),
                # An explicit "read that again". §20 permits a replay only as a
                # new request from a person; nothing in the runtime sets this.
                Parameter("replay", "boolean", default=False),
            ),
            mutating=True,
        ),
        Operation(
            "voice_cancel",
            (
                Parameter("requestId", "identifier", default=""),
                Parameter("taskId", "identifier", default=""),
                Parameter("cancellationToken", "identifier", default=""),
            ),
            mutating=True,
        ),
        Operation("voice_pause", mutating=True),
        Operation("voice_resume", mutating=True),
        Operation(
            "voice_explain",
            (Parameter("requestId", "identifier", default=""),),
        ),
        # -- speech input ------------------------------------------------
        #
        # §20's eight, and deliberately no ninth. Note what none of them
        # takes: no executable, no model path, no recording destination, no
        # raw-audio retrieval, no URL, no arbitrary device command.
        # ``speech_input_start`` names an *activation source* from a closed
        # set the request schema enforces, and every free string it accepts is
        # bounded here and validated again, more narrowly, at construction of
        # the request. A client cannot make the runtime record to a path,
        # load a model, or open a microphone silently — the operations have
        # nowhere to put any of those asks.
        Operation("speech_input_health"),
        Operation("speech_input_devices"),
        Operation(
            "speech_input_start",
            (
                Parameter("sessionId", "identifier", required=True),
                Parameter("activationSource", "string", required=True, maximum_length=64),
                Parameter("language", "string", maximum_length=8, default=""),
                Parameter("locale", "string", maximum_length=16, default=""),
                Parameter("deviceId", "string", maximum_length=128, default=""),
                Parameter("providerId", "string", maximum_length=64, default=""),
                Parameter("maxCaptureMs", "integer", default=30_000, minimum=1_000, maximum=300_000),
                Parameter("initialSilenceMs", "integer", default=6_000, minimum=200, maximum=30_000),
                Parameter("endpointSilenceMs", "integer", default=1_200, minimum=200, maximum=30_000),
                Parameter("partialTranscripts", "boolean", default=True),
                Parameter("confirmationRequired", "boolean", default=True),
                Parameter("presentationRevision", "integer", default=0, maximum=1 << 40),
            ),
            mutating=True,
        ),
        Operation("speech_input_status"),
        Operation(
            "speech_input_stop",
            (Parameter("requestId", "identifier", required=True),),
            mutating=True,
        ),
        Operation(
            "speech_input_cancel",
            (
                Parameter("requestId", "identifier", required=True),
                Parameter("cancellationToken", "identifier", default=""),
            ),
            mutating=True,
        ),
        Operation(
            "speech_input_confirm",
            (
                # The binding fields: the session the transcript belongs to and
                # the digest of the text the user reviewed. The runtime checks
                # both against what it holds; a confirmation about different
                # words or a different session is refused rather than obeyed.
                Parameter("requestId", "identifier", required=True),
                Parameter("sessionId", "identifier", required=True),
                # 4000, the transcript bound, not the 8192 request bound: an
                # edited transcript is still a transcript.
                Parameter("text", "string", maximum_length=4000, default=None),
                Parameter("reviewedDigest", "string", maximum_length=128, default=""),
                Parameter("cancellationToken", "identifier", default=""),
            ),
            mutating=True,
        ),
        Operation(
            "speech_input_retry",
            (
                Parameter("requestId", "identifier", required=True),
                Parameter("activationSource", "string", required=True, maximum_length=64),
            ),
            mutating=True,
        ),
        # -- agent providers (§21). Note what is absent: no operation carries
        # a credential, names an arbitrary endpoint, or mutates provider
        # configuration. Configuration is a file the user edits; these
        # operations only read, explain, test locally, and cancel.
        Operation("providers_list"),
        Operation("providers_status"),
        Operation(
            "providers_explain",
            (
                Parameter("taskClass", "string", required=True, maximum_length=32),
                Parameter("classification", "string", maximum_length=32, default="internal"),
                Parameter("locality", "string", maximum_length=32, default="device-only"),
                Parameter("needsStructuredOutput", "boolean", default=False),
                Parameter("needsToolProposals", "boolean", default=False),
            ),
        ),
        Operation("provider_models", (Parameter("providerId", "identifier", required=True),)),
        Operation("provider_health", (Parameter("providerId", "identifier", default=None),)),
        Operation(
            "provider_test_local",
            (Parameter("providerId", "identifier", default=None),),
            mutating=True,
        ),
        Operation("task_provider_status", (Parameter("taskId", "identifier", required=True),)),
        Operation(
            "task_provider_cancel",
            (Parameter("taskId", "identifier", required=True),),
            mutating=True,
        ),
        # -- desktop actions (§21). Note the shape of what is absent. There is
        # no operation here that performs an action: a client can list, explain,
        # inspect, stop and undo, and the only way to *cause* a desktop effect
        # is a task whose plan proposes one and a person who approves it. An
        # operation that took an action id and parameters would be a generic
        # tool invocation with a narrow name, and it would let a client bypass
        # the whole of §2's pipeline.
        #
        # Nor is there a parameter anywhere below that names an application, a
        # path, a URI, a command, a D-Bus destination or a backend. Every
        # identifier here refers to something the runtime already holds.
        Operation("desktop_actions_list"),
        Operation("desktop_actions_status"),
        Operation(
            "desktop_action_explain",
            (Parameter("actionId", "string", required=True, maximum_length=64),),
        ),
        Operation(
            "desktop_action_cancel",
            (
                Parameter("requestId", "identifier", required=True),
                Parameter("cancellationToken", "identifier", default=""),
            ),
            mutating=True,
        ),
        Operation(
            "desktop_action_undo",
            (
                # The idempotency key of the action to undo. It names an entry
                # in the ledger; it cannot name anything else, and an undo is
                # derived from what that entry recorded rather than from
                # anything the caller supplies.
                Parameter("idempotencyKey", "string", required=True, maximum_length=64),
                Parameter("sessionId", "identifier", default=None),
            ),
            mutating=True,
        ),
        Operation(
            "desktop_action_history",
            (
                Parameter("taskId", "identifier", default=None),
                Parameter("limit", "integer", default=25, minimum=1, maximum=200),
            ),
        ),
    )
}

#: The speech subset, by name. Kept as a derived view rather than a second
#: literal so that the two can never disagree about what a parameter is bounded
#: at — :mod:`companion.voice.service` validates against exactly these objects.
VOICE_OPERATIONS: Mapping[str, Operation] = {
    name: item for name, item in OPERATIONS.items() if name.startswith("voice_")
}

#: The speech-input subset, derived for the same reason:
#: :mod:`companion.speech.service` validates against exactly these objects, so
#: the schema a client is checked against and the schema the service serves are
#: one table read twice.
SPEECH_OPERATIONS: Mapping[str, Operation] = {
    name: item for name, item in OPERATIONS.items() if name.startswith("speech_input_")
}

#: The agent-provider subset, derived for the same reason:
#: :mod:`companion.agents.service` validates against exactly these objects.
PROVIDER_OPERATIONS: Mapping[str, Operation] = {
    name: item for name, item in OPERATIONS.items()
    if name.startswith(("providers_", "provider_", "task_provider_"))
}

#: The desktop-action subset, derived for the same reason:
#: :mod:`companion.desktop.service` validates against exactly these objects, so
#: the schema a client is checked against and the schema the service serves are
#: one table read twice.
DESKTOP_OPERATIONS: Mapping[str, Operation] = {
    name: item for name, item in OPERATIONS.items()
    if name.startswith(("desktop_actions_", "desktop_action_"))
}


class RuntimeGateway(TypingProtocol):
    """What the transport is allowed to call.

    Deliberately one method per operation and nothing else. The gateway holds
    the runtime; the transport holds the gateway; so the widest thing a peer can
    reach is this interface, and reviewing what a client can do means reading
    this list rather than the runtime's whole surface.
    """

    def health(self) -> Mapping[str, Any]: ...
    def create_session(self, **params: Any) -> Mapping[str, Any]: ...
    def list_sessions(self, **params: Any) -> Mapping[str, Any]: ...
    def get_session(self, **params: Any) -> Mapping[str, Any]: ...
    def submit_task(self, **params: Any) -> Mapping[str, Any]: ...
    def list_tasks(self, **params: Any) -> Mapping[str, Any]: ...
    def get_task(self, **params: Any) -> Mapping[str, Any]: ...
    def get_events(self, **params: Any) -> Mapping[str, Any]: ...
    def get_presentation_state(self, **params: Any) -> Mapping[str, Any]: ...
    def resolve_approval(self, **params: Any) -> Mapping[str, Any]: ...
    def cancel_task(self, **params: Any) -> Mapping[str, Any]: ...
    def pause_task(self, **params: Any) -> Mapping[str, Any]: ...
    def resume_task(self, **params: Any) -> Mapping[str, Any]: ...
    def settings_voice_get(self, **params: Any) -> Mapping[str, Any]: ...
    def settings_voice_set(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_health(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_list(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_status(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_speak(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_cancel(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_pause(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_resume(self, **params: Any) -> Mapping[str, Any]: ...
    def voice_explain(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_health(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_devices(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_start(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_status(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_stop(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_cancel(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_confirm(self, **params: Any) -> Mapping[str, Any]: ...
    def speech_input_retry(self, **params: Any) -> Mapping[str, Any]: ...
    def providers_list(self) -> Mapping[str, Any]: ...
    def providers_status(self) -> Mapping[str, Any]: ...
    def providers_explain(self, **params: Any) -> Mapping[str, Any]: ...
    def provider_models(self, **params: Any) -> Mapping[str, Any]: ...
    def provider_health(self, **params: Any) -> Mapping[str, Any]: ...
    def provider_test_local(self, **params: Any) -> Mapping[str, Any]: ...
    def task_provider_status(self, **params: Any) -> Mapping[str, Any]: ...
    def task_provider_cancel(self, **params: Any) -> Mapping[str, Any]: ...


class CompanionProtocol:
    """Envelope validation and dispatch. Holds no socket and no state."""

    def __init__(self, gateway: RuntimeGateway, *, transport_token: str = "") -> None:
        self.gateway = gateway
        self.transport_token = transport_token

    def dispatch(self, document: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(document, Mapping):
            raise ProtocolError("a request must be a JSON object")
        version = document.get("schemaVersion")
        if version != PROTOCOL_SCHEMA_VERSION:
            raise UnsupportedVersion(
                f"this runtime speaks protocol version {PROTOCOL_SCHEMA_VERSION} and the request "
                f"declared {version!r}; there is no downgrade path"
            )
        if self.transport_token:
            supplied = document.get("transportToken")
            # Compared in constant time. The token is the whole of the peer
            # check on the loopback fallback, and a comparison that returned
            # early would leak it a byte at a time to a local process that can
            # reconnect as often as it likes.
            if not isinstance(supplied, str) or not _constant_time_equal(supplied, self.transport_token):
                raise PeerRefused("the loopback transport token is missing or wrong")
        request_id = document.get("requestId")
        if not isinstance(request_id, str) or not valid_id(request_id):
            raise ProtocolError("requestId is not a usable identifier")
        name = document.get("operation")
        if not isinstance(name, str):
            raise ProtocolError("operation must be a string")
        operation = OPERATIONS.get(name)
        if operation is None:
            raise UnknownOperation(f"unknown operation: {name!r}")
        params = document.get("params", {})
        if not isinstance(params, Mapping):
            raise ProtocolError("params must be an object")
        resolved = operation.validate(params)
        # Looked up on the gateway by a name from the table, never from the
        # wire. `getattr(self.gateway, name)` with `name` off the wire would be
        # arbitrary method invocation with extra steps.
        handler: Callable[..., Mapping[str, Any]] = getattr(self.gateway, operation.name)
        result = handler(**resolved) if resolved else handler()
        if not isinstance(result, Mapping):
            raise ProtocolError(f"{name} produced no result document")
        return {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id,
            "operation": name,
            "ok": True,
            "result": dict(result),
        }

    @staticmethod
    def error_response(request_id: str, operation: str, exc: BaseException) -> dict[str, Any]:
        """Turn a refusal into a structured answer.

        The message is bounded and stripped of everything but the sentence. A
        stack trace on the wire is a map of the runtime's internals handed to
        whatever asked for it, and the useful part — *which* refusal this was —
        is in the code.
        """
        from .errors import (
            ApprovalDenied,
            ApprovalError,
            ApprovalExpired,
            ApprovalMismatch,
            ApprovalReplayed,
            CapabilityRefused,
            CompanionError,
            CoordinationLimitExceeded,
            IntegrityError,
            InvalidTransition,
            StoreError,
        )

        code = getattr(exc, "code", "")
        if not code:
            if isinstance(exc, ApprovalExpired):
                code = "approval_expired"
            elif isinstance(exc, ApprovalReplayed):
                code = "approval_replayed"
            elif isinstance(exc, ApprovalMismatch):
                code = "approval_mismatch"
            elif isinstance(exc, ApprovalDenied):
                code = "approval_denied"
            elif isinstance(exc, ApprovalError):
                code = "approval_error"
            elif isinstance(exc, CapabilityRefused):
                code = "capability_refused"
            elif isinstance(exc, CoordinationLimitExceeded):
                code = "limit_exceeded"
            elif isinstance(exc, InvalidTransition):
                code = "invalid_transition"
            elif isinstance(exc, IntegrityError):
                code = "integrity_error"
            elif isinstance(exc, StoreError):
                code = "store_error"
            elif isinstance(exc, PermissionError):
                code = "permission_denied"
            elif isinstance(exc, KeyError):
                code = "not_found"
            elif isinstance(exc, CompanionError):
                code = "runtime_refused"
            elif isinstance(exc, (TypeError, ValueError)):
                code = "invalid_request"
            else:
                code = "runtime_error"
        message = " ".join(str(exc).split())[:512] or type(exc).__name__
        return {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id if valid_id(request_id) else "request-invalid",
            "operation": operation if operation in OPERATIONS else "",
            "ok": False,
            "error": {"code": code, "message": message},
        }


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _encode(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"


# --------------------------------------------------------------------------- #
# The server
# --------------------------------------------------------------------------- #


class _Handler(socketserver.StreamRequestHandler):
    timeout = SOCKET_TIMEOUT_SECONDS

    def _peer_permitted(self) -> bool:
        check = getattr(self.server, "peer_check", None)
        if check is not None:
            return bool(check(self.request))
        return True

    def handle(self) -> None:
        request_id = "request-invalid"
        operation = ""
        protocol: CompanionProtocol = self.server.protocol  # type: ignore[attr-defined]
        try:
            if not self._peer_permitted():
                raise PeerRefused("the peer is not the session user")
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(line) > MAX_REQUEST_BYTES:
                raise RequestTooLarge(
                    f"the request exceeds the {MAX_REQUEST_BYTES} byte limit and was not read"
                )
            if not line or not line.endswith(b"\n"):
                raise ProtocolError("a request is one newline-terminated JSON object")
            try:
                document = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"the request is not valid UTF-8 JSON: {exc}") from exc
            if isinstance(document, Mapping):
                candidate = document.get("requestId")
                if isinstance(candidate, str) and valid_id(candidate):
                    request_id = candidate
                candidate_operation = document.get("operation")
                if isinstance(candidate_operation, str):
                    operation = candidate_operation
            response = protocol.dispatch(document)
        except BaseException as exc:  # every refusal becomes a structured answer
            response = protocol.error_response(request_id, operation, exc)
        encoded = _encode(response)
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = _encode(protocol.error_response(
                request_id, operation,
                ProtocolError(
                    "the answer exceeds the response limit; ask again with a smaller "
                    "'limit' and an 'afterSequence'"
                ),
            ))
        try:
            self.wfile.write(encoded)
        except OSError:
            # The client went away mid-answer. Nothing to do and nothing to
            # cancel: the work this described is the runtime's, not the
            # connection's.
            return


def _peer_uid_check(connection: Any) -> bool:
    """Whether the peer runs as this user, where the platform can say.

    ``SO_PEERCRED`` is authoritative — it is filled in by the kernel from the
    connecting process and cannot be forged by the peer. Where it does not
    exist the answer is ``True`` and the directory and file modes are the whole
    defence; :meth:`CompanionServer.describe` reports which of the two applies
    so a security claim is never made about a platform that cannot support it.
    """
    if not hasattr(socket, "SO_PEERCRED") or not hasattr(os, "getuid"):
        return True
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
    except OSError:
        # The credential could not be read. Refused: a peer whose identity
        # cannot be established is not the session user by default.
        return False
    return uid == os.getuid()


if hasattr(socket, "AF_UNIX"):

    class _UnixServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        """``socketserver`` omits ``ThreadingUnixStreamServer`` on some builds."""

        address_family = socket.AF_UNIX
        socket_type = socket.SOCK_STREAM
        daemon_threads = True
        block_on_close = True
        allow_reuse_address = False

        def __init__(self, path: str, protocol: CompanionProtocol) -> None:
            self.protocol = protocol
            self.peer_check = _peer_uid_check
            super().__init__(path, _Handler)

else:  # pragma: no cover - exercised only on platforms without AF_UNIX
    _UnixServer = None  # type: ignore[assignment,misc]


class _LoopbackServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, protocol: CompanionProtocol) -> None:
        self.protocol = protocol
        self.peer_check = None
        super().__init__(("127.0.0.1", 0), _Handler)


class RuntimeSingleton:
    """The claim on "one runtime owns this session", taken before anything binds.

    Two things share this responsibility and they are not the same thing.

    The *probe* — connect to the endpoint and see whether anybody answers —
    tells a live runtime from a crashed one, and must: a live runtime must not
    be displaced, because two runtimes over one store would both drive tasks and
    both believe they held the lease; and a stale socket must be removed,
    because a crash must not make the companion permanently unstartable.

    The probe alone is racy, and the race is not theoretical. Two services
    starting together both find no endpoint, both decide it is stale, both
    unlink and both bind — and the second unlinks the first's socket out from
    under it. The loser keeps serving on a socket no client can reach. So the
    probe runs *underneath an exclusive advisory lock* on a file beside the
    endpoint, held for the life of the process by the kernel.

    A lock file rather than a second exclusion mechanism with its own idea of
    liveness: the lock is held by the open descriptor, so a process that dies —
    for any reason, including SIGKILL — releases it, and there is no stale state
    to reconcile. The file's continued existence means nothing and is never
    consulted.
    """

    def __init__(self, endpoint: Path) -> None:
        self.endpoint = Path(endpoint)
        self.path = self.endpoint.with_name(self.endpoint.name + ".lock")
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> "RuntimeSingleton":
        """Take the claim, or raise :class:`DuplicateRuntime`."""
        if self._descriptor is not None:
            raise RuntimeError("this singleton is already held")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, _FILE_MODE)
        try:
            _lock_exclusive(descriptor)
        except OSError as exc:
            os.close(descriptor)
            raise DuplicateRuntime(
                f"another Bunny companion runtime holds {self.path}; one runtime owns "
                "the session"
            ) from exc
        except NotImplementedError:
            # No advisory locking on this platform. The probe below is then the
            # whole of the exclusion, which is what it was before this class
            # existed — recorded rather than pretended away.
            pass
        self._descriptor = descriptor
        return self

    def release(self) -> None:
        """Give it up. Safe to call twice, and safe after a fault."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            _unlock(descriptor)
        except OSError:  # pragma: no cover - the descriptor is going away anyway
            pass
        os.close(descriptor)
        try:
            self.path.unlink()
        except OSError:
            pass

    def describe(self) -> dict[str, Any]:
        return {
            "lockPath": str(self.path),
            "held": self.held,
            "advisoryLockingAvailable": _ADVISORY_LOCKING,
        }

    def __enter__(self) -> "RuntimeSingleton":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


try:  # pragma: no cover - one branch per platform
    import fcntl

    _ADVISORY_LOCKING = True

    def _lock_exclusive(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)

except ImportError:  # pragma: no cover - Windows development hosts
    try:
        import msvcrt

        _ADVISORY_LOCKING = True

        def _lock_exclusive(descriptor: int) -> None:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

        def _unlock(descriptor: int) -> None:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

    except ImportError:
        _ADVISORY_LOCKING = False

        def _lock_exclusive(descriptor: int) -> None:
            raise NotImplementedError("this platform has no advisory file locking")

        def _unlock(descriptor: int) -> None:
            raise NotImplementedError("this platform has no advisory file locking")


class CompanionServer:
    """Binds the endpoint, refuses a second runtime, and serves requests.

    The gateway may be attached after the bind. That is not a convenience: it is
    what lets a service acquire its singleton and bind its endpoint *before* it
    builds anything that owns a thread, so a refusal at the door costs nothing
    to unwind. Requests cannot arrive before :meth:`start`, and :meth:`start`
    refuses without a gateway.
    """

    def __init__(
        self,
        gateway: RuntimeGateway | None = None,
        endpoint: Path | None = None,
        *,
        require_unix: bool | None = None,
        prefer_loopback: bool = False,
        singleton: RuntimeSingleton | None = None,
    ) -> None:
        """``prefer_loopback`` is a diagnostic, and only a diagnostic.

        It forces the developer TCP transport on a platform that has ``AF_UNIX``,
        so the two transports can be compared on one machine under one workload:
        identical code, identical tests, only the transport differs. It was
        added to test the hypothesis that the intermittent suite failure came
        from the loopback fallback. On Linux the experiment refuted that
        hypothesis rather than confirming it — 20 slices over ``AF_UNIX`` and 20
        over forced loopback both passed, with a peak ``TIME_WAIT`` count of
        zero. The argument stays because a refuting experiment is worth being
        able to repeat, and because it is the only way to reach the fallback
        transport on a machine that has ``AF_UNIX``.

        It is a constructor argument and not an environment variable on purpose:
        nothing outside a test or a stress harness can reach it, and
        :class:`companion.service.CompanionService` only passes it when a
        caller has explicitly set it in :class:`~companion.service.ServiceOptions`.
        """
        self.endpoint = Path(endpoint or default_endpoint_path())
        self.unix = hasattr(socket, "AF_UNIX") and not prefer_loopback
        if require_unix is None:
            require_unix = os.environ.get("BUNNY_COMPANION_REQUIRE_UNIX") == "1"
        if require_unix and not self.unix:
            raise RuntimeError(
                "BUNNY_COMPANION_REQUIRE_UNIX is set and this platform has no AF_UNIX; "
                "the loopback fallback is a developer transport and was refused"
            )
        self.transport_token = ""
        self._thread: threading.Thread | None = None
        self.gateway = gateway
        #: ``None`` when the caller did not acquire one, in which case the
        #: probe below is the whole of the exclusion — the arrangement that
        #: shipped before :class:`RuntimeSingleton` existed, and the one every
        #: test that constructs a bare server still uses.
        self.singleton = singleton
        self._make_directory()
        # Always. When a singleton is held the probe cannot race another
        # starter, and what it is still doing is the stale-endpoint removal —
        # which is not about exclusion at all: a crashed runtime leaves a socket
        # file behind and ``bind()`` would fail on it. When no singleton was
        # acquired the probe is the whole of the exclusion, as it was before.
        self._refuse_duplicate()
        if self.unix:
            protocol = CompanionProtocol(gateway) if gateway is not None else None
            self._server = _UnixServer(str(self.endpoint), protocol)
            _restrict(self.endpoint)
        else:
            self.transport_token = uuid.uuid4().hex
            protocol = (
                CompanionProtocol(gateway, transport_token=self.transport_token)
                if gateway is not None else None
            )
            self._server = _LoopbackServer(protocol)
            self._write_endpoint_file()

    def attach(self, gateway: RuntimeGateway) -> None:
        """Give the bound endpoint something to serve.

        Safe because nothing is serving yet: the socket is bound and listening
        at the kernel, and a connection that arrives before :meth:`start` sits
        in the accept backlog. There is no window in which a request reaches a
        protocol with no gateway behind it.
        """
        if self._thread is not None:
            raise RuntimeError("this server is already serving; the gateway cannot be replaced")
        self.gateway = gateway
        self._server.protocol = (
            CompanionProtocol(gateway, transport_token=self.transport_token)
            if self.transport_token else CompanionProtocol(gateway)
        )

    # -- endpoint ----------------------------------------------------------

    def _make_directory(self) -> None:
        directory = self.endpoint.parent
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(_DIRECTORY_MODE)
        except OSError:
            # A filesystem with no POSIX modes. The peer check and the token are
            # what remain, and `describe` says so.
            pass

    def _refuse_duplicate(self) -> None:
        """Refuse to start beside another runtime, and refuse to be tricked
        into replacing something that is not an endpoint.

        Two different failures share this path. A *live* runtime must not be
        displaced — two runtimes over one store would both drive tasks and both
        believe they held the lease. A *stale* endpoint must be removed, because
        a crashed runtime must not make the companion permanently unstartable.
        Telling them apart is done by connecting: a socket somebody answers is
        alive, and one nobody answers is not.
        """
        if self.endpoint.is_symlink():
            raise PeerRefused(
                f"{self.endpoint} is a symbolic link; refusing to bind through it"
            )
        if not self.endpoint.exists():
            return
        if self.unix:
            status = self.endpoint.stat()
            if hasattr(stat, "S_ISSOCK") and os.name == "posix" and not stat.S_ISSOCK(status.st_mode):
                raise PeerRefused(
                    f"{self.endpoint} exists and is not a socket; refusing to replace it"
                )
            address: Any = str(self.endpoint)
            family = socket.AF_UNIX
        else:
            try:
                document = json.loads(self.endpoint.read_text(encoding="utf-8"))
                host = str(document["host"])
                port = int(document["port"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PeerRefused(
                    f"{self.endpoint} exists and is not a companion endpoint; refusing to replace it"
                ) from exc
            if host != "127.0.0.1":
                raise PeerRefused("the recorded endpoint is not private loopback")
            address = (host, port)
            family = socket.AF_INET
        probe = socket.socket(family, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.25)
            probe.connect(address)
        except OSError:
            self.endpoint.unlink()
        else:
            raise DuplicateRuntime(
                "another Bunny companion runtime is already listening on this endpoint; "
                "one runtime owns the session"
            )
        finally:
            probe.close()

    def _write_endpoint_file(self) -> None:
        document = {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "transport": "loopback-tcp",
            "host": "127.0.0.1",
            "port": int(self._server.server_address[1]),
            "token": self.transport_token,
        }
        temporary = self.endpoint.with_name(self.endpoint.name + ".new")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True) + "\n")
        os.replace(temporary, self.endpoint)
        _restrict(self.endpoint)

    # -- lifecycle ---------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """What this endpoint actually is. Never a claim the platform cannot back."""
        return {
            "endpoint": str(self.endpoint),
            "transport": "unix-socket" if self.unix else "loopback-tcp",
            "peerUserValidated": bool(self.unix and hasattr(socket, "SO_PEERCRED")),
            "tokenRequired": bool(self.transport_token),
            "protocolSchemaVersion": PROTOCOL_SCHEMA_VERSION,
            "maximumRequestBytes": MAX_REQUEST_BYTES,
            "maximumResponseBytes": MAX_RESPONSE_BYTES,
        }

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def start(self) -> threading.Thread:
        if self._thread is not None:
            raise RuntimeError("this server is already serving")
        if self.gateway is None:
            # Fail closed. A server that began accepting with no gateway would
            # answer every request with an internal error, which reads to a
            # client exactly like a runtime that is up and broken rather than
            # one that never finished starting.
            raise RuntimeError(
                "this server has no gateway attached; call attach() before serving"
            )
        self._thread = threading.Thread(
            target=self.serve_forever, name="bunny-companion-protocol", daemon=True
        )
        self._thread.start()
        return self._thread

    def close(self) -> None:
        # Only shut down a loop that is running. ``socketserver.shutdown`` waits
        # for ``serve_forever`` to acknowledge, and when nothing is serving that
        # acknowledgement never comes — so this blocked for ever rather than
        # raising. The previous guard caught an exception that is never thrown
        # and left the real hazard in place: a runtime that fails between
        # binding and serving, and is then closed by a ``finally``, hung on the
        # way out instead of releasing its socket.
        if self._thread is not None:
            try:
                self._server.shutdown()
            except OSError:  # pragma: no cover - the loop is already gone
                pass
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        try:
            self.endpoint.unlink()
        except OSError:
            pass
        # After the socket is gone, never before: the claim is what stops a
        # second runtime binding, and releasing it while this one still held the
        # endpoint would let the next starter through to a bind that fails.
        if self.singleton is not None:
            self.singleton.release()

    def __enter__(self) -> "CompanionServer":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


class CompanionClientError(RuntimeError):
    """A refusal from the runtime, or a transport that would not carry one."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class CompanionClient:
    """One connection per call, and no state worth losing.

    Deliberately stateless. §7 requires the client to be disposable, and a
    client object holding a live connection would make "reconnect" mean
    "rebuild an object" rather than "call again". Every call opens, asks, reads
    one line and closes.
    """

    endpoint: Path | None = None
    timeout: float = SOCKET_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.endpoint = Path(self.endpoint or default_endpoint_path())

    def _address(self) -> tuple[Any, int, str]:
        if hasattr(socket, "AF_UNIX") and not self._is_endpoint_file():
            return str(self.endpoint), socket.AF_UNIX, ""
        try:
            document = json.loads(Path(self.endpoint).read_text(encoding="utf-8"))
            if document.get("transport") != "loopback-tcp" or document.get("host") != "127.0.0.1":
                raise ValueError("the endpoint is not a private loopback endpoint")
            return ("127.0.0.1", int(document["port"])), socket.AF_INET, str(document["token"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CompanionClientError(
                "runtime_unavailable", f"the companion endpoint is unavailable: {exc}"
            ) from exc

    def _is_endpoint_file(self) -> bool:
        path = Path(self.endpoint)
        try:
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    def call(self, operation: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if operation not in OPERATIONS:
            raise CompanionClientError("unknown_operation", f"unknown operation: {operation!r}")
        request_id = "request-" + uuid.uuid4().hex
        address, family, token = self._address()
        document: dict[str, Any] = {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id,
            "operation": operation,
            "params": {key: value for key, value in (params or {}).items() if value is not None},
        }
        if token:
            document["transportToken"] = token
        encoded = _encode(document)
        if len(encoded) > MAX_REQUEST_BYTES:
            raise CompanionClientError(
                "request_too_large",
                f"the request is {len(encoded)} bytes against a limit of {MAX_REQUEST_BYTES}",
            )
        connection = socket.socket(family, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        chunks: list[bytes] = []
        try:
            connection.connect(address)
            connection.sendall(encoded)
            size = 0
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise CompanionClientError(
                        "oversized_response", "the answer exceeded the response limit"
                    )
                if chunk.endswith(b"\n"):
                    break
        except OSError as exc:
            raise CompanionClientError("runtime_unavailable", f"the companion runtime is unreachable: {exc}") from exc
        finally:
            connection.close()
        try:
            response = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CompanionClientError("invalid_response", f"the answer was not JSON: {exc}") from exc
        if not isinstance(response, Mapping) or response.get("requestId") != request_id:
            raise CompanionClientError(
                "invalid_response", "the answer does not belong to this request"
            )
        if not response.get("ok"):
            error = response.get("error")
            error = error if isinstance(error, Mapping) else {}
            raise CompanionClientError(
                str(error.get("code", "runtime_error")),
                str(error.get("message", "the runtime refused and gave no reason")),
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise CompanionClientError("invalid_response", "the answer carried no result object")
        return result

    # -- the operations, spelled out ---------------------------------------

    def health(self) -> Mapping[str, Any]:
        return self.call("health")

    def create_session(self, title: str = "Companion session", **params: Any) -> Mapping[str, Any]:
        return self.call("create_session", {"title": title, **params})

    def list_sessions(self) -> Mapping[str, Any]:
        return self.call("list_sessions")

    def get_session(self, session_id: str) -> Mapping[str, Any]:
        return self.call("get_session", {"sessionId": session_id})

    def submit_task(self, session_id: str, request: str, *, run: bool = True) -> Mapping[str, Any]:
        return self.call("submit_task", {"sessionId": session_id, "request": request, "run": run})

    def list_tasks(self, session_id: str | None = None) -> Mapping[str, Any]:
        return self.call("list_tasks", {"sessionId": session_id})

    def get_task(self, task_id: str) -> Mapping[str, Any]:
        return self.call("get_task", {"taskId": task_id})

    def get_events(self, task_id: str, *, after_sequence: int = 0, limit: int = MAX_EVENT_PAGE) -> Mapping[str, Any]:
        return self.call("get_events", {
            "taskId": task_id, "afterSequence": after_sequence, "limit": limit,
        })

    def get_presentation_state(
        self, task_id: str | None = None, *, session_id: str | None = None, after_sequence: int = 0
    ) -> Mapping[str, Any]:
        return self.call("get_presentation_state", {
            "taskId": task_id, "sessionId": session_id, "afterSequence": after_sequence,
        })

    def resolve_approval(self, binding: Mapping[str, Any], decision: str) -> Mapping[str, Any]:
        """Answer one question, repeating the binding it was asked under."""
        return self.call("resolve_approval", {**dict(binding), "decision": decision})

    def cancel_task(self, task_id: str, *, cause: str = "user", detail: str = "") -> Mapping[str, Any]:
        return self.call("cancel_task", {"taskId": task_id, "cause": cause, "detail": detail})

    def pause_task(self, task_id: str) -> Mapping[str, Any]:
        return self.call("pause_task", {"taskId": task_id})

    def resume_task(self, task_id: str) -> Mapping[str, Any]:
        return self.call("resume_task", {"taskId": task_id})
