# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The cinematic first-run steps, as data a window can draw and a test can assert.

A valid offline first run must be possible. Every step is therefore either
informational or *skippable*, and the model enforces that structurally —
:attr:`OnboardingStep.required` is ``True`` for exactly two steps, the welcome
and the finish, and neither of them asks for anything.

This is a short guided intro — name, timezone, accessibility, companion,
voice, privacy — not a Linux/systemd wizard. Microphone and speakers are
skippable. The last page leaves Bunny in the corner, or hidden if that was
chosen.

A machine with no network, no microphone, no speakers, no AI model and no GPU
completes this wizard. It arrives at a working desktop. That configuration is
not an error path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "ONBOARDING_ESSENTIAL_IDS",
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


#: The cinematic first-run, in order. Not a disk, locale, or systemd wizard.
ONBOARDING_STEPS: tuple[OnboardingStep, ...] = (
    OnboardingStep(
        "welcome", "Hi. I'm Bunny.",
        "Hi. I'm Bunny. I'll help you get ready on this computer. This takes a minute, "
        "and everything in it can be changed later. You can close this window at any point "
        "and the desktop stays usable.",
        action="Get started", skip="", required=True,
    ),
    OnboardingStep(
        "name", "What should I call you?",
        "A name is enough. This is how Bunny greets you — not a Linux username, "
        "and not an account password.",
        action="Continue", skip="Skip — no name yet",
    ),
    OnboardingStep(
        "timezone", "When is it where you are?",
        "The clock and calendar follow this. You can change it later in Date and Time.",
        action="Continue", skip="Skip — keep the system clock",
    ),
    OnboardingStep(
        "accessibility", "Make this comfortable",
        "Larger text, more contrast, less movement, captions, or a screen reader. "
        "You can change all of this later. Bunny is never required to use the OS.",
        action="Continue", skip="Skip — keep defaults",
    ),
    OnboardingStep(
        "companion", "Meet Bunny",
        "This is how Bunny will appear: Full 3D, Lightweight 2D, or Minimal. "
        "This computer recommends one from what it can draw; you can choose another, "
        "or hide the figure. Everything Bunny says is also available as text.",
        action="Looks good", skip="Skip — hide Bunny", survey="character",
    ),
    OnboardingStep(
        "voice", "Voice, if you want it",
        "Bunny listens only while you hold the push-to-talk key. There is no wake word "
        "and no continuous listening in this release — those are not switched off, they "
        "are not built. Choose a microphone and play a speaker test, or skip and type. "
        "Captions always appear.",
        action="Use voice", skip="Skip — I'll type", survey="speech",
    ),
    OnboardingStep(
        "privacy", "Local first, and it means it",
        "Bunny answers on this computer. Automatic is the default: pick a local model, "
        "and never go online because local is slower. No online models ever is Local only — "
        "not Cloud memory off. Cloud memory and a one-time online answer are two different "
        "consents; both stay off until you turn them on. There is no telemetry.",
        action="Continue", skip="Skip — I'll read this later",
    ),
    OnboardingStep(
        "finish", "Ready",
        "Ready. I'll be in the corner if you need me. If you hid Bunny, Search, Settings, "
        "and Trust still work. If Bunny ever fails to start you will get a recovery window "
        "rather than nothing.",
        action="Finish", skip="", required=True,
    ),
)

_BY_ID = {step.step_id: step for step in ONBOARDING_STEPS}

#: Older first-run files used the ten-step Linux-shaped ids. Resume onto the
#: cinematic spine rather than restarting the wizard.
_RESUME_ALIASES = {
    "character": "companion",
    "microphone": "voice",
    "speaker": "voice",
    "providers": "privacy",
    "local_model": "privacy",
    "remote_provider": "privacy",
    "permissions": "privacy",
}

#: Hello, companion, privacy, ready. Name, timezone, accessibility, and voice
#: stay skippable. The eight steps stay so nothing is hidden; this tuple is
#: which of them a first-run can treat as the progressive spine.
ONBOARDING_ESSENTIAL_IDS = ("welcome", "companion", "privacy", "finish")


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
        target = _RESUME_ALIASES.get(step_id, step_id)
        for position, step in enumerate(self._steps):
            if step.step_id == target:
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
            mapped = _RESUME_ALIASES.get(key, key)
            if mapped in _BY_ID and value in ("answered", "skipped"):
                self._answered[mapped] = value
        current = _RESUME_ALIASES.get(step_id, step_id)
        if current in _BY_ID:
            self.go_to(current)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "currentStep": self.step.step_id,
            "complete": self.complete,
            "answers": self.answers,
            "steps": [step.to_json() for step in self._steps],
        }
