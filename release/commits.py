# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which commit is this, and which commit does the evidence describe?

Five commits were being treated as one. They are not interchangeable, and the
places they diverge are exactly the places evidence stops meaning what it says.

``CHECKOUT_COMMIT``
    What ``git rev-parse HEAD`` returns in the current working tree. On a
    ``pull_request`` event this is a commit GitHub synthesised and nobody pushed.

``PR_HEAD_COMMIT``
    The tip of the pull request's source branch. This is the commit a reviewer
    reads and the one that will land.

``MERGE_TEST_COMMIT``
    The synthetic merge of the PR head into the base that
    ``actions/checkout@v4`` checks out for a ``pull_request`` event. It exists to
    answer "does this integrate with the base?" and it exists nowhere else: it is
    not on any branch, it is not fetchable by SHA from a fresh clone, and it
    changes whenever the base moves. Testing it is correct. Describing it in a
    committed record is not.

``CANDIDATE_COMMIT``
    The immutable commit that artifacts and qualification evidence describe. The
    thing that was built and measured.

``EVIDENCE_COMMIT``
    A later commit that imports reports *about* the candidate. It is always ahead
    of the candidate, and promoting it to candidate would claim that evidence
    describes a tree that did not exist when the evidence was produced.

Six call sites resolved a commit independently, all of them as
``git rev-parse HEAD``:

    scripts/reachability.py:112          scripts/release.py:142
    scripts/build_evidence_record.py:239 scripts/write_qualification_reports.py:225
    scripts/reproducibility/collect_builder_record.py:185,256

The one that mattered, ``reachability.py``, stamped ``HEAD`` into 25 records and
then those records were committed, which moved ``HEAD``, which meant no record
could ever regenerate. The evidence invalidated itself by being recorded. This
module is the single place that rule now lives.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "COMMIT_KINDS",
    "COMMIT_PURPOSES",
    "CommitContext",
    "CommitError",
    "commit_for_purpose",
    "is_full_sha",
    "resolve_commit_context",
    "validate_candidate_binding",
]

_SHA = re.compile(r"^[0-9a-f]{40}$")
_MERGE_REF = re.compile(r"^refs/pull/(\d+)/merge$")

#: The five concepts, named so a record can say which one it carries.
COMMIT_KINDS = (
    "CHECKOUT_COMMIT",
    "PR_HEAD_COMMIT",
    "MERGE_TEST_COMMIT",
    "CANDIDATE_COMMIT",
    "EVIDENCE_COMMIT",
)

#: What a caller intends to do, which decides which commit it may use.
COMMIT_PURPOSES = (
    # Does the tree integrate with the base? The synthetic merge is the point.
    "integration-test",
    # Regenerate a committed record deterministically. Must use the declared
    # candidate, or the record describes whatever HEAD happened to be.
    "committed-evidence",
    # Build on an independent builder. Must be given an exact commit as input;
    # a branch name is not a build input.
    "independent-build",
)

#: Placeholder used when git is unavailable. Never a real commit.
NULL_COMMIT = "0" * 40


class CommitError(Exception):
    """A commit was used for something it cannot support."""


def is_full_sha(value: object) -> bool:
    """A full 40-character lowercase hex SHA. Abbreviations are not accepted."""
    return isinstance(value, str) and bool(_SHA.match(value))


GitRunner = Callable[[Sequence[str]], "str | None"]


def _default_git(root: Path) -> GitRunner:
    def run(arguments: Sequence[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None
        return result.stdout.strip()

    return run


@dataclass(frozen=True)
class CommitContext:
    """The five commits, each resolved once and kept distinct."""

    checkoutCommit: str
    prHeadCommit: str | None
    mergeTestCommit: str | None
    candidateCommit: str
    evidenceCommit: str | None
    event: str
    #: True when the checkout is a synthetic merge that exists only in this run.
    checkoutIsSyntheticMerge: bool
    #: Why the candidate is what it is: "declared", "pr-head", or "checkout".
    candidateSource: str

    @property
    def candidateIsCheckout(self) -> bool:
        return self.candidateCommit == self.checkoutCommit

    @property
    def candidateIsSynthetic(self) -> bool:
        return (
            self.mergeTestCommit is not None
            and self.candidateCommit == self.mergeTestCommit
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkoutCommit": self.checkoutCommit,
            "prHeadCommit": self.prHeadCommit,
            "mergeTestCommit": self.mergeTestCommit,
            "candidateCommit": self.candidateCommit,
            "evidenceCommit": self.evidenceCommit,
            "event": self.event,
            "checkoutIsSyntheticMerge": self.checkoutIsSyntheticMerge,
            "candidateSource": self.candidateSource,
            "candidateIsCheckout": self.candidateIsCheckout,
            "candidateIsSynthetic": self.candidateIsSynthetic,
        }


def _read_event_payload(environ: Mapping[str, str]) -> dict[str, Any]:
    path = environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_commit_context(
    *,
    root: Path,
    environ: Mapping[str, str] | None = None,
    declaredCandidate: str | None = None,
    evidenceCommit: str | None = None,
    git: GitRunner | None = None,
) -> CommitContext:
    """Resolve all five commits from the working tree and the CI event.

    ``declaredCandidate`` is the ``candidateCommit`` a committed record declares.
    When it is present it wins, because the candidate is a property of the
    evidence and not of whatever tree happens to be checked out. When it is
    absent the candidate falls back to the PR head on a pull-request event and to
    the checkout otherwise — never to a synthetic merge, which could not be
    checked out again later.
    """
    environ = os.environ if environ is None else environ
    run = git if git is not None else _default_git(root)

    checkout = run(["rev-parse", "HEAD"]) or NULL_COMMIT
    event = environ.get("GITHUB_EVENT_NAME", "") or "local"
    reference = environ.get("GITHUB_REF", "")

    pr_head: str | None = None
    merge_test: str | None = None

    if _MERGE_REF.match(reference) or event.startswith("pull_request"):
        payload = _read_event_payload(environ)
        head = payload.get("pull_request", {}).get("head", {}).get("sha")
        if is_full_sha(head):
            pr_head = str(head)
        # GITHUB_HEAD_REF names the source branch; the SHA is authoritative and
        # the branch name is only a fallback for resolving it locally.
        if pr_head is None:
            branch = environ.get("GITHUB_HEAD_REF")
            if branch:
                resolved = run(["rev-parse", f"origin/{branch}"])
                if is_full_sha(resolved):
                    pr_head = resolved

        # A synthetic merge has two parents and is not the PR head. Confirming
        # the parent count rather than trusting the ref name means a workflow
        # that checked out the head explicitly is not mislabelled.
        parents = (run(["rev-list", "--parents", "-n", "1", checkout]) or "").split()
        has_two_parents = len(parents) == 3
        if has_two_parents and checkout != pr_head:
            merge_test = checkout
        elif _MERGE_REF.match(reference) and checkout != pr_head:
            merge_test = checkout

    if declaredCandidate is not None:
        candidate, source = declaredCandidate, "declared"
    elif pr_head is not None:
        candidate, source = pr_head, "pr-head"
    else:
        candidate, source = checkout, "checkout"

    return CommitContext(
        checkoutCommit=checkout,
        prHeadCommit=pr_head,
        mergeTestCommit=merge_test,
        candidateCommit=candidate,
        evidenceCommit=evidenceCommit,
        event=event,
        checkoutIsSyntheticMerge=merge_test is not None and merge_test == checkout,
        candidateSource=source,
    )


def validate_candidate_binding(
    context: CommitContext,
    *,
    root: Path,
    git: GitRunner | None = None,
    requireExists: bool = True,
) -> list[str]:
    """Every reason this candidate binding is unusable. Empty means usable.

    Reasons rather than an exception, because a caller reporting an evidence
    record wants all of them at once and a caller gating on it wants to refuse
    on the first — and both are served by a list.
    """
    run = git if git is not None else _default_git(root)
    reasons: list[str] = []

    candidate = context.candidateCommit
    if not is_full_sha(candidate):
        reasons.append(
            f"candidateCommit {candidate!r} is not a full 40-character SHA; an abbreviation "
            "does not identify a commit unambiguously"
        )
        return reasons

    if candidate == NULL_COMMIT:
        reasons.append("candidateCommit is the null commit; no commit was resolved")
        return reasons

    if requireExists:
        if run(["cat-file", "-e", f"{candidate}^{{commit}}"]) is None:
            reasons.append(
                f"candidateCommit {candidate[:12]} does not exist in this repository; "
                "evidence cannot describe a commit nobody can check out"
            )
            return reasons

    # The refusal this module exists for.
    if context.candidateIsSynthetic:
        reasons.append(
            f"candidateCommit {candidate[:12]} is the synthetic merge commit for "
            f"{context.event}; a merge ref exists only inside this run and cannot satisfy a "
            "branch-head or release-candidate requirement"
        )

    evidence = context.evidenceCommit
    if evidence is not None:
        if not is_full_sha(evidence):
            reasons.append(f"evidenceCommit {evidence!r} is not a full 40-character SHA")
        elif evidence == candidate:
            # Permitted: evidence generated and committed in the same act is
            # unusual but not wrong. Reported so it is visible.
            pass
        elif requireExists and run(["cat-file", "-e", f"{evidence}^{{commit}}"]) is None:
            reasons.append(f"evidenceCommit {evidence[:12]} does not exist in this repository")
        elif run(["merge-base", "--is-ancestor", candidate, evidence]) is None:
            reasons.append(
                f"candidateCommit {candidate[:12]} is not an ancestor of evidenceCommit "
                f"{evidence[:12]}; an evidence commit must import reports about a commit that "
                "precedes it"
            )

    return reasons


def commit_for_purpose(
    purpose: str,
    context: CommitContext,
    *,
    explicitCommit: str | None = None,
) -> str:
    """The commit a caller may use for ``purpose``, or ``CommitError``.

    This is the rule the six independent call sites were each guessing at.
    """
    if purpose not in COMMIT_PURPOSES:
        raise CommitError(f"unknown commit purpose {purpose!r}; expected one of {COMMIT_PURPOSES}")

    if purpose == "integration-test":
        # Testing the synthetic merge is the whole point of a PR check.
        return context.checkoutCommit

    if purpose == "committed-evidence":
        if context.candidateIsSynthetic:
            raise CommitError(
                f"refusing to generate committed evidence for synthetic merge commit "
                f"{context.candidateCommit[:12]}: it exists only in this run. Check out the PR "
                "head, or declare a candidateCommit."
            )
        if not is_full_sha(context.candidateCommit):
            raise CommitError(
                f"committed evidence needs a full candidate SHA, got {context.candidateCommit!r}"
            )
        return context.candidateCommit

    # independent-build
    if not is_full_sha(explicitCommit):
        raise CommitError(
            "an independent build requires an exact 40-character commit supplied as input; "
            f"got {explicitCommit!r}. A branch name does not pin a build."
        )
    assert explicitCommit is not None
    return explicitCommit
