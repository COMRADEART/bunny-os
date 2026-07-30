# SPDX-License-Identifier: Apache-2.0
"""Fleet grouping, update rings, and update-state reporting.

Rings sit *above* the existing update channel rather than replacing it. The
update manifest schema keeps its closed three-value ``channel`` enum and its
mandatory Ed25519 verification; a ring only decides *when* a device is offered an
already-signed manifest, and to what fraction of the group. That separation is
deliberate: an organisation gains scheduling control without gaining any
influence over trust.

Signature verification is not a ring setting. There is no representable ring
configuration that disables it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1

#: Dimensions a fleet may be organised by. All are properties of a device or its
#: deployment, never of a person.
GROUP_DIMENSIONS = (
    "organisation",
    "site",
    "department",
    "device-purpose",
    "hardware-family",
    "update-ring",
    "risk-group",
    "support-group",
)

#: Group attributes that would turn fleet structure into behavioural profiling.
#: Rejected by name so the intent is visible in review.
PROHIBITED_GROUP_ATTRIBUTES = frozenset({
    "productivityscore", "activityscore", "engagementscore", "usagehours", "activehours",
    "idletime", "keystrokecount", "attendance", "performancerating", "loginfrequency",
    "applicationusage", "websitesvisited", "promptcount", "aiusage", "employeerating",
})

UPDATE_RINGS = ("internal-test", "early-validation", "general-deployment", "deferred", "emergency")

#: Ring ordering for promotion. A build may not skip from internal test straight
#: to general deployment without passing through early validation.
RING_PROMOTION_ORDER = ("internal-test", "early-validation", "general-deployment")

#: Operational update states. This is the complete reportable vocabulary.
UPDATE_STATES = (
    "not-offered",
    "offered",
    "downloading",
    "staged",
    "restart-required",
    "healthy",
    "failed",
    "rolled-back",
    "deferred",
)

#: Fields that would record what a person was doing when an update ran.
PROHIBITED_UPDATE_CONTEXT = frozenset({
    "activeapplication", "foregroundwindow", "openfiles", "opendocuments", "currenttask",
    "userpresent", "wasworking", "interruptedwork", "promptinflight", "conversationid",
    "screenshot", "windowtitle", "browsertab", "terminalcommand",
})

_GROUP_ID = re.compile(r"^grp-[a-z0-9][a-z0-9-]{1,62}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_TIME_OF_DAY = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class FleetError(ValueError):
    """Raised when a group, ring, or update record violates an invariant."""


def _folded(key: str) -> str:
    return key.replace("_", "").replace("-", "").casefold()


@dataclass(frozen=True)
class FleetGroup:
    groupId: str
    dimension: str
    name: str
    parentGroupId: str | None
    deviceCount: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "groupId": self.groupId,
            "dimension": self.dimension,
            "name": self.name,
            "parentGroupId": self.parentGroupId,
            "deviceCount": self.deviceCount,
        }


def parse_group(record: Mapping[str, Any]) -> FleetGroup:
    """Validate a fleet group definition."""
    if not isinstance(record, Mapping):
        raise FleetError("group must be a mapping")

    allowed = {"schemaVersion", "groupId", "dimension", "name", "parentGroupId", "deviceCount", "attributes"}
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise FleetError("unknown group fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise FleetError("unsupported group schemaVersion")

    group_id = record.get("groupId")
    if not isinstance(group_id, str) or not _GROUP_ID.match(group_id):
        raise FleetError("groupId must match grp-<slug>")

    dimension = record.get("dimension")
    if dimension not in GROUP_DIMENSIONS:
        raise FleetError(f"dimension {dimension!r} is not a recognised grouping dimension")

    name = record.get("name")
    if not isinstance(name, str) or not name:
        raise FleetError("name must be a non-empty string")

    parent = record.get("parentGroupId")
    if parent is not None and (not isinstance(parent, str) or not _GROUP_ID.match(parent)):
        raise FleetError("parentGroupId must match grp-<slug> when present")
    if parent == group_id:
        raise FleetError("a group cannot be its own parent")

    count = record.get("deviceCount", 0)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise FleetError("deviceCount must be a non-negative whole number")

    attributes = record.get("attributes")
    if attributes is not None:
        if not isinstance(attributes, Mapping):
            raise FleetError("attributes must be an object")
        offending = sorted(key for key in attributes if _folded(str(key)) in PROHIBITED_GROUP_ATTRIBUTES)
        if offending:
            raise FleetError(
                "group attributes must not describe personal behaviour: " + ", ".join(offending)
            )

    return FleetGroup(
        groupId=group_id,
        dimension=dimension,
        name=name,
        parentGroupId=parent,
        deviceCount=count,
    )


@dataclass(frozen=True)
class RingConfiguration:
    ring: str
    rolloutPercentage: int
    hardwareExclusions: tuple[str, ...]
    deadline: str | None
    paused: bool
    withdrawn: bool
    maintenanceWindow: dict[str, str] | None
    requireAcPower: bool
    rebootReminderHours: int
    forcedRestart: bool
    signatureVerificationRequired: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ring": self.ring,
            "rolloutPercentage": self.rolloutPercentage,
            "hardwareExclusions": list(self.hardwareExclusions),
            "deadline": self.deadline,
            "paused": self.paused,
            "withdrawn": self.withdrawn,
            "maintenanceWindow": dict(self.maintenanceWindow) if self.maintenanceWindow else None,
            "requireAcPower": self.requireAcPower,
            "rebootReminderHours": self.rebootReminderHours,
            "forcedRestart": self.forcedRestart,
            "signatureVerificationRequired": self.signatureVerificationRequired,
        }


def parse_ring(record: Mapping[str, Any]) -> RingConfiguration:
    """Validate an update-ring configuration.

    ``signatureVerificationRequired`` must be absent or ``true``. Supplying
    ``false`` is a rejection rather than a setting, which is what makes stable
    signature verification non-negotiable at the fleet layer.
    """
    if not isinstance(record, Mapping):
        raise FleetError("ring configuration must be a mapping")

    allowed = {
        "schemaVersion", "ring", "rolloutPercentage", "hardwareExclusions", "deadline", "paused",
        "withdrawn", "maintenanceWindow", "requireAcPower", "rebootReminderHours", "forcedRestart",
        "forcedRestartPolicyReference", "signatureVerificationRequired",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise FleetError("unknown ring fields: " + ", ".join(unexpected))
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise FleetError("unsupported ring schemaVersion")

    ring = record.get("ring")
    if ring not in UPDATE_RINGS:
        raise FleetError(f"ring {ring!r} is not a recognised update ring")

    if "signatureVerificationRequired" in record and record["signatureVerificationRequired"] is not True:
        raise FleetError(
            "signatureVerificationRequired cannot be disabled; stable OS signature verification is mandatory "
            "and is not a fleet-configurable setting"
        )

    percentage = record.get("rolloutPercentage", 100)
    if not isinstance(percentage, int) or isinstance(percentage, bool) or not 0 <= percentage <= 100:
        raise FleetError("rolloutPercentage must be a whole number between 0 and 100")

    exclusions = record.get("hardwareExclusions", [])
    if not isinstance(exclusions, list) or any(not isinstance(item, str) or not item for item in exclusions):
        raise FleetError("hardwareExclusions must be a list of non-empty strings")

    deadline = record.get("deadline")
    if deadline is not None and (not isinstance(deadline, str) or not _RFC3339.match(deadline)):
        raise FleetError("deadline must be an RFC 3339 timestamp when present")

    paused = record.get("paused", False)
    withdrawn = record.get("withdrawn", False)
    for name, value in (("paused", paused), ("withdrawn", withdrawn)):
        if not isinstance(value, bool):
            raise FleetError(f"{name} must be a boolean")
    if withdrawn and percentage > 0:
        raise FleetError("a withdrawn update must have rolloutPercentage 0")

    window = record.get("maintenanceWindow")
    if window is not None:
        if not isinstance(window, Mapping) or set(window) != {"start", "end"}:
            raise FleetError("maintenanceWindow requires exactly start and end")
        for key in ("start", "end"):
            if not isinstance(window[key], str) or not _TIME_OF_DAY.match(window[key]):
                raise FleetError(f"maintenanceWindow.{key} must be HH:MM")

    require_ac = record.get("requireAcPower", False)
    if not isinstance(require_ac, bool):
        raise FleetError("requireAcPower must be a boolean")

    reminder = record.get("rebootReminderHours", 24)
    if not isinstance(reminder, int) or isinstance(reminder, bool) or not 1 <= reminder <= 168:
        raise FleetError("rebootReminderHours must be between 1 and 168")

    forced = record.get("forcedRestart", False)
    if not isinstance(forced, bool):
        raise FleetError("forcedRestart must be a boolean")
    if forced and not record.get("forcedRestartPolicyReference"):
        raise FleetError(
            "forcedRestart requires forcedRestartPolicyReference naming the explicit organisation policy that permits it"
        )
    if forced and ring == "deferred":
        raise FleetError("a deferred ring cannot force a restart")

    return RingConfiguration(
        ring=ring,
        rolloutPercentage=percentage,
        hardwareExclusions=tuple(exclusions),
        deadline=deadline,
        paused=paused,
        withdrawn=withdrawn,
        maintenanceWindow=dict(window) if window else None,
        requireAcPower=require_ac,
        rebootReminderHours=reminder,
        forcedRestart=forced,
        signatureVerificationRequired=True,
    )


def assert_promotion_permitted(from_ring: str, to_ring: str) -> None:
    """Refuse a ring promotion that skips a validation stage."""
    if from_ring not in UPDATE_RINGS or to_ring not in UPDATE_RINGS:
        raise FleetError("both rings must be recognised update rings")
    if to_ring == "emergency":
        return
    if from_ring not in RING_PROMOTION_ORDER or to_ring not in RING_PROMOTION_ORDER:
        return
    source = RING_PROMOTION_ORDER.index(from_ring)
    target = RING_PROMOTION_ORDER.index(to_ring)
    if target > source + 1:
        raise FleetError(
            f"promotion from {from_ring} to {to_ring} skips "
            f"{RING_PROMOTION_ORDER[source + 1]}; rings are promoted in order"
        )


def parse_update_state(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a per-device update state report.

    Refuses any field describing what the user was doing, and refuses a
    ``rolled-back`` report that does not preserve the previous deployment
    reference — a failed fleet update must leave rollback intact.
    """
    if not isinstance(record, Mapping):
        raise FleetError("update state must be a mapping")

    # The behavioural-field scan runs before the unknown-field check so that an
    # attempt to report user activity produces a specific privacy refusal rather
    # than a generic "unknown field" message.
    offending = sorted(key for key in record if _folded(str(key)) in PROHIBITED_UPDATE_CONTEXT)
    if offending:
        raise FleetError(
            "update state must not record user activity context: " + ", ".join(offending)
        )

    allowed = {
        "schemaVersion", "state", "targetVersion", "previousVersion", "ring",
        "attempts", "lastChangedAt", "failureCode", "rollbackAvailable",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise FleetError("unknown update state fields: " + ", ".join(unexpected))

    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise FleetError("unsupported update state schemaVersion")

    state = record.get("state")
    if state not in UPDATE_STATES:
        raise FleetError(f"state {state!r} is not a recognised operational update state")

    ring = record.get("ring")
    if ring is not None and ring not in UPDATE_RINGS:
        raise FleetError(f"ring {ring!r} is not recognised")

    attempts = record.get("attempts", 0)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
        raise FleetError("attempts must be a non-negative whole number")

    changed_at = record.get("lastChangedAt")
    if changed_at is not None and (not isinstance(changed_at, str) or not _RFC3339.match(changed_at)):
        raise FleetError("lastChangedAt must be an RFC 3339 timestamp when present")

    if state in {"failed", "rolled-back"}:
        if record.get("rollbackAvailable") is not True:
            raise FleetError(
                f"a {state} update must report rollbackAvailable true; "
                "a failed fleet update must preserve the previous deployment"
            )
        if not record.get("previousVersion"):
            raise FleetError(f"a {state} update must name the previousVersion that remains selectable")

    return dict(record)


def eligible_device_count(total: int, configuration: RingConfiguration) -> int:
    """Return how many devices in a group may be offered the update now."""
    if total < 0:
        raise FleetError("total must be non-negative")
    if configuration.paused or configuration.withdrawn:
        return 0
    return (total * configuration.rolloutPercentage) // 100
