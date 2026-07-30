# SPDX-License-Identifier: Apache-2.0
"""Controlled pilot definitions, success criteria, and readiness gating.

Pilots run smallest-first. ``assert_pilot_order`` refuses to start a larger pilot
before the smaller one has completed successfully, because "run a small pilot
first" is only a real control if skipping it fails.

Success criteria are operational only. ``PROHIBITED_MEASURES`` names the metrics a
pilot must not collect: productivity, output volume, activity, and anything else
that measures the person rather than the system. Measuring those requires a
separate research protocol with its own consent, which is out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1

#: Pilot kinds, smallest first.
PILOT_ORDER = (
    "internal-pilot",
    "small-community-pilot",
    "research-lab-pilot",
    "small-business-pilot",
    "oem-engineering-pilot",
)

#: Every pilot must define these before it starts.
REQUIRED_PILOT_FIELDS = (
    "scope",
    "durationDays",
    "deviceCount",
    "supportedHardware",
    "supportOwner",
    "successCriteria",
    "privacyNotice",
    "incidentProcess",
    "rollbackPlan",
    "exitPlan",
)

#: Operational outcomes a pilot may measure.
PERMITTED_MEASURES = (
    "enrolmentSuccessRate",
    "policyDeliverySuccessRate",
    "updateSuccessRate",
    "rollbackSuccessRate",
    "recoverySuccessRate",
    "supportTicketCategories",
    "serviceAvailability",
    "hardwareReliability",
)

#: Measures that would study the user rather than the system.
PROHIBITED_MEASURES = frozenset({
    "userproductivity", "productivity", "outputvolume", "taskspercompleted", "timeontask",
    "activelevel", "engagement", "featureadoption", "sessionlength", "promptcount",
    "aiusagefrequency", "keystrokes", "attentionscore", "performancerating",
})

#: Maximum device counts. A pilot larger than its kind allows is refused.
MAXIMUM_DEVICES = {
    "internal-pilot": 25,
    "small-community-pilot": 100,
    "research-lab-pilot": 100,
    "small-business-pilot": 250,
    "oem-engineering-pilot": 50,
}

#: Gates that must pass before any pilot may begin. Every one currently depends on
#: a stable release that does not exist, which is why pilot readiness is NO-GO.
PILOT_ENTRY_GATES = (
    "stableReleasePublished",
    "signedStableArtifacts",
    "reproducibleBuildEvidence",
    "postReleaseSecurityReview",
    "postReleasePrivacyReview",
    "phase7SecurityReview",
    "phase7PrivacyReview",
    "multiTenancyIsolationTests",
    "syncCryptographyIndependentReview",
    "oemRecoveryValidation",
    "supportCapacityConfirmed",
)


class PilotError(ValueError):
    """Raised when a pilot definition or readiness claim is invalid."""


def _folded(key: str) -> str:
    return key.replace("_", "").replace("-", "").casefold()


@dataclass(frozen=True)
class PilotReadiness:
    pilot: str
    ready: bool
    missingFields: tuple[str, ...]
    failedGates: tuple[str, ...]
    missingGates: tuple[str, ...]
    problems: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pilot": self.pilot,
            "ready": self.ready,
            "missingFields": list(self.missingFields),
            "failedGates": list(self.failedGates),
            "missingGates": list(self.missingGates),
            "problems": list(self.problems),
            "recommendation": "GO" if self.ready else "NO-GO",
        }


def assert_pilot_order(pilot: str, completed: Sequence[str]) -> None:
    """Refuse a pilot whose smaller predecessors have not completed."""
    if pilot not in PILOT_ORDER:
        raise PilotError(f"unknown pilot {pilot!r}; pilots are {', '.join(PILOT_ORDER)}")
    index = PILOT_ORDER.index(pilot)
    done = set(completed)
    unknown = sorted(done - set(PILOT_ORDER))
    if unknown:
        raise PilotError("unknown completed pilots: " + ", ".join(unknown))
    outstanding = [name for name in PILOT_ORDER[:index] if name not in done]
    if outstanding:
        raise PilotError(
            f"{pilot} cannot begin before these smaller pilots complete: " + ", ".join(outstanding)
        )


def evaluate_pilot(definition: Mapping[str, Any], gates: Mapping[str, Any]) -> PilotReadiness:
    """Evaluate one pilot definition against the entry gates."""
    if not isinstance(definition, Mapping):
        raise PilotError("definition must be a mapping")
    if not isinstance(gates, Mapping):
        raise PilotError("gates must be a mapping")

    pilot = definition.get("pilot")
    if pilot not in PILOT_ORDER:
        raise PilotError(f"unknown pilot {pilot!r}")

    problems: list[str] = []
    missing_fields = [field for field in REQUIRED_PILOT_FIELDS if not definition.get(field)]

    device_count = definition.get("deviceCount")
    if isinstance(device_count, int) and not isinstance(device_count, bool):
        limit = MAXIMUM_DEVICES[pilot]
        if device_count > limit:
            problems.append(f"{pilot} permits at most {limit} devices; {device_count} were requested")
        if device_count < 1:
            problems.append("deviceCount must be at least 1")
    elif "deviceCount" not in missing_fields:
        problems.append("deviceCount must be a whole number")

    criteria = definition.get("successCriteria")
    if criteria is not None:
        if not isinstance(criteria, list):
            problems.append("successCriteria must be a list")
        else:
            offending = sorted(str(item) for item in criteria if _folded(str(item)) in PROHIBITED_MEASURES)
            if offending:
                problems.append(
                    "these success criteria measure people rather than systems and require a separate "
                    "research protocol with consent: " + ", ".join(offending)
                )
            unknown = sorted(
                str(item) for item in criteria
                if _folded(str(item)) not in PROHIBITED_MEASURES
                and str(item) not in PERMITTED_MEASURES
            )
            if unknown:
                problems.append("unrecognised success criteria: " + ", ".join(unknown))

    unknown_gates = sorted(set(gates) - set(PILOT_ENTRY_GATES))
    if unknown_gates:
        raise PilotError("unknown pilot entry gates: " + ", ".join(unknown_gates))
    missing_gates = [name for name in PILOT_ENTRY_GATES if name not in gates]
    failed_gates = [name for name in PILOT_ENTRY_GATES if gates.get(name) is not True]
    failed_gates = [name for name in failed_gates if name not in missing_gates]

    ready = not missing_fields and not problems and not missing_gates and not failed_gates
    return PilotReadiness(
        pilot=pilot,
        ready=ready,
        missingFields=tuple(missing_fields),
        failedGates=tuple(failed_gates),
        missingGates=tuple(missing_gates),
        problems=tuple(problems),
    )


def describe_pilots() -> list[dict[str, Any]]:
    """Return the pilot catalogue for documentation."""
    return [
        {
            "pilot": name,
            "maximumDevices": MAXIMUM_DEVICES[name],
            "predecessors": list(PILOT_ORDER[:index]),
        }
        for index, name in enumerate(PILOT_ORDER)
    ]
