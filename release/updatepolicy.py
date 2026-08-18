# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The unsupported-update policy, and what it takes for one to count.

§10 of the Phase 6 brief allows a project to declare updates unsupported for a
release class rather than implement an update trust architecture. §19's seventh
blocking condition then permits the update matrix to stay unexecuted, but only
behind *an approved unsupported-update policy*.

That phrasing is the whole of this module's reason to exist. "Approved policy"
is otherwise a document, and a document is exactly the thing this project has
repeatedly found sitting in front of an unmeasured claim. Four separate
harnesses have reported PASS while measuring nothing; a policy asserting "the
system refuses updates" is the same shape unless something checks that the
system was observed to refuse.

So a policy is admissible here only when all of the following hold:

* it names an **accountable person**, not a role and not a placeholder;
* it binds to an **artifact digest**, not to a branch or to HEAD;
* it answers **all seven** of §10's questions, each non-trivially;
* it names a **review condition** and an expiry, so it cannot become permanent
  by inattention;
* the refusal it relies on has been **exercised at runtime** and the recorded
  run is complete and as-intended; and
* that run has a **negative control which actually failed**.

The last is the one that does real work. A refusal qualification whose control
did not fire is indistinguishable from an instrument that cannot fail, and this
module refuses to treat it as evidence.

What this module deliberately does **not** do is relabel any qualification
matrix row. A policy changes what a release is required to demonstrate. It does
not change what was executed, and the matrix records what was executed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1

DECISIONS = ("UNSUPPORTED", "SUPPORTED", "DEFERRED")

#: The seven questions §10 requires an update decision to answer explicitly.
REQUIRED_QUESTIONS = (
    "whereMetadataComesFrom",
    "howMetadataIsAuthenticated",
    "whatRootOfTrustIsPresent",
    "howRootRotationIsHandled",
    "whatHappensWhenVerificationFails",
    "whatPreventsDowngradeOrSubstitution",
    "howRollbackInteractsWithTrustedUpdates",
)

#: An answer shorter than this is a placeholder wearing an answer's clothes.
MINIMUM_ANSWER_CHARACTERS = 80

#: Strings that look like an approver and are not one.
PLACEHOLDER_NAMES = frozenset({
    "", "tbd", "TBD", "todo", "TODO", "n/a", "N/A", "none", "None",
    "unknown", "pending", "the team", "engineering", "security", "product",
})


class UpdatePolicyError(ValueError):
    """A policy that cannot be admitted, with the reason it cannot."""


@dataclass(frozen=True)
class PolicyVerdict:
    decision: str
    releaseClass: str
    approver: str
    boundToDigest: str
    admissible: bool
    reasons: tuple[str, ...]
    refusalQualified: bool
    detail: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "record": "update-support-policy-verdict",
            "decision": self.decision,
            "releaseClass": self.releaseClass,
            "approver": self.approver,
            "boundToDigest": self.boundToDigest,
            "admissible": self.admissible,
            "refusalQualified": self.refusalQualified,
            "reasons": list(self.reasons),
            "detail": dict(self.detail),
            "note": (
                "An admissible policy satisfies blocking condition 7. It does not close "
                "the update matrix, and it does not relabel any matrix row: the matrix "
                "records what was executed, and nothing was."
            ),
        }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UpdatePolicyError(f"cannot read {path}") from exc
    except json.JSONDecodeError as exc:
        raise UpdatePolicyError(f"{path.name} is not valid JSON: {exc}") from exc


def evaluate_refusal_qualification(
    policy: Mapping[str, Any],
    *,
    root: Path,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Check that the refusal the policy leans on was actually observed.

    Returns ``(qualified, reasons, detail)``. ``reasons`` is empty only when the
    run is complete, as-intended, and accompanied by a control that failed.
    """
    reasons: list[str] = []
    detail: dict[str, Any] = {}

    block = policy.get("refusalQualification")
    if not isinstance(block, Mapping):
        return False, ["no refusalQualification block; the refusal is asserted, not measured"], detail

    for field, label in (("evidence", "run"), ("negativeControl", "negative control")):
        reference = _text(block.get(field))
        if not reference:
            reasons.append(f"refusalQualification names no {label}")
            continue
        target = (root / reference).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            reasons.append(f"refusalQualification {label} reference escapes the repository")
            continue
        if not target.is_file():
            reasons.append(f"refusalQualification {label} {reference} does not exist")
            continue
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reasons.append(f"refusalQualification {label} {reference} is not readable JSON")
            continue
        detail[field] = {
            "reference": reference,
            "result": document.get("result"),
            "checks": document.get("checks"),
            "missingChecks": document.get("missingChecks"),
            "duplicateChecks": document.get("duplicateChecks"),
            "unexpectedChecks": document.get("unexpectedChecks"),
        }

    run = detail.get("evidence")
    if run is not None:
        if run["result"] != "AS_INTENDED":
            reasons.append(
                f"the recorded refusal run is {run['result']}, not AS_INTENDED"
            )
        if run["missingChecks"]:
            reasons.append(
                "the recorded refusal run is missing required checks: "
                + ", ".join(run["missingChecks"])
            )
        if run["duplicateChecks"]:
            reasons.append("the recorded refusal run reports duplicate checks")
        declared = block.get("requiredChecks")
        if isinstance(declared, int) and run["checks"] != declared:
            reasons.append(
                f"the policy declares {declared} required checks and the run recorded "
                f"{run['checks']}"
            )

    control = detail.get("negativeControl")
    if control is not None and control["result"] == "AS_INTENDED":
        # The single most important refusal in this module.
        reasons.append(
            "the negative control passed; a control that cannot fail is not a control, "
            "and the run it accompanies is not evidence that the refusal is real"
        )

    return (not reasons), reasons, detail


def evaluate_policy(document: Mapping[str, Any], *, root: Path) -> PolicyVerdict:
    """Admit or refuse a policy record, with every reason it was refused."""
    if not isinstance(document, Mapping):
        raise UpdatePolicyError("policy must be an object")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise UpdatePolicyError("update-support-policy schemaVersion is invalid")

    reasons: list[str] = []

    decision = _text(document.get("decision"))
    if decision not in DECISIONS:
        raise UpdatePolicyError(f"decision must be one of {', '.join(DECISIONS)}")

    release_class = _text(document.get("releaseClass"))
    if not release_class:
        reasons.append("no releaseClass; a policy that names no release class bounds nothing")

    approver = document.get("approver")
    approver_name = _text(approver.get("name")) if isinstance(approver, Mapping) else ""
    if approver_name.lower() in {name.lower() for name in PLACEHOLDER_NAMES}:
        reasons.append(
            "no accountable approver: a policy needs a person, and a role name is not one"
        )
    if isinstance(approver, Mapping) and not _text(approver.get("accountableFor")):
        reasons.append("the approver is not recorded as accountable for anything specific")

    bound = document.get("boundTo")
    digest = _text(bound.get("imageManifestDigest")) if isinstance(bound, Mapping) else ""
    if not digest.startswith("sha256:") or len(digest) != 71:
        reasons.append(
            "boundTo does not name a sha256 image manifest digest; a policy bound to a "
            "branch or to HEAD is not bound to anything releasable"
        )

    questions = document.get("questions")
    if not isinstance(questions, Mapping):
        reasons.append("no questions block; §10's seven questions are unanswered")
        questions = {}
    for name in REQUIRED_QUESTIONS:
        answer = _text(questions.get(name))
        if not answer:
            reasons.append(f"question {name} is unanswered")
        elif len(answer) < MINIMUM_ANSWER_CHARACTERS:
            reasons.append(f"question {name} is answered too briefly to be checkable")
    unknown = sorted(set(questions) - set(REQUIRED_QUESTIONS))
    if unknown:
        reasons.append("questions block carries unknown fields: " + ", ".join(unknown))

    if not _text(document.get("reviewCondition")):
        reasons.append(
            "no reviewCondition; a policy with no way to expire becomes permanent by "
            "inattention rather than by decision"
        )
    if not _text(document.get("expires")):
        reasons.append("no expiry date")

    # A waiver list is permitted but must be explicit about what it waives.
    waived = document.get("waivedScenarios")
    if waived is None:
        reasons.append("waivedScenarios is absent; an empty list must be stated, not implied")
    elif not isinstance(waived, list):
        reasons.append("waivedScenarios must be a list")
    else:
        for entry in waived:
            if not isinstance(entry, Mapping) or not _text(entry.get("scenario")):
                reasons.append("every waived scenario must name a scenario")
            elif not _text(entry.get("reason")):
                reasons.append(
                    f"waived scenario {entry.get('scenario')!r} carries no reason; a blanket "
                    "waiver is refused"
                )

    qualified, refusal_reasons, refusal_detail = evaluate_refusal_qualification(document, root=root)
    if decision == "UNSUPPORTED":
        reasons.extend(refusal_reasons)

    return PolicyVerdict(
        decision=decision,
        releaseClass=release_class,
        approver=approver_name,
        boundToDigest=digest,
        admissible=not reasons,
        reasons=tuple(reasons),
        refusalQualified=qualified,
        detail={"refusalQualification": refusal_detail},
    )


def load_and_evaluate(path: Path, *, root: Path) -> PolicyVerdict:
    return evaluate_policy(_load(path), root=root)


__all__ = [
    "DECISIONS",
    "MINIMUM_ANSWER_CHARACTERS",
    "PolicyVerdict",
    "REQUIRED_QUESTIONS",
    "SCHEMA_VERSION",
    "UpdatePolicyError",
    "evaluate_policy",
    "evaluate_refusal_qualification",
    "load_and_evaluate",
]
