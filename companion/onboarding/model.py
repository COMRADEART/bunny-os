# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ten first-run steps, as data a window can draw and a test can assert.

§7 names ten steps and one rule that shapes all of them: **a valid offline first
run must be possible**. Every step is therefore either informational or
*skippable*, and the model enforces that structurally — :attr:`OnboardingStep.
required` is ``True`` for exactly two steps, the welcome and the finish, and
neither of them asks for anything.

The consequence worth stating: a machine with no network, no microphone, no
speakers, no AI model and no GPU completes this wizard. It arrives at a working
companion that types and reads, and every page it passed through told it what
was missing and what would fix it. That configuration is not an error path; on
the hardware this product is aimed at it is a common one.

What is *not* here: any decision. The steps carry surveys, and the surveys carry
their own reasons and remedies. This module owns the order, the skippability,
what has been answered, and how to persist that — nothing else. A wizard that
also decided whether Ollama was eligible would be a second opinion about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "ONBOARDING_STEPS",
    "OnboardingModel",
    "OnboardingStep",
    "StepView",
]


@dataclass(frozen=True)
class OnboardingStep:
    """One page. ``required`` means it cannot be skipped; two steps are."""

    step_id: str
    title: str
    body: str
    #: What the primary button says when this step can be completed.
    action: str = "Next"
    #: What the secondary button says, or empty when the step cannot be skipped.
    skip: str = "Skip"
    required: bool = False
    #: Which survey this page reads, or empty for a purely informational page.
    survey: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "stepId": self.step_id,
            "title": self.title,
            "body": self.body,
            "action": self.action,
            "skip": self.skip,
            "required": self.required,
            "survey": self.survey,
        }


#: The ten steps, in order. The bodies are the copy; they are here rather than
#: in the window because the accessibility surface, the CLI and the window all
#: have to say the same thing, and three copies of a sentence become three
#: different sentences.
ONBOARDING_STEPS: tuple[OnboardingStep, ...] = (
    OnboardingStep(
        "welcome", "Welcome to Bunny OS",
        "Bunny is a companion that lives on this machine. This takes a couple of minutes and "
        "everything in it can be changed later. You can close this window at any point and the "
        "desktop stays usable.",
        action="Get started", skip="", required=True,
    ),
    OnboardingStep(
        "privacy", "Local first, and it means it",
        "Bunny answers using AI that runs on this machine whenever one is available. Nothing "
        "leaves this computer unless you configure a remote provider yourself and approve the "
        "transfer. There is no telemetry in Bunny OS: no usage counters, no crash uploads, "
        "nothing sent in the background. Diagnostics are exported to a file you read first.",
        action="Continue", skip="",
    ),
    OnboardingStep(
        "character", "Meet Bunny",
        "This is how Bunny will appear on your machine. The presentation adapts to what your "
        "graphics can do, and everything Bunny says is also available as text.",
        action="Looks good", skip="", survey="character",
    ),
    OnboardingStep(
        "microphone", "Microphone",
        "Bunny listens only while you hold the push-to-talk key. There is no wake word and no "
        "continuous listening in this release — those are not switched off, they are not built. "
        "Choose a microphone, or skip this and type instead.",
        action="Use this microphone", skip="Skip — I'll type", survey="speech",
    ),
    OnboardingStep(
        "speaker", "Speaker test",
        "Bunny can read replies aloud. Play the test sound and tell us whether you heard it — "
        "nothing this program can measure tells us that for you. Captions always appear "
        "whether or not audio works.",
        action="I heard it", skip="Skip — no sound", survey="audio",
    ),
    OnboardingStep(
        "providers", "Where answers come from",
        "Bunny needs an AI provider to answer questions. Local providers run on this machine "
        "and are preferred whenever one is available.",
        action="Continue", skip="Set this up later", survey="providers",
    ),
    OnboardingStep(
        "local_model", "Local models",
        "This is what was found on your machine. Bunny does not download models: they are "
        "several gigabytes of your disk and your connection, and that is your decision to make.",
        action="Continue", skip="Continue without a local model", survey="providers",
    ),
    OnboardingStep(
        "remote_provider", "Remote providers (optional)",
        "You can add a provider that runs somewhere else. It stays off until you configure it, "
        "Bunny shows an indicator before anything is transmitted, and content classified as "
        "secret is never sent. Most people should skip this.",
        action="Add a provider", skip="Skip — local only",
    ),
    OnboardingStep(
        "permissions", "What Bunny may do to this computer",
        "Bunny can open applications, change the volume, copy text, show notifications and open "
        "links — and every one of those stops and asks you first, showing exactly what will "
        "happen. Bunny cannot run shell commands, control your keyboard or mouse, or act on a "
        "web page. Those are not permissions you can grant; they do not exist in this release.",
        action="Understood", skip="",
    ),
    OnboardingStep(
        "finish", "Ready",
        "Bunny starts automatically when you log in. If it ever fails to start you will get a "
        "recovery window rather than nothing, with a safe mode that turns off 3D, audio and "
        "desktop actions.",
        action="Finish", skip="", required=True,
    ),
)

_BY_ID = {step.step_id: step for step in ONBOARDING_STEPS}


@dataclass(frozen=True)
class StepView:
    """A step plus everything needed to draw it right now."""

    step: OnboardingStep
    index: int
    total: int
    survey: Any = None
    answered: bool = False
    skipped: bool = False

    @property
    def can_skip(self) -> bool:
        return not self.step.required and bool(self.step.skip)

    @property
    def progress(self) -> str:
        return f"Step {self.index + 1} of {self.total}"

    @property
    def detail(self) -> str:
        """The survey's own sentence, appended to the page copy.

        Empty for an informational page. This is the line that makes the wizard
        about *this machine* rather than about the product in general.
        """
        if self.survey is None:
            return ""
        for attribute in ("summary", "remedy"):
            value = getattr(self.survey, attribute, "")
            if value:
                return str(value)
        return ""

    def to_json(self) -> dict[str, Any]:
        return {
            "step": self.step.to_json(),
            "index": self.index,
            "total": self.total,
            "progress": self.progress,
            "detail": self.detail,
            "canSkip": self.can_skip,
            "answered": self.answered,
            "skipped": self.skipped,
            "survey": self.survey.to_json() if hasattr(self.survey, "to_json") else None,
        }


class OnboardingModel:
    """Position, answers and surveys. No window, no I/O beyond the surveys.

    Surveys are lazy and cached: the provider survey probes loopback ports and
    the speech survey loads a recogniser, and doing either on every repaint
    would make the wizard feel broken. :meth:`refresh` is how the *Check again*
    button re-asks, and it is the only thing that clears the cache.
    """

    def __init__(
        self,
        *,
        steps: Sequence[OnboardingStep] = ONBOARDING_STEPS,
        surveyors: Mapping[str, Callable[[], Any]] | None = None,
    ) -> None:
        self._steps = tuple(steps)
        self._surveyors: Mapping[str, Callable[[], Any]] = dict(surveyors or {})
        self._cache: dict[str, Any] = {}
        self._index = 0
        self._answered: dict[str, str] = {}

    # -- position ------------------------------------------------------------

    @property
    def steps(self) -> tuple[OnboardingStep, ...]:
        return self._steps

    @property
    def index(self) -> int:
        return self._index

    @property
    def step(self) -> OnboardingStep:
        return self._steps[self._index]

    @property
    def complete(self) -> bool:
        return self._answered.get("finish", "") != ""

    @property
    def at_first(self) -> bool:
        return self._index == 0

    @property
    def at_last(self) -> bool:
        return self._index == len(self._steps) - 1

    def view(self) -> StepView:
        step = self.step
        return StepView(
            step=step, index=self._index, total=len(self._steps),
            survey=self.survey(step.survey) if step.survey else None,
            answered=self._answered.get(step.step_id, "") == "answered",
            skipped=self._answered.get(step.step_id, "") == "skipped",
        )

    # -- movement ------------------------------------------------------------

    def advance(self, *, skipped: bool = False) -> OnboardingStep:
        """Record an answer for the current step and move on.

        Refuses to skip a required step, rather than silently accepting it: a
        wizard that let ``finish`` be skipped would leave the completion marker
        unwritten and run again at the next login.
        """
        step = self.step
        if skipped and step.required:
            raise ValueError(f"step {step.step_id!r} cannot be skipped")
        self._answered[step.step_id] = "skipped" if skipped else "answered"
        if self._index < len(self._steps) - 1:
            self._index += 1
        return self.step

    def back(self) -> OnboardingStep:
        if self._index > 0:
            self._index -= 1
        return self.step

    def go_to(self, step_id: str) -> OnboardingStep:
        for position, step in enumerate(self._steps):
            if step.step_id == step_id:
                self._index = position
                return step
        raise KeyError(f"unknown onboarding step {step_id!r}")

    # -- surveys -------------------------------------------------------------

    def survey(self, name: str) -> Any:
        if name not in self._cache:
            surveyor = self._surveyors.get(name)
            self._cache[name] = surveyor() if surveyor is not None else None
        return self._cache[name]

    def refresh(self, name: str = "") -> Any:
        """Re-run one survey, or all of them. What *Check again* calls."""
        if name:
            self._cache.pop(name, None)
            return self.survey(name)
        self._cache.clear()
        return None

    # -- persistence ---------------------------------------------------------

    @property
    def answers(self) -> dict[str, str]:
        return dict(self._answered)

    def restore(self, *, step_id: str = "", answers: Mapping[str, str] | None = None) -> None:
        """Resume where a closed window left off. Unknown ids are ignored.

        Ignored rather than refused: a state file written by a newer build with
        an extra step must not stop an older one from running the wizard, and
        the cost of ignoring it is that one page is shown again.
        """
        for key, value in (answers or {}).items():
            if key in _BY_ID and value in ("answered", "skipped"):
                self._answered[key] = value
        if step_id in _BY_ID:
            self.go_to(step_id)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "currentStep": self.step.step_id,
            "complete": self.complete,
            "answers": self.answers,
            "steps": [step.to_json() for step in self._steps],
        }
