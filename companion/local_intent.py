# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The executor that turns a recognised intent into a structured desktop action.

## What this is for

Every part of the machinery needed to open an application from a request has
existed for two phases: nine declared desktop actions with approval classes and
adapters, a broker that binds the approved act to the executed one, a runtime
that derives consent from tool declarations. The one missing piece was an
executor that ever *planned* one. The shipped executor plans
``text.count_words``, so on a machine with no provider configured, "Open Files"
counted the words in the sentence and reported ``words=2``.

This plans the action instead. It is deterministic, local, needs no model and
no network, and it is the executor that runs on every machine this has been
booted on.

## The safety property, stated once

An executor is provider-neutral and this one is not a provider — but it is the
component that stands where a model would stand, so it is built to the rule
that applies there: **nothing the user typed becomes an argument.**

:mod:`companion.intents` recognises a sentence as one of a closed set of intents
and attaches constants from its own tables. This module reads those constants,
resolves an application id against the *installed* entry registry, and emits a
:class:`~companion.executor.PlannedOperation` naming a declared tool. There is
no path from request text to an executable path, a command line, a URI or a
filesystem path outside the user's own XDG directories.

The consequences of that are worth being concrete about. ``rm -rf /`` typed into
the assistant is not recognised, so it plans nothing and the answer says what
the assistant can do. ``Open /usr/bin/evil`` is not recognised: "open" is a verb
in the table but ``/usr/bin/evil`` matches no application key, and application
keys are the only thing that can select an id.

## Approval

None of the approval logic is here, deliberately. A planned operation naming
``desktop.application.launch`` acquires its approval requirement from the
*tool declaration* in :mod:`companion.desktop_bridge`, which reads the
descriptor's ``approval_class``. An executor that could set its own approval
requirement could set it to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .executor import (
    ExecutorDeclaration,
    ExecutorHealth,
    PlannedOperation,
    ProducedOutput,
    TaskContext,
    TaskPlan,
    TaskResult,
    display_summary,
)
from .intents import Intent, capability_sentence, recognise

__all__ = ["LocalIntentExecutor", "resolve_installed_application", "user_directory"]


#: The tool the folder-listing intent plans. Declared in :mod:`companion.local_files`.
LIST_DIRECTORY_TOOL = "files.list_directory"

#: The desktop actions this executor may plan. Written out rather than derived
#: so that adding a new intent cannot silently reach an action nobody reviewed.
LAUNCH_ACTION = "desktop.application.launch"
REVEAL_ACTION = "desktop.file.reveal"


def user_directory(key: str) -> Path | None:
    """The absolute path of one XDG user directory, or None.

    Read from the user's own configuration through ``xdg-user-dir`` when it is
    present and from the conventional names when it is not. The *key* comes
    from :data:`companion.intents.FOLDERS`, so the set of directories that can
    be named is fixed at three lines of source; what a key resolves to is the
    user's business and this asks them rather than assuming ``~/Downloads``.
    """
    if key == "HOME":
        home = os.environ.get("HOME")
        return Path(home) if home else None
    variable = os.environ.get(f"XDG_{key}_DIR")
    if variable:
        candidate = Path(os.path.expandvars(variable)).expanduser()
        if candidate.is_dir():
            return candidate
    home = os.environ.get("HOME")
    if not home:
        return None
    conventional = {
        "DOWNLOAD": "Downloads", "DOCUMENTS": "Documents", "PICTURES": "Pictures",
        "MUSIC": "Music", "VIDEOS": "Videos", "DESKTOP": "Desktop",
    }.get(key)
    if conventional is None:
        return None
    candidate = Path(home) / conventional
    return candidate if candidate.is_dir() else None


def resolve_installed_application(candidates: Sequence[str]) -> str:
    """The first candidate this machine actually has, or ''.

    Asked of the entry registry rather than assumed, so a build without GNOME
    Terminal plans GNOME Console instead of planning an action that will fail
    at the adapter. An empty answer is a real answer: the caller says the
    application is not installed rather than planning something that cannot work.
    """
    try:
        from .desktop.entries import resolve_application
    except ImportError:  # pragma: no cover - desktop support absent from this build
        return ""
    for candidate in candidates:
        try:
            if resolve_application(candidate) is not None:
                return candidate
        except Exception:  # noqa: BLE001 - a malformed entry is not this decision
            continue
    return ""


@dataclass
class LocalIntentExecutor:
    """Plans one desktop action, or explains that it cannot."""

    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="local.intent",
        provider_id="local",
        implementation_id="bunny-companion-intent-1",
        local=True,
        # `local_action` is the type the desktop work belongs to; the others are
        # here because an unrecognised request still has to be *answered*, and
        # an executor that was ineligible for the task would leave the runtime
        # with nothing selected and the user with a blocked task rather than a
        # sentence.
        supported_task_types=("unclassified", "question", "local_action", "compute", "transform", "summarise"),
        supports_tools=True,
        supports_structured_output=True,
        supports_streaming=False,
        supports_cancellation=True,
        supports_resume=False,
        context_limit_tokens=4096,
        cost_class="free",
        # Nothing it is given leaves the device.
        maximum_privacy_class="secret",
        requires_authentication=False,
    ))
    reported_health: ExecutorHealth = field(default_factory=ExecutorHealth)
    cancelled_with: str = ""

    def health(self) -> ExecutorHealth:
        return self.reported_health

    # -- planning ----------------------------------------------------------

    def plan(self, context: TaskContext) -> TaskPlan:
        request = str(context.task.get("originalRequest", ""))
        revision = max(1, context.plan_revision)
        plan_id = "plan-" + hashlib.sha256(
            f"{context.task.get('taskId', '')}\x1f{revision}\x1fintent".encode("utf-8")
        ).hexdigest()[:16]

        intent = recognise(request)
        operations, summary = self._operations_for(intent)
        return TaskPlan(
            plan_id=plan_id,
            revision=revision,
            summary=summary,
            operations=tuple(operations),
            response_to_review="",
        )

    def _operations_for(self, intent: Intent | None) -> tuple[list[PlannedOperation], str]:
        if intent is None:
            return [], "Explain what this assistant can do"

        if intent.kind == "capabilities":
            return [], "Explain what this assistant can do"

        if intent.kind == "open_application":
            candidates = tuple(intent.parameters.get("candidates", ()))
            application_id = resolve_installed_application(candidates)
            if not application_id:
                # Planned as nothing, answered as a sentence. An action that
                # would certainly fail is worse than a clear "you do not have
                # that", because the failure arrives after an approval prompt.
                return [], f"Report that {intent.parameters.get('spoken', 'that application')} is not installed"
            return [
                PlannedOperation(
                    name="launch-application",
                    tool=LAUNCH_ACTION,
                    # The only value here that is not a literal from this file
                    # or from intents.py is one the entry registry returned.
                    arguments={"applicationId": application_id},
                ),
            ], intent.description

        if intent.kind == "list_folder":
            key = str(intent.parameters.get("directory", ""))
            path = user_directory(key)
            if path is None:
                return [], f"Report that the {intent.parameters.get('spoken', '')} folder was not found"
            return [
                PlannedOperation(
                    name="list-directory",
                    tool=LIST_DIRECTORY_TOOL,
                    arguments={"directory": key},
                ),
            ], intent.description

        if intent.kind == "show_folder":
            key = str(intent.parameters.get("directory", ""))
            path = user_directory(key)
            if path is None:
                return [], f"Report that the {intent.parameters.get('spoken', '')} folder was not found"
            return [
                PlannedOperation(
                    name="reveal-folder",
                    tool=REVEAL_ACTION,
                    arguments={"path": str(path)},
                ),
            ], intent.description

        # Unreachable while KNOWN_INTENTS and this function agree; a test holds
        # them to it. Falling through to an explanation rather than raising
        # keeps an unhandled intent a bad answer instead of a failed task.
        return [], "Explain what this assistant can do"

    # -- result ------------------------------------------------------------

    def result(self, context: TaskContext) -> TaskResult:
        request = str(context.task.get("originalRequest", ""))
        intent = recognise(request)
        summary, body = self._answer(intent, context.operation_results)
        return TaskResult(
            result_id="result-" + hashlib.sha256(
                f"{context.task.get('taskId', '')}\x1f{body}".encode("utf-8")
            ).hexdigest()[:16],
            summary=display_summary(summary),
            outputs=(
                ProducedOutput(
                    output_id="output-1",
                    kind="text",
                    content=body,
                    classification=str(context.classification),
                ),
            ),
            classification=str(context.classification),
        )

    @staticmethod
    def _outcome(results: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
        """The record of one operation, or None if it did not produce one.

        The runtime's convention, which is not obvious and cost a debugging
        round: a *successful* operation appends ``{"name", "value", "detail"}``
        and a *failed* one appends nothing at all — it emits ``operation_failed``
        and the plan stops. So absence means "did not succeed", and there is no
        ``ok`` field to consult. Reading one that does not exist made every
        answer here report failure while the operation had in fact completed.

        ``skipped`` and ``unknown`` records do appear, for operations a restart
        found already-done or indeterminate. A skipped operation succeeded
        before, so it counts; an unknown one does not.
        """
        for item in results:
            if str(item.get("name", "")) != name:
                continue
            if item.get("unknown"):
                return None
            return item
        return None

    def _answer(
        self, intent: Intent | None, results: Sequence[Mapping[str, Any]]
    ) -> tuple[str, str]:
        """What the user is told, and what is recorded. Often the same."""
        if intent is None or intent.kind == "capabilities":
            sentence = capability_sentence()
            return sentence, sentence

        if intent.kind == "open_application":
            spoken = str(intent.parameters.get("spoken", "the application"))
            outcome = self._outcome(results, "launch-application")
            if outcome is None:
                return (
                    f"I could not open {spoken.title()}. It is either not installed on this "
                    "machine or the launch was refused.",
                    f"launch did not complete: {spoken}",
                )
            return f"{spoken.title()} is open.", f"launched {spoken}"

        if intent.kind == "list_folder":
            spoken = str(intent.parameters.get("spoken", "that folder"))
            outcome = self._outcome(results, "list-directory")
            if outcome is None:
                return (
                    f"I could not read your {spoken.title()} folder.",
                    f"listing did not complete: {spoken}",
                )
            value = str(outcome.get("value") or "").strip()
            if not value:
                return (
                    f"I could not read your {spoken.title()} folder.",
                    f"listing returned nothing: {spoken}",
                )
            return value, value

        if intent.kind == "show_folder":
            spoken = str(intent.parameters.get("spoken", "that folder"))
            outcome = self._outcome(results, "reveal-folder")
            if outcome is None:
                return (
                    f"I could not open your {spoken.title()} folder.",
                    f"reveal did not complete: {spoken}",
                )
            return f"Your {spoken.title()} folder is open.", f"revealed {spoken}"

        sentence = capability_sentence()
        return sentence, sentence

    def cancel(self, context: TaskContext, reason: str) -> None:
        self.cancelled_with = reason

    def unavailable(self, detail: str) -> "LocalIntentExecutor":
        return replace(
            self,
            reported_health=ExecutorHealth(available=False, healthy=False, detail=detail),
        )
