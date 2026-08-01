# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builder identity, and what makes two builders independent rather than separate.

``release.reproducibility`` keeps the four reproducibility *claims* apart. This
module answers the prior question those claims depend on: were there actually
two builders?

The previous phase learned the answer the hard way. Two isolated workspaces on
one WSL2 instance produced byte-identical archives, and the comparison correctly
refused to call that independent-builder reproducibility, because the two
records differed only in ``environmentId``. A schema that treats "different
directory" as a trust boundary invites exactly that mistake, so this schema does
not have a field a second directory can move.

The model is a **boundary**, not an identifier. ``administratorBoundary`` names
who can change the builder; ``builderType`` names what kind of execution
environment it is. Independence is then a property of a *pair*: two records are
independent when they form one of four accepted pairings and satisfy that
pairing's extra condition. Anything else is refused with the reason stated.

Explicitly insufficient, and each is tested:

* a different temporary path;
* a different workspace identifier;
* a different environment variable;
* two directories on the same host;
* two containers under the same daemon;
* two consecutive builds by the same runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA_VERSION = 2

BUILDER_TYPES = (
    "local-machine",
    "hosted-ci",
    "self-hosted-ci",
    "cloud-vm",
    "physical-builder",
)

#: A builder type that runs under someone else's administration must say which
#: run produced it. Without a run identifier a "hosted CI build" is an assertion.
_RUN_ID_REQUIRED = frozenset({"hosted-ci", "self-hosted-ci"})

#: The accepted independence pairings, each with the additional condition that
#: makes the pairing meaningful. The condition matters as much as the pairing:
#: two cloud VMs at one provider share a hypervisor and an operator, and two
#: physical builders in one cupboard share an administrator.
ACCEPTED_PAIRINGS: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"local-machine", "hosted-ci"}),
        "distinctAdministrator",
        "a local physical builder paired with hosted CI",
    ),
    (
        frozenset({"physical-builder", "hosted-ci"}),
        "distinctAdministrator",
        "a physical builder paired with hosted CI",
    ),
    (
        frozenset({"physical-builder"}),
        "distinctAdministrator",
        "two separately administered physical builders",
    ),
    (
        frozenset({"cloud-vm"}),
        "distinctCloudProvider",
        "two independent cloud providers",
    ),
    (
        frozenset({"hosted-ci", "self-hosted-ci"}),
        "distinctAdministrator",
        "hosted CI paired with a separately administered self-hosted runner",
    ),
)

#: Fields that must be identical between two builders of the same artifact.
#: Comparing builds of different inputs establishes nothing at all.
SHARED_INPUT_FIELDS = ("sourceCommit", "baseImageDigest")

#: Record fields whose difference is *not* independence, used to name what a
#: refused pair actually differed in.
WEAK_DIMENSIONS = ("environmentId", "buildStartedAt", "buildCompletedAt")

#: What the brief names as insufficient, including things this schema has no
#: field for. The absence is deliberate: schema 1 carried a ``workspace`` path,
#: and a schema with a field for the workspace invites a comparison that treats
#: two directories as two builders. Schema 2 has nowhere to put one.
INSUFFICIENT_FOR_INDEPENDENCE = (
    "a different temporary path",
    "a different workspace identifier",
    "a different environment variable",
    "two directories on the same host",
    "two containers under the same daemon",
    "two consecutive builds by the same runner",
)

_REQUIRED_FIELDS = (
    "schemaVersion",
    "builderId",
    "environmentId",
    "sourceCommit",
    "baseImageDigest",
    "architecture",
    "operatingSystem",
    "kernelVersion",
    "builderType",
    "administratorBoundary",
    "buildStartedAt",
    "buildCompletedAt",
    "toolchain",
)

_DIGEST_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class BuilderError(ValueError):
    """Raised when a builder record is malformed, or overclaims independence."""


def _timestamp(value: str, *, field: str, builder: str) -> _datetime.datetime:
    try:
        return _datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise BuilderError(f"{builder}: {field} must be an RFC 3339 timestamp") from None


@dataclass(frozen=True)
class BuilderRecord:
    """One builder's identity, as recorded by the builder itself."""

    schemaVersion: int
    builderId: str
    environmentId: str
    sourceCommit: str
    baseImageDigest: str
    architecture: str
    operatingSystem: str
    kernelVersion: str
    builderType: str
    administratorBoundary: str
    buildStartedAt: str
    buildCompletedAt: str
    toolchain: Mapping[str, str]
    cloudProvider: str | None = None
    cloudRunner: str | None = None
    workflowRunId: str | None = None
    dependencyLockHashes: Mapping[str, str] | None = None

    @property
    def buildDurationSeconds(self) -> float:
        started = _datetime.datetime.fromisoformat(self.buildStartedAt.replace("Z", "+00:00"))
        completed = _datetime.datetime.fromisoformat(self.buildCompletedAt.replace("Z", "+00:00"))
        return (completed - started).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "builderId": self.builderId,
            "environmentId": self.environmentId,
            "sourceCommit": self.sourceCommit,
            "baseImageDigest": self.baseImageDigest,
            "architecture": self.architecture,
            "operatingSystem": self.operatingSystem,
            "kernelVersion": self.kernelVersion,
            "builderType": self.builderType,
            "cloudProvider": self.cloudProvider,
            "cloudRunner": self.cloudRunner,
            "workflowRunId": self.workflowRunId,
            "administratorBoundary": self.administratorBoundary,
            "buildStartedAt": self.buildStartedAt,
            "buildCompletedAt": self.buildCompletedAt,
            "toolchain": dict(self.toolchain),
            "dependencyLockHashes": dict(self.dependencyLockHashes or {}),
        }

    def identityFingerprint(self) -> tuple[Any, ...]:
        """Everything except the builder's own name.

        Two records that agree on all of this are one record with two names,
        which is the ``copied builder records`` adversarial case.
        """
        return (
            self.environmentId,
            self.builderType,
            self.administratorBoundary,
            self.cloudProvider,
            self.cloudRunner,
            self.workflowRunId,
            self.kernelVersion,
            self.operatingSystem,
            self.architecture,
            self.buildStartedAt,
            self.buildCompletedAt,
        )


def parse_builder_record(record: Mapping[str, Any]) -> BuilderRecord:
    """Validate one builder record. Fails closed on anything ambiguous."""
    if not isinstance(record, Mapping):
        raise BuilderError("builder record must be an object")

    identifier = str(record.get("builderId") or "<unnamed>")

    missing = [name for name in _REQUIRED_FIELDS if record.get(name) in (None, "", {})]
    if missing:
        # Named individually because "missing administrator boundary" and
        # "missing source commit" are two of the mandated rejection cases and a
        # generic message would not distinguish them.
        raise BuilderError(f"{identifier}: builder record missing fields: {', '.join(sorted(missing))}")

    if int(record["schemaVersion"]) != SCHEMA_VERSION:
        raise BuilderError(
            f"{identifier}: builder record schemaVersion must be {SCHEMA_VERSION}; "
            f"got {record['schemaVersion']!r}"
        )

    builder_type = str(record["builderType"])
    if builder_type not in BUILDER_TYPES:
        raise BuilderError(f"{identifier}: builderType must be one of {', '.join(BUILDER_TYPES)}")

    commit = str(record["sourceCommit"])
    if not _COMMIT.match(commit):
        raise BuilderError(
            f"{identifier}: sourceCommit must be a full 40-character SHA; a branch name or short "
            "SHA does not pin a build"
        )

    base = str(record["baseImageDigest"])
    if not _DIGEST_PINNED.search(base):
        # A mutable tag is the failure this check exists for: two builders can
        # both pull `:44` and get different bases, and the comparison would
        # attribute the difference to the build.
        raise BuilderError(
            f"{identifier}: baseImageDigest {base!r} is not digest-pinned. A mutable tag does not "
            "identify a base image; both builders must pin the same name@sha256:<64 hex>"
        )

    toolchain = record["toolchain"]
    if not isinstance(toolchain, Mapping) or not toolchain:
        raise BuilderError(f"{identifier}: toolchain must record the versions of the tools used")

    started = _timestamp(record["buildStartedAt"], field="buildStartedAt", builder=identifier)
    completed = _timestamp(record["buildCompletedAt"], field="buildCompletedAt", builder=identifier)
    if completed < started:
        raise BuilderError(f"{identifier}: buildCompletedAt precedes buildStartedAt")

    run_id = record.get("workflowRunId")
    if builder_type in _RUN_ID_REQUIRED and not run_id:
        raise BuilderError(
            f"{identifier}: a {builder_type} builder must record workflowRunId; without a run "
            "identifier the build cannot be traced to a run and the record is an assertion"
        )
    if builder_type == "cloud-vm" and not record.get("cloudProvider"):
        raise BuilderError(
            f"{identifier}: a cloud-vm builder must record cloudProvider; two VMs at one provider "
            "share a hypervisor and an operator and are not independent"
        )

    lock_hashes = record.get("dependencyLockHashes")
    if lock_hashes is not None and not isinstance(lock_hashes, Mapping):
        raise BuilderError(f"{identifier}: dependencyLockHashes must be an object")

    return BuilderRecord(
        schemaVersion=SCHEMA_VERSION,
        builderId=str(record["builderId"]),
        environmentId=str(record["environmentId"]),
        sourceCommit=commit,
        baseImageDigest=base,
        architecture=str(record["architecture"]),
        operatingSystem=str(record["operatingSystem"]),
        kernelVersion=str(record["kernelVersion"]),
        builderType=builder_type,
        administratorBoundary=str(record["administratorBoundary"]),
        buildStartedAt=str(record["buildStartedAt"]),
        buildCompletedAt=str(record["buildCompletedAt"]),
        toolchain={str(k): str(v) for k, v in toolchain.items()},
        cloudProvider=str(record["cloudProvider"]) if record.get("cloudProvider") else None,
        cloudRunner=str(record["cloudRunner"]) if record.get("cloudRunner") else None,
        workflowRunId=str(run_id) if run_id else None,
        dependencyLockHashes={str(k): str(v) for k, v in (lock_hashes or {}).items()} or None,
    )


@dataclass(frozen=True)
class IndependenceVerdict:
    first: str
    second: str
    pairing: str | None
    independent: bool
    sharedInputs: tuple[str, ...]
    mismatchedInputs: tuple[str, ...]
    reasons: tuple[str, ...]
    recorded: Mapping[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "first": self.first,
            "second": self.second,
            "pairing": self.pairing,
            "independent": self.independent,
            "sharedInputs": list(self.sharedInputs),
            "mismatchedInputs": list(self.mismatchedInputs),
            "recorded": dict(self.recorded),
            "reasons": list(self.reasons),
            "result": "PASS" if self.independent else "BLOCKED",
            "note": (
                "Independence is a property of the pair, not of either record. A second workspace, "
                "container, or consecutive run on one host is separation, not independence."
            ),
        }


def _matching_pairing(first: BuilderRecord, second: BuilderRecord) -> tuple[str, str] | None:
    types = frozenset({first.builderType, second.builderType})
    for accepted, condition, description in ACCEPTED_PAIRINGS:
        if accepted == types:
            return condition, description
    return None


def evaluate_independence(
    first: BuilderRecord,
    second: BuilderRecord,
    *,
    toolClassifications: Mapping[str, str] | None = None,
) -> IndependenceVerdict:
    """Decide whether these two records describe two independent builders.

    Tool-version differences are adjudicated by the classification model in
    ``release/supplychain.py`` rather than by blanket string equality. An
    earlier version of this function refused any pair whose recorded versions
    differed for any tool it happened to share, which pinned the machine
    instead of the build: grype and image-builder never touch the archive, and
    the honest question — could this difference have put different bytes in
    the artifact? — is exactly what the per-tool classifications answer, with
    a declared class, a reason and a test each. ``unknown`` still blocks: a
    difference in a tool nobody classified is a difference nobody has
    established to be harmless, so a caller that passes no classifications
    keeps the old strict behaviour.
    """
    from release.supplychain import toolchain_mismatches

    reasons: list[str] = []

    # --- inputs that must be identical -------------------------------------
    mismatched = tuple(
        name for name in SHARED_INPUT_FIELDS if getattr(first, name) != getattr(second, name)
    )
    blocking, recorded_only, unclassified = toolchain_mismatches(
        first.toolchain, second.toolchain, classifications=dict(toolClassifications or {})
    )
    toolchain_mismatch = tuple(f"toolchain.{tool}" for tool in (*blocking, *unclassified))
    if mismatched:
        reasons.append(
            "the builders did not build the same thing: " + ", ".join(mismatched) + " differ"
        )
    if blocking:
        reasons.append(
            "toolchain versions differ: "
            + ", ".join(f"toolchain.{tool}" for tool in blocking)
            + "; a content difference could not be attributed to the environment"
        )
    if unclassified:
        reasons.append(
            "toolchain versions differ in unclassified tools: "
            + ", ".join(f"toolchain.{tool}" for tool in unclassified)
            + "; a tool whose effect on the artifact nobody has established cannot be assumed "
            "to have none"
        )

    if first.builderId == second.builderId:
        reasons.append("both records carry the same builderId; one builder is not two builders")

    # --- the copied record -------------------------------------------------
    if first.identityFingerprint() == second.identityFingerprint():
        reasons.append(
            "the two records are identical in every field except builderId; a copied builder "
            "record is one build recorded twice"
        )

    # --- the reused run ----------------------------------------------------
    if first.workflowRunId and first.workflowRunId == second.workflowRunId:
        reasons.append(
            f"both records cite workflow run {first.workflowRunId}; two jobs in one workflow run "
            "share the run's checkout, cache and administrator"
        )
    if first.cloudRunner and first.cloudRunner == second.cloudRunner:
        reasons.append(
            f"both records cite runner {first.cloudRunner}; two consecutive builds by one runner "
            "are repeatability, not independence"
        )

    # --- the disguised host ------------------------------------------------
    if first.administratorBoundary == second.administratorBoundary:
        differing = [
            name for name in WEAK_DIMENSIONS if getattr(first, name) != getattr(second, name)
        ]
        detail = ", ".join(differing) if differing else "nothing"
        reasons.append(
            "both builders share administratorBoundary "
            f"{first.administratorBoundary!r} and differ only in {detail}. A different workspace, "
            "temporary path, environment identifier or container under the same daemon is "
            "environment separation on one host: a defect in the shared kernel, storage or clock "
            "reproduces in both builds and the comparison cannot detect it"
        )

    # --- the pairing -------------------------------------------------------
    pairing = _matching_pairing(first, second)
    description: str | None = None
    if pairing is None:
        reasons.append(
            f"builderType pair ({first.builderType}, {second.builderType}) is not an accepted "
            "independence pairing. Accepted: "
            + "; ".join(text for _, _, text in ACCEPTED_PAIRINGS)
        )
    else:
        condition, description = pairing
        if condition == "distinctCloudProvider" and first.cloudProvider == second.cloudProvider:
            reasons.append(
                f"both cloud builders run at {first.cloudProvider!r}; two independent cloud "
                "providers are required, not two instances at one provider"
            )

    return IndependenceVerdict(
        first=first.builderId,
        second=second.builderId,
        pairing=description,
        independent=not reasons,
        sharedInputs=tuple(name for name in SHARED_INPUT_FIELDS if name not in mismatched),
        mismatchedInputs=mismatched + toolchain_mismatch,
        reasons=tuple(reasons),
        recorded={
            # The six things the brief requires a comparison to record. Each is
            # a measurement, reported whether or not the verdict passes.
            "sourceCommitEquality": first.sourceCommit == second.sourceCommit,
            "baseDigestEquality": first.baseImageDigest == second.baseImageDigest,
            "configurationEquality": not mismatched,
            "toolchainEquality": not toolchain_mismatch,
            # Differences the classifications permit, reported rather than
            # silently tolerated: the verdict says what differed and why that
            # was allowed to stand.
            "toolchainRecordedOnlyDifferences": list(recorded_only),
            "environmentIndependence": first.administratorBoundary != second.administratorBoundary,
            "artifactComparisonAvailable": False,
        },
    )


def evaluate_builder_set(
    document: Mapping[str, Any],
    *,
    toolClassifications: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate every declared builder pair in ``operations/data/builders.json``."""
    raw = document.get("builderRecords")
    if not isinstance(raw, list):
        raise BuilderError("builder document must carry a builderRecords array")
    pairs = document.get("independencePairs")
    if not isinstance(pairs, list):
        raise BuilderError("builder document must carry an independencePairs array")

    records: dict[str, BuilderRecord] = {}
    rejected: list[str] = []
    for item in raw:
        try:
            record = parse_builder_record(item)
        except BuilderError as exc:
            rejected.append(str(exc))
            continue
        if record.builderId in records:
            rejected.append(f"{record.builderId}: duplicate builderId")
            continue
        records[record.builderId] = record

    verdicts: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, Mapping):
            rejected.append("independence pair must be an object")
            continue
        left, right = pair.get("first"), pair.get("second")
        if left not in records or right not in records:
            missing = [name for name in (left, right) if name not in records]
            rejected.append(f"pair references unknown builder(s): {', '.join(map(str, missing))}")
            continue
        verdict = evaluate_independence(
            records[left], records[right], toolClassifications=toolClassifications
        )
        verdicts.append(verdict.as_dict())

    independent = [v for v in verdicts if v["independent"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "builderCount": len(records),
        "builderTypes": sorted({record.builderType for record in records.values()}),
        "rejected": rejected,
        "pairs": verdicts,
        "independentPairCount": len(independent),
        "requirementMet": bool(independent) and not rejected,
        "result": "PASS" if independent and not rejected else "BLOCKED",
        "note": (
            "At least one accepted independence pairing must be verified from real environment "
            "evidence. A rejected record blocks even when another pair passes: a record the model "
            "refuses is evidence the collection is not trustworthy."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "ACCEPTED_PAIRINGS",
    "BUILDER_TYPES",
    "INSUFFICIENT_FOR_INDEPENDENCE",
    "SHARED_INPUT_FIELDS",
    "WEAK_DIMENSIONS",
    "BuilderError",
    "BuilderRecord",
    "IndependenceVerdict",
    "evaluate_builder_set",
    "evaluate_independence",
    "parse_builder_record",
]
