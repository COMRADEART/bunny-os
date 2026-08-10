# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The only place a companion task can actually cause something to happen.

Executors propose operations; this performs them. Everything a task does to the
world goes through :meth:`ToolBroker.invoke`, which is therefore the one place
that has to get three things right:

* **the allowlist** — a tool that is not declared cannot be called, so a
  plan naming ``shell.run`` fails at the broker rather than somewhere deeper;
* **the caller** — every invocation names its caller in the
  :mod:`companion.events` producer vocabulary, and a caller of kind ``reviewer``
  is refused with :class:`~companion.errors.ReviewerViolation`. Reviewers are
  given no broker reference at all, so this check should be unreachable; it is
  here because "should be unreachable" is not a security property, and if it
  ever fires the runtime has learned something important about a reviewer;
* **the declaration** — whether a tool is destructive, whether it reaches an
  external destination, and the most sensitive data it may be given. Those three
  facts drive the approval requirements in §12, and inferring them from a tool's
  name would mean a new tool silently inherits whatever the parser guessed.

The tools shipped here are pure functions over the task's own text. They read no
file, open no socket and start no process. That is not a placeholder for a real
tool set: this phase is the runtime, and a runtime whose test tools could touch
the machine would make every test a system test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Callable, Mapping

from .errors import MalformedOutput, ReviewerViolation
from .privacy import DATA_CLASSES, rank

__all__ = [
    "LOCAL_TEST_TOOLS",
    "ToolBroker",
    "ToolDeclaration",
    "ToolOutcome",
]


@dataclass(frozen=True)
class ToolDeclaration:
    """What a tool is and what calling it means.

    Undeclared fails closed, in the same sense as
    :class:`capability.router.ProviderDeclaration`: the defaults describe the
    *safe* tool, and a tool that is in fact destructive has to say so. The
    consequence of forgetting is that an approval is not requested, so the
    defaults are the ones where forgetting is survivable — the runtime asks for
    consent based on what is declared, and a tool that under-declares is a
    review failure rather than a silent escalation, because the broker refuses
    anything whose declaration does not cover the data it is handed.
    """

    tool_id: str
    summary: str
    destructive: bool = False
    #: Whether calling this reaches something outside the machine.
    external_destination: bool = False
    #: Whether it interrupts what the user is doing.
    interrupts_user: bool = False
    #: The most sensitive data this tool may be given.
    maximum_classification: str = "secret"

    def __post_init__(self) -> None:
        if self.maximum_classification not in DATA_CLASSES:
            raise MalformedOutput(f"unknown tool classification ceiling: {self.maximum_classification!r}")
        if self.external_destination and rank(self.maximum_classification) > rank("internal"):
            raise MalformedOutput(
                f"tool {self.tool_id!r} reaches outside the device and cannot declare a ceiling "
                "above 'internal'"
            )

    @property
    def sensitive(self) -> bool:
        """Whether an invocation needs a person to have said yes."""
        return self.destructive or self.external_destination or self.interrupts_user

    def to_json(self) -> dict[str, Any]:
        return {
            "toolId": self.tool_id,
            "summary": self.summary,
            "destructive": self.destructive,
            "externalDestination": self.external_destination,
            "interruptsUser": self.interrupts_user,
            "maximumClassification": self.maximum_classification,
            "sensitive": self.sensitive,
        }


@dataclass(frozen=True)
class ToolOutcome:
    """What one invocation produced."""

    tool_id: str
    ok: bool
    value: Any = None
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"toolId": self.tool_id, "ok": self.ok, "value": self.value, "detail": self.detail}


def _count_words(arguments: Mapping[str, Any]) -> ToolOutcome:
    text = str(arguments.get("text", ""))
    return ToolOutcome("text.count_words", True, value=len(re.findall(r"\S+", text)))


def _validate_count(arguments: Mapping[str, Any]) -> ToolOutcome:
    text = str(arguments.get("text", ""))
    words = re.findall(r"\S+", text)
    # A second, independently written count. If two different methods of
    # counting the same text disagree, the validation has done its job.
    independent = sum(1 for token in text.split() if token)
    return ToolOutcome(
        "text.validate_count",
        True,
        value="consistent" if len(words) == independent else "inconsistent",
        detail=f"pattern={len(words)} split={independent}",
    )


def _checksum(arguments: Mapping[str, Any]) -> ToolOutcome:
    text = str(arguments.get("text", ""))
    return ToolOutcome(
        "text.checksum", True, value=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    )


def _publish_notice(arguments: Mapping[str, Any]) -> ToolOutcome:
    """Deliver a notice to the user's session.

    In this phase there is no session to deliver to, so the notice is returned
    rather than shown. The *declaration* is what matters and is not provisional:
    publishing a notice interrupts what somebody is doing, so the tool declares
    ``interrupts_user`` and the runtime requires consent before calling it. When
    the UX shell wires a real notifier in behind this, the declaration — and
    therefore the approval — does not change. Declaring it honestly now is what
    stops the approval being *added* later, which is the point at which it gets
    argued about and skipped.
    """
    text = str(arguments.get("text", ""))
    return ToolOutcome("notice.publish", True, value=text, detail="headless: the notice was not displayed")


#: The tools this phase ships. Pure, local, free and free of side effects.
LOCAL_TEST_TOOLS: Mapping[str, tuple[ToolDeclaration, Callable[[Mapping[str, Any]], ToolOutcome]]] = {
    "notice.publish": (
        ToolDeclaration(
            "notice.publish",
            "Publish a notice to the user's session, interrupting what they are doing",
            interrupts_user=True,
        ),
        _publish_notice,
    ),
    "text.count_words": (
        ToolDeclaration("text.count_words", "Count the words in a piece of text"),
        _count_words,
    ),
    "text.validate_count": (
        ToolDeclaration("text.validate_count", "Count the same text a second way and compare"),
        _validate_count,
    ),
    "text.checksum": (
        ToolDeclaration("text.checksum", "Digest a piece of text"),
        _checksum,
    ),
}


@dataclass
class ToolBroker:
    """The allowlist, and the only door through it."""

    tools: Mapping[str, tuple[ToolDeclaration, Callable[[Mapping[str, Any]], ToolOutcome]]] = field(
        default_factory=lambda: dict(LOCAL_TEST_TOOLS)
    )
    #: Every invocation, in order, for the tests and for the audit view.
    invocations: list[dict[str, Any]] = field(default_factory=list)
    #: Attempts refused because the caller was not permitted to make them.
    refusals: list[dict[str, Any]] = field(default_factory=list)

    def declaration(self, tool_id: str) -> ToolDeclaration | None:
        entry = self.tools.get(tool_id)
        return entry[0] if entry is not None else None

    def declarations(self) -> tuple[ToolDeclaration, ...]:
        return tuple(declaration for declaration, _ in (self.tools[key] for key in sorted(self.tools)))

    def invoke(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        *,
        caller: str,
        classification: str = "internal",
    ) -> ToolOutcome:
        """Perform one operation, or refuse and say why.

        ``caller`` is a producer string from :data:`companion.events.PRODUCER_KINDS`.
        A reviewer reaching this method is a security event: it is recorded
        against the reviewer's identity and raised, never merely returned as a
        failed outcome, because a failure looks like a tool that did not work
        and this is a component that tried to exceed its role.
        """
        kind = caller.split(":", 1)[0]
        if kind == "reviewer":
            self.refusals.append({"toolId": tool_id, "caller": caller, "reason": "reviewers may not execute tools"})
            raise ReviewerViolation(
                f"{caller} attempted to execute {tool_id!r}; reviewers are observation-only and this "
                "attempt was refused and recorded"
            )
        if kind not in ("runtime", "executor", "recovery"):
            self.refusals.append({"toolId": tool_id, "caller": caller, "reason": "caller may not execute tools"})
            raise ReviewerViolation(f"{caller} may not execute tools")

        entry = self.tools.get(tool_id)
        if entry is None:
            self.refusals.append({"toolId": tool_id, "caller": caller, "reason": "not on the allowlist"})
            return ToolOutcome(tool_id, False, detail=f"{tool_id!r} is not an allowed tool")
        declaration, implementation = entry
        if rank(classification) > rank(declaration.maximum_classification):
            self.refusals.append({
                "toolId": tool_id, "caller": caller,
                "reason": f"{classification} data exceeds the tool's {declaration.maximum_classification} ceiling",
            })
            return ToolOutcome(
                tool_id, False,
                detail=(
                    f"{tool_id!r} may be given data classified up to {declaration.maximum_classification} "
                    f"and this task is {classification}"
                ),
            )
        try:
            outcome = implementation(arguments)
        except Exception as exc:  # a tool is third-party code; its faults are data
            self.invocations.append({"toolId": tool_id, "caller": caller, "ok": False})
            return ToolOutcome(tool_id, False, detail=f"{type(exc).__name__}: {exc}")
        if not isinstance(outcome, ToolOutcome):
            self.invocations.append({"toolId": tool_id, "caller": caller, "ok": False})
            return ToolOutcome(tool_id, False, detail="the tool did not return a ToolOutcome")
        self.invocations.append({"toolId": tool_id, "caller": caller, "ok": outcome.ok})
        return outcome
