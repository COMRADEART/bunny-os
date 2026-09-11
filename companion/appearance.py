# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three product appearance modes a person chooses between.

Bunny OS offers **Full 3D**, **Lightweight 2D** (pre-rendered frames) and
**Minimal**. Capability recommends one from measured hardware; a person may
override. Override never raises the surface above what the machine can
honour — there is no "force 3D" — and the recommendation stays visible so
a later switch back is not guessing.

This is a product vocabulary on top of two existing axes that must not be
collapsed:

* :class:`companion.character.modes.RenderMode` — which renderer draws
* :attr:`companion.settings.CharacterSettings.companion_mode` — how much
  chrome the character takes

Appearance is what Settings and first-run should show. Renderer mode and
companion chrome are derived from it, never the other way around on this
surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from companion.character.adaptation import Presentation
from companion.character.modes import RenderMode
from companion.presentation import (
    PresentationRecommendation,
    PresentationSignals,
    select_presentation,
)

__all__ = [
    "APPEARANCE_MODES",
    "AppearanceChoice",
    "AppearanceMode",
    "DEFAULT_APPEARANCE",
    "appearance_blurb",
    "appearance_from_settings",
    "appearance_title",
    "apply_appearance",
    "parse_appearance",
    "recommend_appearance",
]


class AppearanceMode(str, Enum):
    """What a person picks on the appearance page."""

    FULL_3D = "full-3d"
    LIGHTWEIGHT_2D = "lightweight-2d"
    MINIMAL = "minimal"


APPEARANCE_MODES = (
    AppearanceMode.FULL_3D,
    AppearanceMode.LIGHTWEIGHT_2D,
    AppearanceMode.MINIMAL,
)

#: The product default. Matches :data:`companion.character.modes.DEFAULT_MODE`.
DEFAULT_APPEARANCE = AppearanceMode.LIGHTWEIGHT_2D

_TITLES: Mapping[AppearanceMode, str] = {
    AppearanceMode.FULL_3D: "Full 3D",
    AppearanceMode.LIGHTWEIGHT_2D: "Lightweight 2D",
    AppearanceMode.MINIMAL: "Minimal",
}

_BLURBS: Mapping[AppearanceMode, str] = {
    AppearanceMode.FULL_3D: "A moving 3D Bunny. Uses more graphics and battery.",
    AppearanceMode.LIGHTWEIGHT_2D: "A pre-rendered Bunny. The usual choice, and the lightest that still looks like Bunny.",
    AppearanceMode.MINIMAL: "A small still figure and a status word. Lowest cost.",
}

#: Highest capability rung each appearance may reach. A ceiling, never a floor.
_CEILINGS: Mapping[AppearanceMode, Presentation] = {
    AppearanceMode.FULL_3D: Presentation.FULL_3D,
    AppearanceMode.LIGHTWEIGHT_2D: Presentation.ANIMATED_2D,
    AppearanceMode.MINIMAL: Presentation.STATIC_IMAGE,
}

_RENDER: Mapping[AppearanceMode, RenderMode] = {
    AppearanceMode.FULL_3D: RenderMode.THREE_D,
    AppearanceMode.LIGHTWEIGHT_2D: RenderMode.PRERENDERED,
    AppearanceMode.MINIMAL: RenderMode.PRERENDERED,
}

_CHROME: Mapping[AppearanceMode, str] = {
    AppearanceMode.FULL_3D: "full",
    AppearanceMode.LIGHTWEIGHT_2D: "full",
    AppearanceMode.MINIMAL: "minimal",
}

_KIND_TO_APPEARANCE: Mapping[str, AppearanceMode] = {
    "full-3d": AppearanceMode.FULL_3D,
    "lightweight-3d": AppearanceMode.FULL_3D,
    "animated-2d": AppearanceMode.LIGHTWEIGHT_2D,
    "static-image": AppearanceMode.MINIMAL,
    "audio-only": AppearanceMode.MINIMAL,
    "text-only": AppearanceMode.MINIMAL,
}

_ALIASES = {
    "full-3d": AppearanceMode.FULL_3D,
    "3d": AppearanceMode.FULL_3D,
    "full3d": AppearanceMode.FULL_3D,
    "lightweight-2d": AppearanceMode.LIGHTWEIGHT_2D,
    "lightweight2d": AppearanceMode.LIGHTWEIGHT_2D,
    "2d": AppearanceMode.LIGHTWEIGHT_2D,
    "prerendered": AppearanceMode.LIGHTWEIGHT_2D,
    "pre-rendered": AppearanceMode.LIGHTWEIGHT_2D,
    "minimal": AppearanceMode.MINIMAL,
    "static": AppearanceMode.MINIMAL,
    "text-only": AppearanceMode.MINIMAL,
}


@dataclass(frozen=True)
class AppearanceChoice:
    """Recommendation, override, and what will actually draw."""

    recommended: AppearanceMode
    chosen: AppearanceMode
    effective: AppearanceMode
    eligible_kind: str
    override: bool
    bounded: bool
    reasons: tuple[str, ...]

    @property
    def title(self) -> str:
        return _TITLES[self.effective]

    def settings_patch(self) -> dict[str, str]:
        """What to write into :class:`~companion.settings.CharacterSettings`.

        Persists the *chosen* mode so a bounded 3D request can return when
        hardware allows. Drawing still uses :attr:`effective`. There is no
        ``three_d="on"`` — auto or off only.
        """
        return {
            "render_mode": _RENDER[self.chosen].value,
            "companion_mode": _CHROME[self.chosen],
            "three_d": "auto" if self.chosen is AppearanceMode.FULL_3D else "off",
        }

    def to_json(self) -> dict[str, object]:
        return {
            "recommended": self.recommended.value,
            "recommendedTitle": _TITLES[self.recommended],
            "chosen": self.chosen.value,
            "chosenTitle": _TITLES[self.chosen],
            "effective": self.effective.value,
            "effectiveTitle": _TITLES[self.effective],
            "eligibleKind": self.eligible_kind,
            "override": self.override,
            "bounded": self.bounded,
            "reasons": list(self.reasons),
            "renderMode": _RENDER[self.effective].value,
            "companionMode": _CHROME[self.effective],
            "ceiling": _CEILINGS[self.effective].value,
            "blurb": _BLURBS[self.effective],
        }


def appearance_title(mode: AppearanceMode) -> str:
    return _TITLES[mode]


def appearance_blurb(mode: AppearanceMode) -> str:
    return _BLURBS[mode]


def parse_appearance(value: str | None) -> AppearanceMode:
    """Read an appearance name. Unknown values become the default, not an error."""
    key = str(value or "").strip().casefold().replace("_", "-")
    return _ALIASES.get(key, DEFAULT_APPEARANCE)


def appearance_from_settings(render_mode: str, companion_mode: str) -> AppearanceMode:
    """Derive appearance from already-persisted character settings.

    ``companion_mode=minimal`` wins: a person who asked for a small still
    figure did not ask for 3D chrome. Otherwise the renderer mode decides.
    """
    if companion_mode == "minimal":
        return AppearanceMode.MINIMAL
    if render_mode == "3d":
        return AppearanceMode.FULL_3D
    return AppearanceMode.LIGHTWEIGHT_2D


def recommend_appearance(
    signals: PresentationSignals,
    *,
    recommendation: PresentationRecommendation | None = None,
) -> AppearanceMode:
    """What this hardware should suggest. Never a claim about a physical device
    unless ``signals`` came from one.
    """
    rec = recommendation or select_presentation(signals)
    return _KIND_TO_APPEARANCE.get(rec.implementation, DEFAULT_APPEARANCE)


def _rank(mode: AppearanceMode) -> int:
    return {
        AppearanceMode.MINIMAL: 0,
        AppearanceMode.LIGHTWEIGHT_2D: 1,
        AppearanceMode.FULL_3D: 2,
    }[mode]


def apply_appearance(
    *,
    signals: PresentationSignals,
    chosen: AppearanceMode | str | None = None,
    override: bool = False,
) -> AppearanceChoice:
    """Bound a person's choice by what the machine can honour.

    ``override=True`` means they picked ``chosen`` rather than accepting the
    recommendation. A choice heavier than eligibility is stored (so it can
    come back when hardware allows) and the *effective* mode is lowered.
    """
    recommendation = select_presentation(signals)
    recommended = _KIND_TO_APPEARANCE.get(recommendation.implementation, DEFAULT_APPEARANCE)
    picked = parse_appearance(chosen.value if isinstance(chosen, AppearanceMode) else chosen)
    if not override and chosen is None:
        picked = recommended
    eligible = _KIND_TO_APPEARANCE.get(recommendation.eligible, AppearanceMode.MINIMAL)
    reasons = list(recommendation.reasons)
    bounded = _rank(picked) > _rank(eligible)
    effective = picked
    if bounded:
        effective = eligible
        reasons.append(
            f"you asked for {_TITLES[picked]}, and this machine can honour "
            f"{_TITLES[eligible]} — the choice is kept, the drawing is lowered"
        )
    elif override and picked is not recommended:
        reasons.append(
            f"you chose {_TITLES[picked]} instead of the recommended {_TITLES[recommended]}"
        )
    elif not override:
        reasons.append(f"recommended {_TITLES[recommended]} from what this machine can draw")
    return AppearanceChoice(
        recommended=recommended,
        chosen=picked,
        effective=effective,
        eligible_kind=recommendation.eligible,
        override=bool(override),
        bounded=bounded,
        reasons=tuple(reasons),
    )
