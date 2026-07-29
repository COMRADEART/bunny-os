"""Device decommissioning and lost-device response.

Each scenario has a *required* action set. The point of enumerating them is that
partial decommissioning is the common real-world failure: a device is wiped but
its enrolment certificate is never revoked, or it is removed from the console but
its sync device key still decrypts new data.

``evaluate_decommission`` therefore refuses to report a device as decommissioned
until every required action for that scenario is recorded as completed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1

SCENARIOS = (
    "personally-owned-unenrolment",
    "organisation-owned-reassignment",
    "device-retirement",
    "storage-replacement",
    "lost-device",
    "stolen-device",
)

ACTIONS = (
    "revoke-enrolment-certificate",
    "remove-organisation-data",
    "remove-organisation-applications",
    "revoke-organisation-credentials",
    "rotate-sync-keys",
    "revoke-sync-device",
    "remove-from-update-rings",
    "remove-from-groups",
    "archive-audit-history",
    "cryptographic-erase",
    "full-reset",
    "notify-user",
    "record-incident-report",
)

#: Required actions per scenario. A personally owned unenrolment deliberately does
#: *not* include a wipe: the organisation withdraws its own footprint and nothing
#: more.
REQUIRED_ACTIONS: dict[str, tuple[str, ...]] = {
    "personally-owned-unenrolment": (
        "revoke-enrolment-certificate",
        "remove-organisation-data",
        "remove-organisation-applications",
        "revoke-organisation-credentials",
        "remove-from-update-rings",
        "remove-from-groups",
        "archive-audit-history",
        "notify-user",
    ),
    "organisation-owned-reassignment": (
        "revoke-enrolment-certificate",
        "remove-organisation-data",
        "revoke-organisation-credentials",
        "revoke-sync-device",
        "rotate-sync-keys",
        "remove-from-update-rings",
        "remove-from-groups",
        "archive-audit-history",
        "full-reset",
    ),
    "device-retirement": (
        "revoke-enrolment-certificate",
        "revoke-organisation-credentials",
        "revoke-sync-device",
        "rotate-sync-keys",
        "remove-from-update-rings",
        "remove-from-groups",
        "archive-audit-history",
        "cryptographic-erase",
    ),
    "storage-replacement": (
        "revoke-sync-device",
        "rotate-sync-keys",
        "cryptographic-erase",
        "archive-audit-history",
    ),
    "lost-device": (
        "revoke-enrolment-certificate",
        "revoke-organisation-credentials",
        "revoke-sync-device",
        "rotate-sync-keys",
        "remove-from-update-rings",
        "archive-audit-history",
        "record-incident-report",
        "notify-user",
    ),
    "stolen-device": (
        "revoke-enrolment-certificate",
        "revoke-organisation-credentials",
        "revoke-sync-device",
        "rotate-sync-keys",
        "remove-from-update-rings",
        "archive-audit-history",
        "record-incident-report",
        "notify-user",
    ),
}

#: Actions that require the device to be organisation-owned.
ORGANISATION_OWNED_ONLY_ACTIONS = frozenset({"full-reset", "cryptographic-erase"})

_CORRELATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class DecommissionError(ValueError):
    """Raised when a decommission record is malformed or incomplete."""


@dataclass(frozen=True)
class DecommissionVerdict:
    scenario: str
    complete: bool
    outstandingActions: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    completedActions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "complete": self.complete,
            "outstandingActions": list(self.outstandingActions),
            "refusals": list(self.refusals),
            "completedActions": list(self.completedActions),
        }


def evaluate_decommission(record: Mapping[str, Any]) -> DecommissionVerdict:
    """Evaluate whether a decommission is complete and permitted."""
    if not isinstance(record, Mapping):
        raise DecommissionError("record must be a mapping")

    allowed = {
        "schemaVersion", "scenario", "organisationOwned", "completedActions",
        "auditCorrelationId", "recoveryPreserved",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise DecommissionError("unknown decommission fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise DecommissionError("unsupported decommission schemaVersion")

    scenario = record.get("scenario")
    if scenario not in SCENARIOS:
        raise DecommissionError(f"scenario {scenario!r} is not recognised")

    organisation_owned = record.get("organisationOwned")
    if not isinstance(organisation_owned, bool):
        raise DecommissionError("organisationOwned must be a boolean")

    completed = record.get("completedActions", [])
    if not isinstance(completed, list):
        raise DecommissionError("completedActions must be a list")
    unknown = sorted(set(map(str, completed)) - set(ACTIONS))
    if unknown:
        raise DecommissionError("unknown decommission actions: " + ", ".join(unknown))
    completed_set = set(map(str, completed))

    correlation = record.get("auditCorrelationId")
    refusals: list[str] = []
    if not isinstance(correlation, str) or not _CORRELATION_ID.match(correlation):
        refusals.append("decommissioning requires an audit correlation id so the action is auditable")

    if not organisation_owned:
        overreach = sorted(completed_set & ORGANISATION_OWNED_ONLY_ACTIONS)
        if overreach:
            refusals.append(
                "these actions require an organisation-owned device: " + ", ".join(overreach)
            )

    if "full-reset" in completed_set or "cryptographic-erase" in completed_set:
        if record.get("recoveryPreserved") is not True:
            refusals.append(
                "a full reset or cryptographic erase must preserve the recovery environment so the "
                "device remains reinstallable"
            )

    required = REQUIRED_ACTIONS[scenario]
    outstanding = [action for action in required if action not in completed_set]

    return DecommissionVerdict(
        scenario=scenario,
        complete=not outstanding and not refusals,
        outstandingActions=tuple(outstanding),
        refusals=tuple(refusals),
        completedActions=tuple(sorted(completed_set)),
    )


def required_actions(scenario: str) -> tuple[str, ...]:
    """Return the required action set for a scenario."""
    if scenario not in REQUIRED_ACTIONS:
        raise DecommissionError(f"scenario {scenario!r} is not recognised")
    return REQUIRED_ACTIONS[scenario]


def lost_device_response(*, stolen: bool = False) -> dict[str, Any]:
    """Return the documented lost- or stolen-device response sequence."""
    scenario = "stolen-device" if stolen else "lost-device"
    return {
        "scenario": scenario,
        "immediateActions": list(REQUIRED_ACTIONS[scenario]),
        "remoteWipeConstraint": (
            "Remote wipe remains constrained by device ownership and prior policy. A personally owned "
            "device is not fully wiped; the organisation withdraws its own data, applications, and "
            "credentials only."
        ),
        "recoveryGuidance": [
            "Encrypted data on the lost device stays protected by the user's LUKS credentials.",
            "Rotating sync keys prevents the lost device from decrypting objects uploaded after revocation.",
            "Objects the device already downloaded before revocation cannot be retracted; state this plainly.",
        ],
        "auditReportRequired": True,
    }
