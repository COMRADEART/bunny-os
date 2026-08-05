# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""How much an adaptation is allowed to cost the person using the machine.

Adapting to a smaller machine is only a virtue up to the point where it starts
throwing away somebody's afternoon. This module draws that line, and it draws it
by classifying the *act* rather than the reason for it: a plan that says a
service should stop is not, by itself, permission to terminate a process a
person is typing into.

Three classes, in increasing cost:

**Non-disruptive** — the user cannot tell, except by the machine getting
quieter. Lowering a background CPU weight, shrinking a cache, pausing an
optional indexer. These proceed automatically when policy permits.

**Gracefully disruptive** — something restarts or moves, and in-progress work
must be handed over rather than dropped. Switching an inference backend,
restarting a nonessential service with a smaller grant. These proceed
automatically, but only through a path that gives the service a chance to
finish, and never against a service that has declared it holds unsaved work.

**User-visible or destructive** — a person loses something: a foreground task
dies, unsaved state is discarded, data goes somewhere it has not been before,
money is spent, or an explicit pin is overridden. These require an approval, and
in its absence the answer is no.

The default when a class cannot be determined is the most expensive one.
Guessing "probably non-disruptive" about an act whose cost is unknown is exactly
the guess that loses somebody's work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ADAPTATION_CLASSES",
    "AdaptationAssessment",
    "EMERGENCY_POLICY",
    "USER_WORK_POLICIES",
    "assess_adaptation",
]

#: Increasing cost to the user. Ordered so that ``max`` of two classes is the
#: more expensive one, which is how a transition that is disruptive in two ways
#: is classified.
ADAPTATION_CLASSES = ("non_disruptive", "gracefully_disruptive", "user_visible")

_RANK = {name: index for index, name in enumerate(ADAPTATION_CLASSES)}

#: What may be done to work in progress, in increasing severity. §13 requires a
#: policy for each; these are the names the applicator uses for them.
USER_WORK_POLICIES = (
    "graceful_completion",      # let it finish, then act
    "user_notification",        # act, but say so
    "approval_required",        # ask, and do nothing until answered
    "deadline_shutdown",        # let it finish, but not indefinitely
    "emergency_only",           # only when the alternative is losing the machine
)

#: The one documented case in which user work may be interrupted without an
#: approval: the machine is about to become unusable anyway. Naming it here, as
#: a constant with a stated threshold, means an emergency is a measurement
#: rather than an adjective anybody can apply to a transition they are impatient
#: about.
EMERGENCY_POLICY = {
    "name": "imminent_memory_exhaustion",
    "condition": "available memory is below the protected reserve and still falling",
    "permits": "terminating a nonessential service that holds unsaved work, with a notification",
    "neverPermits": (
        "sending data to a remote provider, spending money, or stopping an essential service"
    ),
}


@dataclass(frozen=True)
class AdaptationAssessment:
    """What a transition would cost, and what must happen before it may run."""

    adaptation_class: str
    user_work_policy: str
    requires_approval: bool
    reasons: tuple[str, ...] = ()
    #: What the user keeps if this is refused. Never empty for a refusal: a
    #: refusal with no stated alternative is a dead end presented as a choice.
    fallback: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "adaptationClass": self.adaptation_class,
            "userWorkPolicy": self.user_work_policy,
            "requiresApproval": self.requires_approval,
            "reasons": list(self.reasons),
            "fallback": self.fallback,
        }


def _worst(*classes: str) -> str:
    return max(classes, key=lambda name: _RANK.get(name, len(_RANK)))


def assess_adaptation(
    operation: str,
    desired: Any,
    observation: Any,
    *,
    emergency: bool = False,
) -> AdaptationAssessment:
    """Classify one proposed transition.

    ``desired`` is a :class:`~capability.apply.state.DesiredService` and
    ``observation`` a :class:`~capability.apply.state.ServiceObservation`. Both
    are needed: the cost of stopping a service depends entirely on what that
    service is currently doing, and a plan cannot know that.
    """
    reasons: list[str] = []

    # Applying limits to something already running changes no behaviour the user
    # can name. This is the case the whole classification exists to keep cheap:
    # if tightening a CPU weight needed an approval, the machine could not adapt
    # at all without interrupting somebody.
    if operation in ("apply_limits", "reload", "probe"):
        return AdaptationAssessment(
            "non_disruptive", "graceful_completion", False,
            ("adjusting resource limits on a running service changes no user-visible behaviour",),
        )

    if operation == "start":
        return AdaptationAssessment(
            "non_disruptive", "graceful_completion",
            requires_approval=bool(desired.requires_approval),
            reasons=(
                ("this start needs an approval the plan recorded as outstanding",)
                if desired.requires_approval
                else ("starting a service takes nothing away from anyone",)
            ),
            fallback=(
                "the service stays stopped and its feature remains unavailable"
                if desired.requires_approval else ""
            ),
        )

    if operation == "resume":
        return AdaptationAssessment(
            "non_disruptive", "graceful_completion", False,
            ("resuming a suspended service restores what was already there",),
        )

    # Everything below here takes something away.
    classification = "gracefully_disruptive"
    policy = "graceful_completion"
    approval = False

    if operation == "suspend":
        reasons.append("suspending holds the service's memory and stops its work until it is resumed")
        if desired.suspendable is False:
            # The manifest says this service cannot be suspended safely. Doing
            # it anyway is the destructive case wearing a cheaper name.
            classification = "user_visible"
            policy = "approval_required"
            approval = True
            reasons.append("this service declares that it cannot be suspended safely")
    else:
        reasons.append("stopping ends the service's work")

    if getattr(observation, "user_facing", False):
        classification = _worst(classification, "user_visible")
        policy = "approval_required"
        approval = True
        reasons.append("a person is using this service right now")

    if getattr(observation, "holds_unsaved_work", False):
        classification = _worst(classification, "user_visible")
        policy = "approval_required"
        approval = True
        reasons.append("the service has declared that it holds unsaved work")

    if desired.essential:
        classification = _worst(classification, "user_visible")
        policy = "approval_required"
        approval = True
        reasons.append("this is an essential service; stopping it takes away the machine's control plane")

    if desired.locality == "remote":
        classification = _worst(classification, "user_visible")
        approval = True
        reasons.append("this transition would send work to a remote provider")

    if emergency and not desired.essential and desired.locality != "remote":
        # The documented exception, and the only one. It does not apply to
        # essential services and it never authorises an egress, because
        # neither of those becomes safe merely because memory is short.
        approval = False
        policy = "emergency_only"
        reasons.append(
            "the documented emergency policy applies: available memory is below the protected "
            "reserve, so this proceeds without an approval and the user is notified"
        )

    return AdaptationAssessment(
        classification, policy, approval, tuple(reasons),
        fallback=(
            "the service keeps running and the machine stays under pressure until "
            "the user answers or the pressure clears"
            if approval else ""
        ),
    )
