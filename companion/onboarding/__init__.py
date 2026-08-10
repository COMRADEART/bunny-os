# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a person is asked, and shown, the first time Bunny OS starts.

Everything in this package is **presentation-free**. The first-run window draws
what these modules report; it does not decide anything. That split is here for
one reason: the decisions are the part that has to be tested, and a decision
that only exists inside a GTK callback can only be tested by opening a window.

The four surveys — providers, speech, audio, character — share a shape, and the
shape is the whole design:

``present``
    the thing exists on this machine. A file, a binary, a device node.
``operational``
    the thing answered. A server responded, a device enumerated, a package
    validated. **Never inferred from presence**, because §20 of the phase brief
    says so and because every one of these has a configuration where presence
    holds and operation does not: an installed Ollama with no server running, a
    sound card with no server, a Vosk library with no model, a 3D-capable GPU
    with a character package that fails validation.
``eligible``
    operational *and* good enough to use for the thing the user wants.
``reason``
    why not, in words, when any of the three is false.
``remedy``
    what the user can do about it, in words, without a terminal where that is
    possible and naming the exact command where it is not.

``remedy`` is the field that makes this onboarding rather than a status page. A
first run that says "no local model available" and stops has told the user they
have a problem and left them with it.

Nothing here downloads anything. Not a model, not a recogniser, not a character.
§8 and §9 both say so, and the reason is the same in both cases: a multi-gigabyte
transfer that the user did not ask for is a decision about their disk, their
bandwidth and — on a metered connection — their money.
"""

from __future__ import annotations

from .audio import AudioSurvey, AudioDeviceFinding, survey_audio
from .character import CharacterSurvey, survey_character
from .model import (
    ONBOARDING_STEPS,
    OnboardingModel,
    OnboardingStep,
    StepView,
)
from .providers import (
    LocalProviderFinding,
    LocalProviderSurvey,
    ModelSummary,
    survey_local_providers,
)
from .speech import SpeechSurvey, survey_speech

__all__ = [
    "ONBOARDING_STEPS",
    "AudioDeviceFinding",
    "AudioSurvey",
    "CharacterSurvey",
    "LocalProviderFinding",
    "LocalProviderSurvey",
    "ModelSummary",
    "OnboardingModel",
    "OnboardingStep",
    "SpeechSurvey",
    "StepView",
    "survey_audio",
    "survey_character",
    "survey_local_providers",
    "survey_speech",
]
