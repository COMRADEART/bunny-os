# SPDX-License-Identifier: Apache-2.0
"""Policy conflict resolution and precedence.

Precedence is fixed and total:

1. safety invariant
2. operating-system security policy
3. organisation device policy
4. user preference
5. application preference

The resolver always produces an explanation, because a user who cannot change a
setting is entitled to know which layer decided that and who owns it. Silent
enforcement is the failure mode this module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from enterprise.policy import SAFETY_INVARIANTS, PolicyError

#: Highest precedence first. Index in this tuple is the authority rank.
PRECEDENCE_ORDER = (
    "safety-invariant",
    "operating-system-security-policy",
    "organisation-device-policy",
    "user-preference",
    "application-preference",
)

_RANK = {layer: index for index, layer in enumerate(PRECEDENCE_ORDER)}

#: Human-readable owner for each layer, shown alongside a blocked control.
LAYER_OWNERS = {
    "safety-invariant": "Bunny OS safety invariant",
    "operating-system-security-policy": "Bunny OS security policy",
    "organisation-device-policy": "your organisation",
    "user-preference": "you",
    "application-preference": "the application",
}


@dataclass(frozen=True)
class ConflictDecision:
    setting: str
    winningLayer: str
    winningValue: Any
    winningOwner: str
    overriddenLayers: tuple[str, ...]
    explanation: str
    userChangeable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "setting": self.setting,
            "winningLayer": self.winningLayer,
            "winningValue": self.winningValue,
            "winningOwner": self.winningOwner,
            "overriddenLayers": list(self.overriddenLayers),
            "explanation": self.explanation,
            "userChangeable": self.userChangeable,
        }


def resolve(setting: str, candidates: Sequence[Mapping[str, Any]]) -> ConflictDecision:
    """Resolve competing values for one setting.

    Each candidate is ``{"layer": str, "value": Any, "owner": str | None,
    "priority": int | None}``. Within a layer, a higher ``priority`` wins; ties
    are refused rather than resolved arbitrarily, because an arbitrary winner
    makes fleet behaviour unpredictable.
    """
    if not candidates:
        raise PolicyError(f"no candidates supplied for {setting!r}")

    for candidate in candidates:
        layer = candidate.get("layer")
        if layer not in _RANK:
            raise PolicyError(f"unknown precedence layer {layer!r}")

    best_rank = min(_RANK[candidate["layer"]] for candidate in candidates)
    contenders = [candidate for candidate in candidates if _RANK[candidate["layer"]] == best_rank]

    if len(contenders) > 1:
        priorities = [candidate.get("priority") for candidate in contenders]
        if any(value is None for value in priorities):
            raise PolicyError(
                f"{setting!r} has {len(contenders)} candidates in layer "
                f"{PRECEDENCE_ORDER[best_rank]!r} without priorities; conflict cannot be resolved deterministically"
            )
        highest = max(priorities)
        if priorities.count(highest) > 1:
            raise PolicyError(
                f"{setting!r} has multiple candidates at priority {highest} in layer "
                f"{PRECEDENCE_ORDER[best_rank]!r}; the organisation must break the tie explicitly"
            )
        winner = next(item for item in contenders if item.get("priority") == highest)
    else:
        winner = contenders[0]

    winning_layer = winner["layer"]
    overridden = tuple(
        sorted({candidate["layer"] for candidate in candidates if candidate is not winner and candidate["layer"] != winning_layer})
    )
    owner = winner.get("owner") or LAYER_OWNERS[winning_layer]
    user_changeable = winning_layer in {"user-preference", "application-preference"}

    if winning_layer == "safety-invariant":
        explanation = f"{setting} is fixed by a Bunny OS safety invariant and cannot be changed by anyone."
    elif winning_layer == "operating-system-security-policy":
        explanation = f"{setting} is set by Bunny OS security policy, which an organisation cannot relax."
    elif winning_layer == "organisation-device-policy":
        explanation = (
            f"{setting} is managed by {owner}. It applies because this device is enrolled, "
            "and it overrides your personal preference for this setting only."
        )
    elif winning_layer == "user-preference":
        explanation = f"{setting} is your choice; no organisation policy applies to it."
    else:
        explanation = f"{setting} is set by the application and you can change it."

    if overridden:
        explanation += f" Overridden: {', '.join(overridden)}."

    return ConflictDecision(
        setting=setting,
        winningLayer=winning_layer,
        winningValue=winner.get("value"),
        winningOwner=owner,
        overriddenLayers=overridden,
        explanation=explanation,
        userChangeable=user_changeable,
    )


def assert_organisation_policy_permitted(setting: str) -> None:
    """Refuse an organisation policy that targets a safety invariant.

    Worked examples, all enforced rather than documented:

    * requiring encryption is permitted;
    * disabling update signature verification is refused;
    * exposing private Bunny memory to a fleet is refused.
    """
    if setting in SAFETY_INVARIANTS:
        raise PolicyError(
            f"{setting!r} is a safety invariant; organisation policy cannot set it at any enforcement level"
        )


def assert_user_cannot_bypass(setting: str, layer: str) -> None:
    """Refuse a user preference that would undercut a mandatory baseline."""
    if layer not in _RANK:
        raise PolicyError(f"unknown precedence layer {layer!r}")
    if layer in {"user-preference", "application-preference"} and setting in SAFETY_INVARIANTS:
        raise PolicyError(
            f"{setting!r} is a mandatory security baseline and cannot be overridden by a {layer}"
        )


def explain_for_display(decisions: Sequence[ConflictDecision]) -> list[dict[str, Any]]:
    """Render decisions for the settings UI, including ownership."""
    return [
        {
            "setting": decision.setting,
            "managedBy": decision.winningOwner,
            "changeable": decision.userChangeable,
            "why": decision.explanation,
        }
        for decision in decisions
    ]
