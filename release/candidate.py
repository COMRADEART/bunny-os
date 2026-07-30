# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable-candidate prerequisites and the evidence dashboard.

Two things live here because they are two views of one list.

**Prerequisites** are the fourteen conditions a stable candidate must satisfy
before any artifact may be labelled release-qualified. They are machine-readable
and fail closed: an unknown prerequisite state is `BLOCKED`, never `PASS`, and
there is no code path that treats absence as success.

**The dashboard** is the same fourteen plus the wider evidence categories,
rendered with the one thing the previous dashboard lacked: *who can produce this*.
A row that says `BLOCKED` and nothing else invites someone to try harder at it.
A row that says `PENDING_HARDWARE — needs an x86-64 UEFI machine` does not.

The eight states are deliberately more than pass and fail. `BLOCKED`,
`PENDING_EXTERNAL_REVIEW`, `PENDING_OWNER` and `PENDING_HARDWARE` all mean "not
satisfied", and they mean it for four different reasons with four different
resolutions. Collapsing them into one number is how a project spends a month
retrying something that needed a purchase order.

There is deliberately **no aggregate percentage**. "78% complete" reads as nearly
done when the missing 22% contains every blocker that needs a third party.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _datetime
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

STATES = (
    "PASS",
    "FAIL",
    "BLOCKED",
    "NOT_RUN",
    "STALE",
    "PENDING_EXTERNAL_REVIEW",
    "PENDING_OWNER",
    "PENDING_HARDWARE",
)

#: Only this one is satisfied. Everything else blocks, including the four
#: PENDING_* states, which describe *why* rather than softening the result.
SATISFIED_STATES = frozenset({"PASS"})

#: Who can produce a piece of evidence. Naming this per row is the whole point:
#: a third-party requirement misfiled as an engineering task is how a project
#: talks itself into self-reviewing.
OWNERS = (
    "engineering",
    "ci-infrastructure",
    "second-independent-machine",
    "physical-hardware",
    "independent-reviewer",
    "second-authorised-signer",
    "owner-decision",
    "operated-release",
)

#: The fourteen candidate prerequisites, in the brief's order, each with the
#: owner who can satisfy it and the state it defaults to when no evidence exists.
CANDIDATE_PREREQUISITES: tuple[dict[str, str], ...] = (
    {"id": "licence-gate", "description": "Licence gate passed", "owner": "engineering", "absentState": "BLOCKED"},
    {"id": "vulnerability-gate", "description": "Vulnerability gate passed", "owner": "independent-reviewer", "absentState": "PENDING_EXTERNAL_REVIEW"},
    {"id": "independent-reproducibility", "description": "Independent reproducibility passed", "owner": "ci-infrastructure", "absentState": "BLOCKED"},
    {"id": "development-signing-drill", "description": "Development signing drill passed", "owner": "engineering", "absentState": "BLOCKED"},
    {"id": "independent-recovery-media", "description": "Independent recovery media passed", "owner": "engineering", "absentState": "NOT_RUN"},
    {"id": "installation-matrix", "description": "Installation matrix passed", "owner": "engineering", "absentState": "NOT_RUN"},
    {"id": "encryption-matrix", "description": "Encryption matrix passed", "owner": "engineering", "absentState": "NOT_RUN"},
    {"id": "update-matrix", "description": "Update matrix passed", "owner": "operated-release", "absentState": "NOT_RUN"},
    {"id": "rollback-matrix", "description": "Rollback matrix passed", "owner": "operated-release", "absentState": "NOT_RUN"},
    {"id": "physical-hardware-evidence", "description": "Physical hardware evidence passed", "owner": "physical-hardware", "absentState": "PENDING_HARDWARE"},
    {"id": "accessibility-evidence", "description": "Accessibility evidence passed", "owner": "independent-reviewer", "absentState": "PENDING_EXTERNAL_REVIEW"},
    {"id": "independent-reviews", "description": "Independent reviews passed", "owner": "independent-reviewer", "absentState": "PENDING_EXTERNAL_REVIEW"},
    {"id": "second-production-signer", "description": "Second production signer available", "owner": "second-authorised-signer", "absentState": "BLOCKED"},
    {"id": "protected-approvals", "description": "Protected approvals complete", "owner": "owner-decision", "absentState": "PENDING_OWNER"},
)

PREREQUISITE_IDS = tuple(item["id"] for item in CANDIDATE_PREREQUISITES)

#: How long a piece of evidence stays fresh before it must be regenerated. Not a
#: judgement about decay: it is the interval after which nobody can say whether
#: the thing measured is still true.
DEFAULT_MAX_AGE_DAYS = 90


class CandidateError(ValueError):
    """Raised when a prerequisite or dashboard row is malformed."""


@dataclass(frozen=True)
class Row:
    id: str
    description: str
    state: str
    owner: str
    evidence: str
    commit: str
    ageDays: int | None
    blocker: str
    nextAction: str
    dependency: str

    @property
    def satisfied(self) -> bool:
        return self.state in SATISFIED_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "state": self.state,
            "owner": self.owner,
            "evidence": self.evidence,
            "commit": self.commit,
            "ageDays": self.ageDays,
            "blocker": self.blocker,
            "nextAction": self.nextAction,
            "dependency": self.dependency,
            "satisfied": self.satisfied,
        }


def _age_days(generatedAt: str | None, now: _datetime.datetime) -> int | None:
    if not generatedAt:
        return None
    try:
        stamp = _datetime.datetime.fromisoformat(str(generatedAt).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_datetime.timezone.utc)
    return max(0, (now - stamp).days)


def build_row(
    definition: Mapping[str, str],
    observation: Mapping[str, Any],
    *,
    sourceCommit: str,
    now: _datetime.datetime,
    maxAgeDays: int = DEFAULT_MAX_AGE_DAYS,
) -> Row:
    """Turn one prerequisite definition plus one observation into a row.

    Staleness and wrong-commit are applied *after* the observed state, so a
    passing check whose evidence is six months old or generated from another
    commit reports `STALE` rather than `PASS`. Both are silent failures otherwise:
    the check passed, once, somewhere.
    """
    satisfied = bool(observation.get("satisfied", False))
    state = str(observation.get("state") or ("PASS" if satisfied else definition["absentState"]))
    if state not in STATES:
        raise CandidateError(f"{definition['id']}: state must be one of {', '.join(STATES)}")

    evidence = str(observation.get("evidence") or "none recorded")
    commit = str(observation.get("commit") or "")
    age = _age_days(observation.get("generatedAt"), now)

    if state == "PASS":
        if commit and sourceCommit and commit != sourceCommit:
            state = "STALE"
            evidence += f" (generated from {commit[:12]}, candidate is {sourceCommit[:12]})"
        elif age is not None and age > maxAgeDays:
            state = "STALE"
            evidence += f" (generated {age} days ago; the freshness limit is {maxAgeDays})"

    return Row(
        id=str(definition["id"]),
        description=str(definition["description"]),
        state=state,
        owner=str(observation.get("owner") or definition["owner"]),
        evidence=evidence,
        commit=commit or "unbound",
        ageDays=age,
        blocker="none" if state in SATISFIED_STATES else str(observation.get("blocker") or state),
        nextAction=str(observation.get("nextAction") or _default_next_action(definition, state)),
        dependency=str(observation.get("dependency") or "none"),
    )


def _default_next_action(definition: Mapping[str, str], state: str) -> str:
    owner = definition["owner"]
    if state in SATISFIED_STATES:
        return "none"
    return {
        "engineering": "run the check and commit the evidence",
        "ci-infrastructure": "execute .github/workflows/independent-builder.yml against this commit",
        "second-independent-machine": "run a build on a separately administered machine",
        "physical-hardware": "acquire one x86-64 UEFI machine with Secure Boot and TPM 2.0",
        "independent-reviewer": "commission the review; see the matching reviews/*/REQUEST.md",
        "second-authorised-signer": "identify a second signer and hold a key ceremony",
        "owner-decision": "the owner must decide; this is not an engineering task",
        "operated-release": "publish a release, then measure against it",
    }.get(owner, "unassigned")


@dataclass(frozen=True)
class CandidateReadiness:
    sourceCommit: str
    rows: tuple[Row, ...]
    evaluatedAt: str

    @property
    def unsatisfied(self) -> tuple[Row, ...]:
        return tuple(row for row in self.rows if not row.satisfied)

    @property
    def ready(self) -> bool:
        return not self.unsatisfied and len(self.rows) == len(CANDIDATE_PREREQUISITES)

    def as_dict(self) -> dict[str, Any]:
        by_state: dict[str, list[str]] = {name: [] for name in STATES}
        by_owner: dict[str, list[str]] = {name: [] for name in OWNERS}
        for row in self.rows:
            by_state[row.state].append(row.id)
            by_owner.setdefault(row.owner, []).append(row.id)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sourceCommit": self.sourceCommit,
            "evaluatedAt": self.evaluatedAt,
            "prerequisiteCount": len(CANDIDATE_PREREQUISITES),
            "rows": [row.as_dict() for row in self.rows],
            "satisfied": [row.id for row in self.rows if row.satisfied],
            "unsatisfied": [row.id for row in self.unsatisfied],
            "byState": {name: sorted(values) for name, values in by_state.items() if values},
            "byOwner": {name: sorted(values) for name, values in by_owner.items() if values},
            "ready": self.ready,
            "result": "PASS" if self.ready else "BLOCKED",
            "candidateLabelPermitted": self.ready,
            "note": (
                "No artifact may be labelled release-qualified while any prerequisite is "
                "unsatisfied. There is no aggregate percentage here on purpose: a completion "
                "figure reads as nearly done when what remains needs a third party."
            ),
        }


def evaluate_candidate(
    observations: Mapping[str, Mapping[str, Any]],
    *,
    sourceCommit: str,
    now: _datetime.datetime,
    maxAgeDays: int = DEFAULT_MAX_AGE_DAYS,
) -> CandidateReadiness:
    """Evaluate all fourteen prerequisites.

    An observation absent from ``observations`` is not an error: it takes the
    prerequisite's ``absentState``, which is never ``PASS``. That is the
    fail-closed property, and it means adding a prerequisite cannot accidentally
    make a candidate pass.
    """
    unknown = sorted(set(observations) - set(PREREQUISITE_IDS))
    if unknown:
        raise CandidateError(f"unknown prerequisites declared: {', '.join(unknown)}")

    rows = tuple(
        build_row(
            definition,
            observations.get(definition["id"], {}),
            sourceCommit=sourceCommit,
            now=now,
            maxAgeDays=maxAgeDays,
        )
        for definition in CANDIDATE_PREREQUISITES
    )
    return CandidateReadiness(
        sourceCommit=sourceCommit,
        rows=rows,
        evaluatedAt=now.isoformat().replace("+00:00", "Z"),
    )


def render_dashboard(readiness: CandidateReadiness, *, extraRows: Iterable[Row] = ()) -> str:
    """Render the dashboard as Markdown, one row per requirement."""
    rows = list(readiness.rows) + list(extraRows)
    lines = [
        "# Stable evidence dashboard",
        "",
        f"Source commit: `{readiness.sourceCommit}`  ",
        f"Evaluated at: {readiness.evaluatedAt}",
        "",
        f"**{len(readiness.rows) - len(readiness.unsatisfied)} of {len(readiness.rows)} candidate "
        f"prerequisites satisfied. Candidate label permitted: "
        f"{'yes' if readiness.ready else 'NO'}.**",
        "",
        "No aggregate percentage is shown. A completion figure hides which blockers need a third",
        "party, and those are the ones that determine the date.",
        "",
        "| Requirement | State | Owner | Evidence | Commit | Age (days) | Blocker | Next action | Dependency |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        age = "—" if row.ageDays is None else str(row.ageDays)
        commit = row.commit[:12] if row.commit != "unbound" else "unbound"
        lines.append(
            f"| {row.description} | **{row.state}** | {row.owner} | {row.evidence} | `{commit}` | "
            f"{age} | {row.blocker} | {row.nextAction} | {row.dependency} |"
        )

    lines.extend(["", "## States", ""])
    lines.extend(
        [
            "| State | Meaning | Satisfies a gate |",
            "|---|---|---|",
            "| `PASS` | measured, current, and bound to this commit | **yes** |",
            "| `FAIL` | measured and negative | no |",
            "| `BLOCKED` | cannot be measured yet; a dependency is unmet | no |",
            "| `NOT_RUN` | nobody has run it | no |",
            "| `STALE` | it passed, but at another commit or too long ago | no |",
            "| `PENDING_EXTERNAL_REVIEW` | needs an identified external party | no |",
            "| `PENDING_OWNER` | needs a decision that is not an engineering decision | no |",
            "| `PENDING_HARDWARE` | needs a physical device | no |",
            "",
            "Only `PASS` satisfies anything. The four `PENDING_*` states are not softer than",
            "`BLOCKED`; they name who can resolve it.",
            "",
        ]
    )
    return "\n".join(lines)


def load_observations(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = document.get("prerequisites")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise CandidateError("prerequisites must be an object keyed by prerequisite id")
    return {str(key): dict(value) for key, value in raw.items()}


__all__ = [
    "CANDIDATE_PREREQUISITES",
    "DEFAULT_MAX_AGE_DAYS",
    "OWNERS",
    "PREREQUISITE_IDS",
    "SATISFIED_STATES",
    "STATES",
    "CandidateError",
    "CandidateReadiness",
    "Row",
    "build_row",
    "evaluate_candidate",
    "load_observations",
    "render_dashboard",
]
