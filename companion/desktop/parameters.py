# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What each action accepts, and the one normalisation everything else uses.

Two rules shape this module, and both exist because of the same failure:
a person approves a sentence and a different act happens.

**``additionalProperties: false`` on every schema.** A parameter nobody declared
is refused, not ignored. An ignored parameter is one a caller believes took
effect, and the first time one of them means "…and skip the confirmation" the
silence becomes the vulnerability. :mod:`companion.protocol` makes the same
argument about its own operations and it applies with more force here, where the
consequence is on somebody's screen rather than in a reply.

**Normalisation happens once, before approval, and its output is what runs.**
:func:`normalise` produces a :class:`NormalisedAction` whose ``parameters`` are
canonical — the URI already parsed and rebuilt, the path already resolved
through symlinks, the notification body already escaped, the volume already an
integer. That object is what is digested into the approval binding, what is
rendered into the prompt the user reads, and what is handed to the adapter. There
is no second pass, so there is no window in which the three could differ.

The presentation strings are built here too, for the same reason. §18 forbids
"Allow task action" and requires the exact parameters; if a presentation layer
composed its own sentence from the parameters, that sentence and the binding
would be two readings of one fact, and the tests could only check one of them.

A note on what is *not* here: no schema has a field for a command, an
executable, an argument list, an environment variable, a D-Bus destination, a
raw path or a credential. That is the deliberate absence §3 asks for, and the
structural test in ``tests/companion/test_desktop_authority.py`` asserts it over
the schema table rather than over prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from ..privacy import DATA_CLASSES, rank, scrub_text
from .catalogue import descriptor_for
from .errors import DesktopRefused, DesktopSchemaError
from .paths import PathContext, ResolvedPath
from .uris import ALLOWED_SCHEMES, DESTINATION_CLASSES, ParsedUri, parse_uri

__all__ = [
    "MAX_CLIPBOARD_CHARACTERS",
    "MAX_NOTIFICATION_BODY",
    "NormalisedAction",
    "PARAMETER_SCHEMAS",
    "SETTINGS_PAGES",
    "URGENCIES",
    "escape_markup",
    "normalise",
    "validate_parameters",
]

#: §4.1's bound. Long enough for a sentence about a task, short enough that a
#: notification cannot be used to put a page of text on a lock screen.
MAX_NOTIFICATION_BODY = 500
MAX_NOTIFICATION_TITLE = 120

#: §4.7's bound. A clipboard is for text a person will paste; four kilobytes is
#: generous for that and far short of "exfiltrate a document".
MAX_CLIPBOARD_CHARACTERS = 4096

#: §4.4's allowlist. Identifiers, not component paths and not commands. The
#: mapping from one of these to whatever a given desktop calls it lives in the
#: settings adapter, so an environment that has no such page reports
#: ``unsupported`` instead of opening something approximate.
SETTINGS_PAGES = (
    "accessibility",
    "display",
    "keyboard",
    "network",
    "notifications",
    "power",
    "privacy",
    "sound",
)

URGENCIES = ("low", "normal", "critical")

#: Notification timeouts a caller may ask for, in milliseconds. Zero — "until
#: dismissed" — is deliberately outside the range: §4.1 forbids an indefinite
#: critical notification without justification, and the way that is enforced is
#: that indefiniteness has to be asked for by name.
MIN_NOTIFICATION_TIMEOUT_MS = 1_000
MAX_NOTIFICATION_TIMEOUT_MS = 60_000

#: How long a clipboard entry may be held before ownership is released.
MAX_CLIPBOARD_CLEAR_SECONDS = 3_600

_MAX_DEPTH = 4
_MAX_FIELDS = 24

#: A terminal escape, which is the injection §19 tests for: a string containing
#: ESC can move a cursor, rewrite a line already printed, or set a title, and a
#: refusal message printed to a terminal is exactly where that lands.
_ESCAPE = 0x1B


# --------------------------------------------------------------------------- #
# The schemas
# --------------------------------------------------------------------------- #

def _object(properties: Mapping[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": dict(properties),
    }


#: One schema per action. Written out rather than generated, because a generated
#: schema is one nobody reads, and this table is the security boundary a reviewer
#: is meant to be able to check by eye.
PARAMETER_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "desktop.notification.show": _object(
        {
            "title": {"type": "string", "minLength": 1, "maxLength": MAX_NOTIFICATION_TITLE},
            "body": {"type": "string", "maxLength": MAX_NOTIFICATION_BODY},
            "urgency": {"type": "string", "enum": list(URGENCIES)},
            # The canonical task this notification is about. An identifier the
            # runtime already holds; there is no field for a URL, an action
            # button or a callback, so a notification cannot be made clickable
            # into anything.
            "taskReference": {"type": "string", "identifier": True, "maxLength": 128},
            "timeoutMs": {
                "type": "integer",
                "minimum": MIN_NOTIFICATION_TIMEOUT_MS,
                "maximum": MAX_NOTIFICATION_TIMEOUT_MS,
            },
            # Required only when a critical notification asks to stay until it is
            # dismissed. Checked in normalisation, because "required under this
            # condition" is not something a flat schema can say.
            "persistJustification": {"type": "string", "maxLength": 200},
        },
        required=("title",),
    ),
    "desktop.application.launch": _object(
        {
            "applicationId": {"type": "string", "maxLength": 140},
            # Path *references*, never paths. See companion.desktop.paths.
            "fileReferences": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "string", "identifier": True, "maxLength": 128},
            },
            "uris": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "string", "maxLength": 2048},
            },
            "focusExisting": {"type": "boolean"},
        },
        required=("applicationId",),
    ),
    "desktop.application.present": _object(
        {
            "applicationId": {"type": "string", "maxLength": 140},
            #: Opaque to us: whatever the compositor calls a window. Bounded and
            #: never interpreted, so it cannot become a path or a command.
            "windowIdentity": {"type": "string", "maxLength": 128},
        },
        required=("applicationId",),
    ),
    "desktop.settings.open": _object(
        {"page": {"type": "string", "enum": list(SETTINGS_PAGES)}},
        required=("page",),
    ),
    "desktop.audio.set-volume": _object(
        {
            "percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "muted": {"type": "boolean"},
            #: The sink this was approved against. Bound into the approval so a
            #: device that changed between consent and execution is refused
            #: rather than substituted (§4.5).
            "outputId": {"type": "string", "maxLength": 128},
        },
        required=("percent",),
    ),
    "desktop.notifications.set-do-not-disturb": _object(
        {"enabled": {"type": "boolean"}},
        required=("enabled",),
    ),
    "desktop.clipboard.copy-text": _object(
        {
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_CLIPBOARD_CHARACTERS},
            "classification": {"type": "string", "enum": list(DATA_CLASSES)},
            "clearAfterSeconds": {
                "type": "integer", "minimum": 0, "maximum": MAX_CLIPBOARD_CLEAR_SECONDS,
            },
        },
        required=("text",),
    ),
    "desktop.uri.open": _object(
        {
            "uri": {"type": "string", "maxLength": 2048},
            "expectedScheme": {"type": "string", "enum": list(ALLOWED_SCHEMES)},
            "expectedDestinationClass": {"type": "string", "enum": list(DESTINATION_CLASSES)},
            #: For ``file:``. §4.8 requires an approved canonical local path, and
            #: the only way to have one is to reference a path the task holds.
            "pathReference": {"type": "string", "identifier": True, "maxLength": 128},
        },
        required=("expectedScheme", "expectedDestinationClass"),
    ),
    "desktop.file.reveal": _object(
        {"pathReference": {"type": "string", "identifier": True, "maxLength": 128}},
        required=("pathReference",),
    ),
}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _clean(value: str, path: str) -> None:
    """Refuse control characters, and refuse the escape byte by name.

    Named separately because they are different attacks with different targets:
    a stray C0 byte breaks a parser, and ESC rewrites a terminal that is
    displaying a refusal about it.
    """
    for character in value:
        code = ord(character)
        if code == _ESCAPE:
            raise DesktopSchemaError(
                f"{path}: contains a terminal escape byte, which can rewrite what a person "
                "is reading; the parameter was refused rather than stripped"
            )
        if code < 0x20 and character not in ("\n", "\t"):
            raise DesktopSchemaError(f"{path}: contains control character U+{code:04X}")
        if 0x7F <= code <= 0x9F:
            raise DesktopSchemaError(f"{path}: contains control character U+{code:04X}")


def _validate(value: Any, schema: Mapping[str, Any], path: str, depth: int) -> None:
    from ..ids import valid_id

    if depth > _MAX_DEPTH:
        raise DesktopSchemaError(f"{path}: nested deeper than {_MAX_DEPTH}")
    declared = schema.get("type")
    if declared == "object":
        if not isinstance(value, Mapping):
            raise DesktopSchemaError(f"{path or 'parameters'}: expected an object")
        if len(value) > _MAX_FIELDS:
            raise DesktopSchemaError(f"{path or 'parameters'}: more than {_MAX_FIELDS} fields")
        properties: Mapping[str, Any] = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                raise DesktopSchemaError(
                    f"{path or 'parameters'}: {name!r} is required and was not supplied"
                )
        for name, item in value.items():
            if not isinstance(name, str):
                raise DesktopSchemaError(f"{path or 'parameters'}: a field name is not a string")
            child = f"{path}.{name}" if path else name
            if name not in properties:
                # The rule this whole module exists for. Refused, never dropped.
                raise DesktopSchemaError(
                    f"{child}: is not a parameter of this action; the schema is closed, so an "
                    "unrecognised parameter is refused rather than ignored"
                )
            _validate(item, properties[name], child, depth + 1)
        return
    if declared == "array":
        if not isinstance(value, (list, tuple)):
            raise DesktopSchemaError(f"{path}: expected an array")
        limit = int(schema.get("maxItems", 8))
        if len(value) > limit:
            raise DesktopSchemaError(f"{path}: more than {limit} items")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate(item, item_schema, f"{path}[{index}]", depth + 1)
        return
    if declared == "string":
        if not isinstance(value, str):
            raise DesktopSchemaError(f"{path}: expected a string")
        minimum = int(schema.get("minLength", 0))
        maximum = int(schema.get("maxLength", 1024))
        if len(value) < minimum:
            raise DesktopSchemaError(f"{path}: is shorter than {minimum} characters")
        if len(value) > maximum:
            raise DesktopSchemaError(
                f"{path}: is {len(value)} characters against a limit of {maximum}; it was "
                "refused rather than truncated, because a truncated act is a different act"
            )
        _clean(value, path)
        allowed = schema.get("enum")
        if allowed is not None and value not in allowed:
            raise DesktopSchemaError(f"{path}: {value!r} is not one of {tuple(allowed)}")
        if schema.get("identifier") and not valid_id(value):
            raise DesktopSchemaError(f"{path}: {value!r} is not a usable identifier")
        return
    if declared == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise DesktopSchemaError(f"{path}: expected an integer")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise DesktopSchemaError(f"{path}: {value} is below the minimum of {minimum}")
        if maximum is not None and value > maximum:
            raise DesktopSchemaError(f"{path}: {value} is above the maximum of {maximum}")
        return
    if declared == "boolean":
        if not isinstance(value, bool):
            raise DesktopSchemaError(f"{path}: expected true or false")
        return
    raise DesktopSchemaError(f"{path}: the schema declares an unsupported type {declared!r}")


def validate_parameters(action_id: str, parameters: Mapping[str, Any]) -> None:
    """Check parameters against the closed schema for one action."""
    schema = PARAMETER_SCHEMAS.get(action_id)
    if schema is None:
        # Reached only for a declared action with no schema, which the
        # import-time check below makes impossible. Kept because "impossible"
        # is not a property, and this is the branch that would otherwise let a
        # new action through unvalidated.
        raise DesktopSchemaError(f"{action_id!r} has no parameter schema")
    _validate(parameters, schema, "", 0)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")


def escape_markup(value: str) -> str:
    """Make text safe to hand to a notification daemon that parses markup.

    Applied to every notification title and body, whether or not the daemon
    declares ``body-markup``, because which daemon is running is not something
    the request can know and a daemon that parses markup will parse it whatever
    we assumed. Escaping unconditionally means the user sees the characters the
    task produced rather than a fragment of markup the task did not intend.
    """
    return (
        _AMP.sub("&amp;", value)
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@dataclass(frozen=True)
class NormalisedAction:
    """One action, canonical, with everything the rest of the phase needs.

    Produced once. Digested into the approval binding, rendered into the prompt,
    handed to the adapter. If any two of those were built from different objects
    the approval would not describe the act, which is the failure §8 is a list
    of ways to avoid.
    """

    action_id: str
    #: The canonical parameters. This is what executes.
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: The exact thing acted upon, as one comparable string: an application id, a
    #: normalised URI, a resolved path, a settings page, an audio sink.
    target: str = ""
    #: What kind of thing the target is, so a change of *kind* is caught even if
    #: two targets somehow compared equal.
    target_kind: str = "none"
    #: The classification of the data this action discloses.
    classification: str = "public"
    #: What is being disclosed, in a form a person can weigh. Never the data.
    disclosure: str = "nothing"
    #: §18's sentence. "Open Firefox", not "Allow task action".
    presentation: str = ""
    #: What the user should expect to see.
    expected_effect: str = ""
    #: The state that existed before, when it was read and undo depends on it.
    previous_state: Mapping[str, Any] = field(default_factory=dict)
    #: Resolved supporting objects, for the adapter. Not serialised into the
    #: binding — the binding holds the *target*, which is derived from these.
    resolved_uri: ParsedUri | None = None
    resolved_path: ResolvedPath | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "actionId": self.action_id,
            "parameters": dict(self.parameters),
            "target": self.target,
            "targetKind": self.target_kind,
            "classification": self.classification,
            "disclosure": self.disclosure,
            "presentation": self.presentation,
            "expectedEffect": self.expected_effect,
            "previousState": dict(self.previous_state),
        }


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def normalise(
    action_id: str,
    parameters: Mapping[str, Any],
    *,
    classification: str = "internal",
    path_context: PathContext | None = None,
    application_name: str = "",
    observed_state: Mapping[str, Any] | None = None,
) -> NormalisedAction:
    """Validate, canonicalise and describe one action.

    ``observed_state`` is what the broker read from the machine before asking —
    the current volume, the current do-not-disturb setting. It is how the prompt
    can say "from 35% to 50%" rather than "to 50%", which §18 gives as the
    example of a label that tells a person what will actually change.
    """
    descriptor = descriptor_for(action_id)
    validate_parameters(action_id, parameters)
    # The class of what *this action* carries, which is not the task's class
    # for the four actions nothing of the task's flows into. See
    # :attr:`companion.desktop.catalogue.ActionDescriptor.carries_task_data`.
    effective = descriptor.effective_classification(classification)
    if not descriptor.accepts(effective):
        raise DesktopRefused(
            f"{action_id} may be given data classified up to {descriptor.privacy_ceiling} and "
            f"this task is {classification}"
        )
    observed = dict(observed_state or {})
    handler = _NORMALISERS[action_id]
    return handler(
        dict(parameters),
        classification=effective,
        path_context=path_context,
        application_name=application_name,
        observed=observed,
        descriptor=descriptor,
    )


def _notification(parameters: dict[str, Any], *, classification: str, observed, descriptor, **_: Any) -> NormalisedAction:
    title = escape_markup(scrub_text(parameters["title"]).strip())
    body = escape_markup(scrub_text(parameters.get("body", "")).strip())
    if not title:
        raise DesktopRefused("a notification with an empty title has nothing to show")
    urgency = parameters.get("urgency", "normal")
    timeout = parameters.get("timeoutMs")
    justification = (parameters.get("persistJustification") or "").strip()
    if urgency == "critical" and timeout is None and not justification:
        # §4.1, made structural. A critical notification with no timeout stays on
        # the screen until somebody dismisses it, which is a claim on a person's
        # attention that has to be argued for rather than defaulted into.
        raise DesktopRefused(
            "a critical notification with no timeout stays until it is dismissed; it must "
            "state why in persistJustification, or set a timeout"
        )
    canonical: dict[str, Any] = {"title": title, "urgency": urgency}
    if body:
        canonical["body"] = body
    if timeout is not None:
        canonical["timeoutMs"] = timeout
    if parameters.get("taskReference"):
        canonical["taskReference"] = parameters["taskReference"]
    if justification:
        canonical["persistJustification"] = justification
    return NormalisedAction(
        action_id="desktop.notification.show",
        parameters=canonical,
        target=title,
        target_kind="notification",
        classification=classification,
        disclosure=(
            f"{_plural(len(body), 'character')} of {classification} text on screen"
            if body else "a title only"
        ),
        presentation=f"Show a notification: “{title}”",
        expected_effect=descriptor.expected_visibility,
    )


def _launch(
    parameters: dict[str, Any], *, classification: str, path_context, application_name: str, descriptor, **_: Any
) -> NormalisedAction:
    from .entries import valid_application_id

    application_id = parameters["applicationId"]
    if not valid_application_id(application_id):
        raise DesktopRefused(
            f"{application_id!r} is not a usable application identifier; an identifier names an "
            "installed entry and never a path"
        )
    stem = application_id[: -len(".desktop")] if application_id.endswith(".desktop") else application_id

    resolved_files: list[ResolvedPath] = []
    for reference in parameters.get("fileReferences", ()):
        if path_context is None:
            raise DesktopRefused("this task holds no path context, so it can supply no files")
        resolved_files.append(path_context.resolve(reference))
    parsed_uris = [parse_uri(item) for item in parameters.get("uris", ())]
    for item in parsed_uris:
        if item.scheme == "file":
            raise DesktopRefused(
                "a file URI supplied to a launch must be given as a path reference, so that it "
                "is resolved against this task's approved roots rather than taken as written"
            )

    canonical: dict[str, Any] = {
        "applicationId": stem,
        "focusExisting": bool(parameters.get("focusExisting", True)),
    }
    if resolved_files:
        canonical["fileReferences"] = [item.reference_id for item in resolved_files]
    if parsed_uris:
        canonical["uris"] = [item.normalised for item in parsed_uris]

    name = application_name or stem
    opened = len(resolved_files) + len(parsed_uris)
    return NormalisedAction(
        action_id="desktop.application.launch",
        parameters=canonical,
        target=stem,
        target_kind="application",
        classification=classification,
        disclosure=(
            f"{_plural(opened, 'item')} handed to {name}" if opened else "nothing"
        ),
        presentation=(
            f"Open {name}" + (f" with {_plural(opened, 'item')}" if opened else "")
        ),
        expected_effect=descriptor.expected_visibility,
        previous_state={
            "fileDigests": [item.digest for item in resolved_files],
        } if resolved_files else {},
    )


def _present(
    parameters: dict[str, Any], *, classification: str, application_name: str, descriptor, **_: Any
) -> NormalisedAction:
    from .entries import valid_application_id

    application_id = parameters["applicationId"]
    if not valid_application_id(application_id):
        raise DesktopRefused(f"{application_id!r} is not a usable application identifier")
    stem = application_id[: -len(".desktop")] if application_id.endswith(".desktop") else application_id
    canonical: dict[str, Any] = {"applicationId": stem}
    if parameters.get("windowIdentity"):
        canonical["windowIdentity"] = parameters["windowIdentity"]
    name = application_name or stem
    return NormalisedAction(
        action_id="desktop.application.present",
        parameters=canonical,
        target=stem,
        target_kind="application",
        classification=classification,
        disclosure="nothing",
        presentation=f"Bring {name} to the front",
        expected_effect=descriptor.expected_visibility,
    )


def _settings(parameters: dict[str, Any], *, classification: str, descriptor, **_: Any) -> NormalisedAction:
    page = parameters["page"]
    return NormalisedAction(
        action_id="desktop.settings.open",
        parameters={"page": page},
        target=page,
        target_kind="settings-page",
        classification=classification,
        disclosure="nothing",
        presentation=f"Open the {page} settings page",
        expected_effect=descriptor.expected_visibility,
    )


def _volume(parameters: dict[str, Any], *, classification: str, observed, descriptor, **_: Any) -> NormalisedAction:
    percent = parameters["percent"]
    output_id = (parameters.get("outputId") or "").strip() or str(observed.get("outputId", "")) or "default"
    canonical: dict[str, Any] = {"percent": percent, "outputId": output_id}
    if "muted" in parameters:
        canonical["muted"] = bool(parameters["muted"])

    previous: dict[str, Any] = {}
    before = observed.get("percent")
    if isinstance(before, int):
        previous["percent"] = before
    if isinstance(observed.get("muted"), bool):
        previous["muted"] = observed["muted"]
    if output_id:
        previous["outputId"] = output_id

    sink = observed.get("outputName") or output_id
    if "percent" in previous:
        sentence = f"Set {sink} volume from {previous['percent']}% to {percent}%"
    else:
        sentence = f"Set {sink} volume to {percent}%"
    if canonical.get("muted") is True:
        sentence += " and mute it"
    elif canonical.get("muted") is False:
        sentence += " and unmute it"
    return NormalisedAction(
        action_id="desktop.audio.set-volume",
        parameters=canonical,
        target=output_id,
        target_kind="audio-output",
        classification=classification,
        disclosure="nothing",
        presentation=sentence,
        expected_effect=descriptor.expected_visibility,
        previous_state=previous,
    )


def _do_not_disturb(parameters: dict[str, Any], *, classification: str, observed, descriptor, **_: Any) -> NormalisedAction:
    enabled = bool(parameters["enabled"])
    previous: dict[str, Any] = {}
    if isinstance(observed.get("enabled"), bool):
        previous["enabled"] = observed["enabled"]
    return NormalisedAction(
        action_id="desktop.notifications.set-do-not-disturb",
        parameters={"enabled": enabled},
        target="do-not-disturb",
        target_kind="setting",
        classification=classification,
        disclosure="nothing",
        presentation=("Turn do-not-disturb on" if enabled else "Turn do-not-disturb off"),
        expected_effect=descriptor.expected_visibility,
        previous_state=previous,
    )


def _clipboard(parameters: dict[str, Any], *, classification: str, descriptor, **_: Any) -> NormalisedAction:
    raw = parameters["text"]
    # Not scrubbed-and-copied: refused. `scrub_text` replaces a credential with a
    # marker, and silently copying "[redacted]" where a user expected their text
    # would be a failure they discover by pasting it somewhere that matters.
    if scrub_text(raw) != raw:
        raise DesktopRefused(
            "the text contains something credential-shaped; it was refused rather than copied, "
            "and rather than copied with the credential removed, because a partial paste is a "
            "failure a person only finds out about afterwards"
        )
    declared = parameters.get("classification", classification)
    if rank(declared) < rank(classification):
        # A provider may not lower the class of what it is copying. Raising it is
        # allowed: a task classified `internal` may still say a particular string
        # is personal, and the stricter of the two applies.
        declared = classification
    if rank(declared) > rank(descriptor.privacy_ceiling):
        raise DesktopRefused(
            f"clipboard text classified {declared} exceeds this action's "
            f"{descriptor.privacy_ceiling} ceiling"
        )
    canonical = {"text": raw, "classification": declared}
    clear_after = parameters.get("clearAfterSeconds")
    if clear_after is not None:
        canonical["clearAfterSeconds"] = clear_after
    # Said in the sentence, because it is part of what the person is agreeing
    # to. A clear-after policy that appeared only in the parameter list would be
    # a promise made in small print.
    clearing = (
        f", released again after {clear_after} seconds" if clear_after else ""
    )
    return NormalisedAction(
        action_id="desktop.clipboard.copy-text",
        parameters=canonical,
        # The *digest* is the target, never the text. §8 requires a changed
        # clipboard digest to invalidate an approval, and §13 forbids the text
        # reaching a record; a digest does both jobs at once.
        target=_text_digest(raw),
        target_kind="clipboard-text",
        classification=declared,
        disclosure=f"{_plural(len(raw), 'character')} of {declared} text",
        presentation=(
            f"Copy {_plural(len(raw), 'character')} of {declared} text to the clipboard"
            + clearing
        ),
        expected_effect=descriptor.expected_visibility,
    )


def _text_digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _uri(parameters: dict[str, Any], *, classification: str, path_context, descriptor, **_: Any) -> NormalisedAction:
    expected_scheme = parameters["expectedScheme"]
    expected_class = parameters["expectedDestinationClass"]
    supplied = parameters.get("uri")
    reference = parameters.get("pathReference")

    resolved_path: ResolvedPath | None = None
    if expected_scheme == "file":
        if supplied is not None:
            raise DesktopRefused(
                "a file URI is not accepted as a string; §4.8 requires an approved canonical "
                "local path, so name a path reference this task already holds"
            )
        if not reference:
            raise DesktopRefused("opening a file URI requires a path reference")
        if path_context is None:
            raise DesktopRefused("this task holds no path context, so no file may be opened")
        resolved_path = path_context.resolve(reference)
        parsed = parse_uri(
            "file://" + resolved_path.real_path.replace("\\", "/"), expected_scheme="file"
        )
    else:
        if reference:
            raise DesktopRefused("a path reference only applies to a file URI")
        if not supplied:
            raise DesktopRefused("no URI was supplied")
        parsed = parse_uri(supplied, expected_scheme=expected_scheme)

    if parsed.destination_class != expected_class:
        raise DesktopRefused(
            f"the URI leads to a {parsed.destination_class} destination and was presented as "
            f"{expected_class}; the string shown and the string opened must agree"
        )

    canonical: dict[str, Any] = {
        "uri": parsed.normalised,
        "expectedScheme": parsed.scheme,
        "expectedDestinationClass": parsed.destination_class,
    }
    if reference:
        canonical["pathReference"] = reference

    if parsed.scheme == "mailto":
        sentence = f"Open a message composer to {parsed.normalised[len('mailto:'):].split('?')[0]}"
        effect = "A message composer opens. Nothing is sent."
    elif resolved_path is not None:
        sentence = f"Open {resolved_path.display}"
        effect = descriptor.expected_visibility
    else:
        sentence = f"Open {parsed.display}"
        effect = descriptor.expected_visibility
    return NormalisedAction(
        action_id="desktop.uri.open",
        parameters=canonical,
        target=parsed.normalised,
        target_kind=parsed.destination_class,
        classification=classification,
        disclosure=(
            "the address, to whichever application handles it"
            + (" (it carries a query string)" if parsed.has_query else "")
        ),
        presentation=sentence,
        expected_effect=effect,
        resolved_uri=parsed,
        resolved_path=resolved_path,
    )


def _reveal(parameters: dict[str, Any], *, classification: str, path_context, descriptor, **_: Any) -> NormalisedAction:
    if path_context is None:
        raise DesktopRefused("this task holds no path context, so nothing can be revealed")
    resolved = path_context.resolve(parameters["pathReference"])
    return NormalisedAction(
        action_id="desktop.file.reveal",
        parameters={"pathReference": resolved.reference_id},
        # The real path, so that a reference re-pointed at a different file
        # after approval produces a different target and is refused (§8).
        target=resolved.real_path,
        target_kind="local-file",
        classification=classification,
        disclosure=f"the location of {resolved.display}",
        presentation=(
            f"Reveal {resolved.display}"
            + (" (a link, resolved)" if resolved.was_symlink else "")
        ),
        expected_effect=descriptor.expected_visibility,
        resolved_path=resolved,
    )


_NORMALISERS = {
    "desktop.notification.show": _notification,
    "desktop.application.launch": _launch,
    "desktop.application.present": _present,
    "desktop.settings.open": _settings,
    "desktop.audio.set-volume": _volume,
    "desktop.notifications.set-do-not-disturb": _do_not_disturb,
    "desktop.clipboard.copy-text": _clipboard,
    "desktop.uri.open": _uri,
    "desktop.file.reveal": _reveal,
}


def _check_tables() -> None:
    from .catalogue import ACTION_IDS

    missing_schema = [item for item in ACTION_IDS if item not in PARAMETER_SCHEMAS]
    if missing_schema:
        raise DesktopSchemaError(f"{missing_schema} are declared and have no parameter schema")
    missing_normaliser = [item for item in ACTION_IDS if item not in _NORMALISERS]
    if missing_normaliser:
        raise DesktopSchemaError(f"{missing_normaliser} are declared and have no normaliser")
    stray = sorted(set(PARAMETER_SCHEMAS) - set(ACTION_IDS))
    if stray:
        raise DesktopSchemaError(f"{stray} have a schema and are not declared actions")
    for _action_id, _schema in PARAMETER_SCHEMAS.items():
        if _schema.get("additionalProperties") is not False:
            raise DesktopSchemaError(
                f"{_action_id}'s schema does not close additionalProperties; an undeclared "
                "parameter would be silently ignored"
            )


_check_tables()
