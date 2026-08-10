# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What may be written down, and who may read it.

Two separate questions live here and conflating them is the usual way a privacy
model fails.

**What may be stored at all.** Some things are never written to a companion
event, at any classification, for any audience: credentials, authorisation
headers, a model's hidden reasoning, raw microphone audio, whole sensitive
screens. There is no flag that turns these on. They are removed by
:func:`sanitize` before an event is constructed, and the *fact* of removal is
kept — a field that vanished without trace is a record that reads as complete
and is not.

The check is on the *name*, normalised by :func:`normalise_key` so that
``sessionCookie``, ``session_cookie``, ``SESSION_COOKIE`` and ``session.cookie``
are one thing. That normalisation is not decoration: without it the word-boundary
anchors matched camelCase and missed snake_case entirely, because ``_`` is a
word character in Python — a total bypass for the most common convention in this
codebase. What the name check cannot catch is a credential in a field with an
innocuous name and an unrecognised shape; :data:`_CREDENTIAL_VALUE` covers the
well-known shapes and nothing claims to cover the rest.

**Who may read what was stored.** A task carries a data classification, and each
audience has a ceiling. A reviewer reading a task classified ``personal`` gets
the class marker and the structure, not the content; the on-device executor
performing the work gets the content; a remote provider gets nothing above
``internal`` and only when policy permits it at all.

The classes are the router's classes plus ``personal``:

    public < internal < personal < sensitive < secret

:mod:`capability.router` has no ``personal`` because a service placement does
not need one. A companion task does: "my calendar" is not ``internal`` and
calling it ``sensitive`` would make the sensitive tier meaningless. When a
companion classification is handed to the router it is mapped conservatively —
``personal`` becomes ``sensitive`` — so the addition can only ever tighten a
routing decision, never loosen one.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

__all__ = [
    "AUDIENCES",
    "AUDIENCE_CEILING",
    "DATA_CLASSES",
    "MAX_PAYLOAD_BYTES",
    "MAX_REQUEST_LENGTH",
    "MAX_STRING_LENGTH",
    "MAX_SUMMARY_LENGTH",
    "REDACTION_MARKER",
    "Sanitized",
    "at_most",
    "display_summary",
    "project",
    "normalise_key",
    "rank",
    "router_privacy",
    "sanitize",
    "scrub_text",
    "visible_to",
    "withheld_marker",
]

#: Increasing sensitivity. Order is the whole of the meaning; the names are
#: compared by rank and never by string.
DATA_CLASSES = ("public", "internal", "personal", "sensitive", "secret")

_RANK = {name: index for index, name in enumerate(DATA_CLASSES)}

#: Who a stored field can be shown to. ``executor`` is the *on-device* executor
#: performing the work; a remote provider is the ``remote`` audience even when
#: it is acting as the executor, because the question "may this leave the
#: machine" does not become a different question by being asked of an executor.
AUDIENCES = ("executor", "reviewer", "ui", "audit", "remote")

#: The highest classification each audience may see verbatim. Anything above the
#: ceiling is replaced by a marker naming the class that was withheld, so the
#: audience can tell "there was nothing here" from "there was something here you
#: may not see" — a distinction reviewers in particular need in order to say
#: honestly that they reviewed a task they could only partly read.
AUDIENCE_CEILING: Mapping[str, str] = {
    # The thing actually doing the work, on this machine.
    "executor": "secret",
    # Observation-only, and observation does not require the contents. A
    # reviewer that needed the user's personal data to notice a missing
    # validation step would be a reviewer designed wrong.
    "reviewer": "internal",
    # The user's own surface. Secret stays out of the ordinary event view and is
    # reached only through a deliberate act, never rendered incidentally.
    "ui": "sensitive",
    # Audit exists to prove what happened, not to archive what it was about.
    "audit": "internal",
    # Off-device. Never above internal from this module; policy decides
    # separately whether anything may go at all.
    "remote": "internal",
}

#: What replaces a value that is removed rather than withheld.
REDACTION_MARKER = "[redacted]"

#: Ceilings for one event payload. Exceeded means refused, not truncated: a
#: quietly shortened payload is indistinguishable from a complete one.
MAX_PAYLOAD_BYTES = 16 * 1024
MAX_STRING_LENGTH = 4 * 1024
MAX_COLLECTION_ITEMS = 128
MAX_DEPTH = 8

#: Display summaries *are* truncated, because they are a summary and say so.
MAX_SUMMARY_LENGTH = 240

#: The longest request the runtime accepts. Bounded where it is accepted rather
#: than truncated where it is stored: a user whose request was too long is told
#: so, instead of discovering later that the companion answered half of it.
MAX_REQUEST_LENGTH = 8192

#: Field names whose values are never stored, at any classification. Matched
#: against :func:`normalise_key` of the field name, case-insensitively, so that
#: every naming convention reduces to the same words before comparison. Adding
#: an alternative here needs only one spelling; the normalisation covers the
#: rest.
#
# Every compound is written with an optional ``[-_ ]`` between its parts, so
# ``framebuffer``, ``frame_buffer``, ``frame-buffer`` and ``frameBuffer`` are one
# alternative rather than four. Single words keep ``\b`` so that ``secret`` does
# not match ``secretary``; that is safe now that :func:`normalise_key` has turned
# every separator into a space, which ``\b`` does see.
#
# **A word that is itself a compound must be written as one.** ``normalise_key``
# *inserts* separators, so an alternative spelled as a single word can be split
# apart by a field name that spells it in two: ``\bpasswords?\b`` matched
# ``password`` and missed ``passWord`` and ``pass_word``, which are spellings
# people actually write. This is the mirror image of the original ``\b`` bug and
# it is easy to reintroduce — when adding an alternative, ask whether an English
# speaker might put a separator anywhere inside it.
_FORBIDDEN_FIELD = re.compile(
    r"(?i)("
    # credentials and keys
    r"api[-_ ]?key|secret[-_ ]?key|private[-_ ]?key|public[-_ ]?private"
    r"|access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token|bearer[-_ ]?token"
    r"|auth[-_ ]?token|session[-_ ]?token|csrf[-_ ]?token|api[-_ ]?token"
    r"|\btokens?\b|authoriz|authoris|\bcredentials?\b"
    r"|\bpass[-_ ]?words?\b|\bpass[-_ ]?phrase\b|\bsecrets?\b|\bcookies?\b"
    r"|api[-_ ]?secret"
    # a model's private reasoning
    r"|chain[-_ ]?of[-_ ]?thought|hidden[-_ ]?reasoning|reasoning[-_ ]?trace"
    r"|\bscratch[-_ ]?pad\b|internal[-_ ]?monologue|\bdeliberation"
    # captured media
    r"|raw[-_ ]?audio|microphone[-_ ]?recording|\bwave[-_ ]?form\b|audio[-_ ]?samples"
    r"|screen[-_ ]?content|screen[-_ ]?capture|\bframe[-_ ]?buffer\b"
    r"|\bscreen[-_ ]?shots?\b"
    r")"
)

#: Names that collide with :data:`_FORBIDDEN_FIELD` but are measurements rather
#: than material. Permitted **only when the value is a number** — a context
#: length is a number, and a "tokenCount" holding a string is not a count.
_NUMERIC_EXEMPT = frozenset({
    "tokencount", "tokensused", "prompttokens", "completiontokens",
    "contexttokens", "maxtokens", "tokenlimit", "tokenbudget",
})

#: Value shapes that are credentials whatever the field is called. Deliberately
#: a short list of well-known prefixes rather than an entropy heuristic: a
#: heuristic that redacts by looking random would eat digests, ids and
#: fingerprints, which are exactly the fields this record exists to carry.
_CREDENTIAL_VALUE = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bbearer\s+[A-Za-z0-9._\-]{8,}"
    r"|\b(?:sk|rk|pk)-[A-Za-z0-9]{16,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{16,}"
    r"|\bxox[abposr]-[A-Za-z0-9-]{8,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")"
)


def rank(classification: str) -> int:
    """Position of a class in :data:`DATA_CLASSES`. Raises on an unknown name."""
    try:
        return _RANK[classification]
    except KeyError:
        raise ValueError(f"unknown data classification: {classification!r}") from None


def at_most(left: str, right: str) -> str:
    """The lower of two classifications."""
    return left if rank(left) <= rank(right) else right


def highest(values: Sequence[str]) -> str:
    """The most sensitive of a set of classifications; ``public`` when empty."""
    result = "public"
    for value in values:
        if rank(value) > rank(result):
            result = value
    return result


def visible_to(audience: str, classification: str) -> bool:
    """Whether an audience may see content of this class verbatim."""
    if audience not in AUDIENCE_CEILING:
        raise ValueError(f"unknown audience: {audience!r}")
    return rank(classification) <= rank(AUDIENCE_CEILING[audience])


def withheld_marker(classification: str) -> str:
    """What an audience above its ceiling sees instead of the content."""
    return f"[withheld: {classification}]"


def router_privacy(classification: str) -> str:
    """Map a companion class onto :data:`capability.router.PRIVACY_CLASSES`.

    ``personal`` has no router equivalent and is raised to ``sensitive`` rather
    than lowered to ``internal``. The mapping is allowed to make routing
    stricter and never looser, so a class the router has not heard of cannot
    become a path off the device.
    """
    if classification == "personal":
        return "sensitive"
    if classification not in DATA_CLASSES:
        raise ValueError(f"unknown data classification: {classification!r}")
    return classification


@dataclass(frozen=True)
class Sanitized:
    """A payload that is safe to store, and the record of what was taken out."""

    value: Any
    #: Dotted paths whose values were removed because they may never be stored.
    removed: tuple[str, ...] = ()
    #: Dotted paths whose values were rewritten because they looked like a
    #: credential regardless of the field name.
    scrubbed: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.removed and not self.scrubbed

    def to_json(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "removedFields": list(self.removed),
            "scrubbedFields": list(self.scrubbed),
        }


def normalise_key(key: str) -> str:
    """Reduce any naming convention to space-separated words.

    ``sessionCookie``, ``session_cookie``, ``session-cookie``, ``SESSION_COOKIE``
    and ``session.cookie`` all become ``session Cookie`` or ``session cookie``.

    This exists because of a real and total bypass. Half of
    :data:`_FORBIDDEN_FIELD`'s alternatives are anchored with ``\\b``, and in
    Python ``_`` is a *word* character — so ``\\bcookie`` never matches after an
    underscore, and every snake_case credential name went straight through into
    the store. Splitting only on case transitions, as an earlier version did,
    fixed camelCase and left snake_case wide open.

    Normalising every separator to a space before matching is what makes the
    check independent of naming convention. The tests assert the same concept in
    five conventions, so an alternative added in only one shape fails.
    """
    return re.sub(r"[^A-Za-z0-9]+", " ", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)).strip()


def _forbidden(key: str, value: Any) -> bool:
    if _FORBIDDEN_FIELD.search(normalise_key(key)) is None:
        return False
    normalised = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalised in _NUMERIC_EXEMPT and isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    return True


def scrub_text(value: str) -> str:
    """Remove credential-shaped material from free text, keeping the rest.

    Unlike :func:`display_summary` this does not shorten or collapse: it is for
    the fields where the user's own words are kept in full — the original
    request above all. A request is not a payload, so it is not truncated here;
    its length is bounded where it is accepted, so that a refusal is a refusal
    rather than a silent shortening.
    """
    return _CREDENTIAL_VALUE.sub(REDACTION_MARKER, str(value))


def _walk(value: Any, path: str, depth: int, removed: list[str], scrubbed: list[str]) -> Any:
    from .errors import PayloadTooLarge, SchemaError

    if depth > MAX_DEPTH:
        raise PayloadTooLarge(f"{path or 'payload'} is nested deeper than {MAX_DEPTH} levels")

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # NaN and infinities have no JSON representation and would be written as
        # bare tokens that a strict reader rejects. Refused at the boundary
        # rather than discovered when the store is read back after a crash.
        if value != value or value in (float("inf"), float("-inf")):
            raise SchemaError(f"{path or 'payload'} holds a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise PayloadTooLarge(
                f"{path or 'payload'} is {len(value)} characters against a limit of {MAX_STRING_LENGTH}"
            )
        replaced = _CREDENTIAL_VALUE.sub(REDACTION_MARKER, value)
        if replaced != value:
            scrubbed.append(path or "payload")
        return replaced
    if isinstance(value, Mapping):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PayloadTooLarge(f"{path or 'payload'} has {len(value)} fields against a limit of {MAX_COLLECTION_ITEMS}")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaError(f"{path or 'payload'} has a non-string field name")
            child = f"{path}.{key}" if path else key
            if _forbidden(key, item):
                removed.append(child)
                continue
            result[key] = _walk(item, child, depth + 1, removed, scrubbed)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PayloadTooLarge(f"{path or 'payload'} has {len(value)} items against a limit of {MAX_COLLECTION_ITEMS}")
        return [_walk(item, f"{path}[{index}]", depth + 1, removed, scrubbed) for index, item in enumerate(value)]
    raise SchemaError(f"{path or 'payload'} holds an unsupported type: {type(value).__name__}")


def sanitize(payload: Any) -> Sanitized:
    """Remove what may never be stored; refuse what is too large.

    Removal and refusal are different on purpose. A credential is removed
    because storing it is the harm; an oversized payload is refused because
    storing part of it produces a record that lies about its own completeness.
    """
    from .errors import PayloadTooLarge

    removed: list[str] = []
    scrubbed: list[str] = []
    value = _walk(payload, "", 0, removed, scrubbed)

    import json

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    size = len(encoded.encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise PayloadTooLarge(f"payload is {size} bytes against a limit of {MAX_PAYLOAD_BYTES}")
    return Sanitized(value=value, removed=tuple(removed), scrubbed=tuple(scrubbed))


def project(payload: Any, *, audience: str, classification: str) -> Any:
    """Render a stored payload for one audience.

    Above the audience's ceiling the *structure* survives and the *content* does
    not: keys remain, values become :func:`withheld_marker`. A reviewer can
    therefore still see that a task had a ``recipients`` field and say something
    useful about it without being told who the recipients were.
    """
    if visible_to(audience, classification):
        return payload
    marker = withheld_marker(classification)

    def _mask(value: Any, depth: int) -> Any:
        if depth > MAX_DEPTH:
            return marker
        if isinstance(value, Mapping):
            return {key: _mask(item, depth + 1) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_mask(item, depth + 1) for item in value]
        if value is None or isinstance(value, bool):
            return value
        return marker

    return _mask(payload, 0)


def display_summary(text: str, *, limit: int = MAX_SUMMARY_LENGTH) -> str:
    """A short, credential-free rendering of free text, marked when shortened.

    Unlike :func:`sanitize` this truncates, because the field it produces is
    declared to be a summary. The ellipsis is part of the contract: a UI must be
    able to tell the user that there is more than it is showing.
    """
    collapsed = " ".join(str(text).split())
    scrubbed = _CREDENTIAL_VALUE.sub(REDACTION_MARKER, collapsed)
    if len(scrubbed) <= limit:
        return scrubbed
    return scrubbed[: max(0, limit - 1)].rstrip() + "…"
