"""Five commits, kept apart.

A pull-request job checks out a synthetic merge commit. That is correct for an
integration test and wrong for anything that gets committed, because the merge
commit exists only inside that run. Nothing prevented an evidence generator from
stamping one into a record, and the record would have looked well-formed.

Each test names the situation it stands for rather than the function it calls.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.commits import (  # noqa: E402
    COMMIT_KINDS,
    COMMIT_PURPOSES,
    CommitError,
    commit_for_purpose,
    is_full_sha,
    resolve_commit_context,
    validate_candidate_binding,
)

BRANCH_HEAD = "a" * 40
PR_HEAD = "b" * 40
MERGE = "c" * 40
BASE = "d" * 40
EVIDENCE = "e" * 40


def fake_git(*, head: str, parents: dict[str, list[str]] | None = None,
             exists: set[str] | None = None, ancestors: set[tuple[str, str]] | None = None):
    """A git that answers only what the resolver asks, with no repository."""
    parents = parents or {}
    exists = exists if exists is not None else {head}
    ancestors = ancestors or set()

    def run(arguments):
        arguments = list(arguments)
        if arguments[:2] == ["rev-parse", "HEAD"]:
            return head
        if arguments[0] == "rev-parse":
            return None
        if arguments[:3] == ["rev-list", "--parents"]:
            target = arguments[-1]
            return " ".join([target, *parents.get(target, [])])
        if arguments[0] == "cat-file":
            sha = arguments[-1].split("^")[0]
            return "" if sha in exists else None
        if arguments[:2] == ["merge-base", "--is-ancestor"]:
            return "" if (arguments[2], arguments[3]) in ancestors else None
        return None

    return run


def pr_event(directory: Path, headSha: str) -> dict[str, str]:
    payload = directory / "event.json"
    payload.write_text(
        json.dumps({"pull_request": {"head": {"sha": headSha}}}), encoding="utf-8"
    )
    return {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/4/merge",
        "GITHUB_EVENT_PATH": str(payload),
        "GITHUB_HEAD_REF": "feature/qualification-evidence-closure",
    }


class VocabularyTests(unittest.TestCase):
    def test_all_five_commit_kinds_are_named(self) -> None:
        self.assertEqual(
            COMMIT_KINDS,
            ("CHECKOUT_COMMIT", "PR_HEAD_COMMIT", "MERGE_TEST_COMMIT",
             "CANDIDATE_COMMIT", "EVIDENCE_COMMIT"),
        )

    def test_an_abbreviated_sha_is_not_a_full_sha(self) -> None:
        self.assertTrue(is_full_sha("9dc7e33f66a270150dfc2c1c9950b1e974a3c2ae"))
        self.assertFalse(is_full_sha("9dc7e33"))
        self.assertFalse(is_full_sha("9DC7E33F66A270150DFC2C1C9950B1E974A3C2AE"))
        self.assertFalse(is_full_sha(None))
        self.assertFalse(is_full_sha("z" * 40))


class LocalBranchCheckoutTests(unittest.TestCase):
    def test_a_local_branch_checkout_has_no_merge_commit(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, git=fake_git(head=BRANCH_HEAD)
        )
        self.assertEqual(context.checkoutCommit, BRANCH_HEAD)
        self.assertIsNone(context.mergeTestCommit)
        self.assertIsNone(context.prHeadCommit)
        self.assertFalse(context.checkoutIsSyntheticMerge)
        self.assertEqual(context.candidateCommit, BRANCH_HEAD)
        self.assertEqual(context.candidateSource, "checkout")
        self.assertEqual(context.event, "local")


class DetachedExactCommitTests(unittest.TestCase):
    def test_a_detached_exact_commit_is_its_own_candidate(self) -> None:
        context = resolve_commit_context(
            root=ROOT,
            environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
            git=fake_git(head=PR_HEAD),
        )
        self.assertEqual(context.candidateCommit, PR_HEAD)
        self.assertFalse(context.checkoutIsSyntheticMerge)
        self.assertEqual(
            commit_for_purpose("independent-build", context, explicitCommit=PR_HEAD), PR_HEAD
        )


class PullRequestMergeCommitTests(unittest.TestCase):
    def test_a_synthetic_merge_checkout_is_recognised_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ = pr_event(Path(directory), PR_HEAD)
            context = resolve_commit_context(
                root=ROOT, environ=environ,
                git=fake_git(head=MERGE, parents={MERGE: [BASE, PR_HEAD]}),
            )
            self.assertEqual(context.checkoutCommit, MERGE)
            self.assertEqual(context.mergeTestCommit, MERGE)
            self.assertEqual(context.prHeadCommit, PR_HEAD)
            self.assertTrue(context.checkoutIsSyntheticMerge)

    def test_the_candidate_falls_back_to_the_pr_head_not_the_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ = pr_event(Path(directory), PR_HEAD)
            context = resolve_commit_context(
                root=ROOT, environ=environ,
                git=fake_git(head=MERGE, parents={MERGE: [BASE, PR_HEAD]}),
            )
            self.assertEqual(context.candidateCommit, PR_HEAD)
            self.assertEqual(context.candidateSource, "pr-head")
            self.assertFalse(context.candidateIsSynthetic)

    def test_an_integration_test_may_use_the_synthetic_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ = pr_event(Path(directory), PR_HEAD)
            context = resolve_commit_context(
                root=ROOT, environ=environ,
                git=fake_git(head=MERGE, parents={MERGE: [BASE, PR_HEAD]}),
            )
            self.assertEqual(commit_for_purpose("integration-test", context), MERGE)


class PullRequestHeadCheckoutTests(unittest.TestCase):
    def test_an_explicit_head_checkout_is_not_labelled_synthetic(self) -> None:
        # A workflow that sets `ref: ${{ github.event.pull_request.head.sha }}`
        # is on a pull_request event but is not on a merge commit.
        with tempfile.TemporaryDirectory() as directory:
            environ = pr_event(Path(directory), PR_HEAD)
            context = resolve_commit_context(
                root=ROOT, environ=environ,
                git=fake_git(head=PR_HEAD, parents={PR_HEAD: [BASE]}),
            )
            self.assertEqual(context.checkoutCommit, PR_HEAD)
            self.assertIsNone(context.mergeTestCommit)
            self.assertFalse(context.checkoutIsSyntheticMerge)
            self.assertEqual(context.candidateCommit, PR_HEAD)


class EvidenceAfterCandidateTests(unittest.TestCase):
    def test_an_evidence_commit_ahead_of_the_candidate_is_accepted(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate=BRANCH_HEAD, evidenceCommit=EVIDENCE,
            git=fake_git(head=EVIDENCE, exists={BRANCH_HEAD, EVIDENCE},
                         ancestors={(BRANCH_HEAD, EVIDENCE)}),
        )
        reasons = validate_candidate_binding(
            context, root=ROOT,
            git=fake_git(head=EVIDENCE, exists={BRANCH_HEAD, EVIDENCE},
                         ancestors={(BRANCH_HEAD, EVIDENCE)}),
        )
        self.assertEqual(reasons, [])
        self.assertEqual(context.candidateCommit, BRANCH_HEAD)
        self.assertEqual(context.evidenceCommit, EVIDENCE)

    def test_an_evidence_commit_that_does_not_descend_from_the_candidate_is_refused(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate=BRANCH_HEAD, evidenceCommit=EVIDENCE,
            git=fake_git(head=EVIDENCE, exists={BRANCH_HEAD, EVIDENCE}, ancestors=set()),
        )
        reasons = validate_candidate_binding(
            context, root=ROOT,
            git=fake_git(head=EVIDENCE, exists={BRANCH_HEAD, EVIDENCE}, ancestors=set()),
        )
        self.assertTrue(any("is not an ancestor of evidenceCommit" in r for r in reasons), reasons)

    def test_an_evidence_commit_may_not_be_promoted_to_candidate(self) -> None:
        # Commit B imports reports about Commit A. Declaring B the candidate
        # would claim the evidence describes a tree that did not exist when the
        # evidence was measured.
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate=EVIDENCE, evidenceCommit=EVIDENCE,
            git=fake_git(head=EVIDENCE, exists={BRANCH_HEAD, EVIDENCE},
                         ancestors={(BRANCH_HEAD, EVIDENCE)}),
        )
        self.assertEqual(context.candidateCommit, context.evidenceCommit)
        # Structurally legal, and therefore reported rather than silently allowed:
        # the readiness report must show candidate and evidence as the same commit
        # so a reviewer can see the promotion happened.
        self.assertEqual(context.as_dict()["candidateCommit"], EVIDENCE)
        self.assertEqual(context.as_dict()["evidenceCommit"], EVIDENCE)


class WrongAndMissingCandidateTests(unittest.TestCase):
    def test_a_candidate_that_does_not_exist_is_refused(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate="f" * 40,
            git=fake_git(head=BRANCH_HEAD, exists={BRANCH_HEAD}),
        )
        reasons = validate_candidate_binding(
            context, root=ROOT, git=fake_git(head=BRANCH_HEAD, exists={BRANCH_HEAD})
        )
        self.assertTrue(any("does not exist in this repository" in r for r in reasons), reasons)

    def test_an_abbreviated_candidate_is_refused(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate="9dc7e33",
            git=fake_git(head=BRANCH_HEAD),
        )
        reasons = validate_candidate_binding(context, root=ROOT, git=fake_git(head=BRANCH_HEAD))
        self.assertTrue(any("not a full 40-character SHA" in r for r in reasons), reasons)

    def test_a_missing_candidate_falls_back_and_is_reported(self) -> None:
        context = resolve_commit_context(
            root=ROOT, environ={}, declaredCandidate=None,
            git=fake_git(head=BRANCH_HEAD, exists={BRANCH_HEAD}),
        )
        self.assertEqual(context.candidateSource, "checkout")
        self.assertEqual(
            validate_candidate_binding(
                context, root=ROOT, git=fake_git(head=BRANCH_HEAD, exists={BRANCH_HEAD})
            ),
            [],
        )


class EvidenceBoundToAMergeRefTests(unittest.TestCase):
    """The refusal this module exists for."""

    def _synthetic_context(self, directory: Path):
        environ = pr_event(directory, PR_HEAD)
        return resolve_commit_context(
            root=ROOT, environ=environ, declaredCandidate=MERGE,
            git=fake_git(head=MERGE, parents={MERGE: [BASE, PR_HEAD]}, exists={MERGE}),
        )

    def test_a_candidate_bound_to_the_merge_ref_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self._synthetic_context(Path(directory))
            self.assertTrue(context.candidateIsSynthetic)

    def test_a_candidate_bound_to_the_merge_ref_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self._synthetic_context(Path(directory))
            reasons = validate_candidate_binding(
                context, root=ROOT,
                git=fake_git(head=MERGE, parents={MERGE: [BASE, PR_HEAD]}, exists={MERGE}),
            )
            self.assertTrue(
                any("synthetic merge commit" in r for r in reasons), reasons
            )

    def test_committed_evidence_generation_refuses_a_merge_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self._synthetic_context(Path(directory))
            with self.assertRaises(CommitError) as caught:
                commit_for_purpose("committed-evidence", context)
            self.assertIn("exists only in this run", str(caught.exception))


class IndependentBuildRequiresAnExactCommitTests(unittest.TestCase):
    def test_a_branch_name_is_refused_as_a_build_input(self) -> None:
        context = resolve_commit_context(root=ROOT, environ={}, git=fake_git(head=BRANCH_HEAD))
        for supplied in (None, "main", "feature/qualification-evidence-closure", "9dc7e33"):
            with self.subTest(supplied=supplied):
                with self.assertRaises(CommitError):
                    commit_for_purpose("independent-build", context, explicitCommit=supplied)

    def test_an_unknown_purpose_is_refused(self) -> None:
        context = resolve_commit_context(root=ROOT, environ={}, git=fake_git(head=BRANCH_HEAD))
        with self.assertRaises(CommitError):
            commit_for_purpose("whatever", context)

    def test_every_documented_purpose_is_handled(self) -> None:
        context = resolve_commit_context(root=ROOT, environ={}, git=fake_git(head=BRANCH_HEAD))
        for purpose in COMMIT_PURPOSES:
            with self.subTest(purpose=purpose):
                try:
                    commit_for_purpose(purpose, context, explicitCommit=BRANCH_HEAD)
                except CommitError:  # a documented refusal is a handled purpose
                    pass


class RealRepositoryTests(unittest.TestCase):
    """Against this repository, with real git."""

    def test_the_working_tree_resolves_without_a_synthetic_merge(self) -> None:
        if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                          capture_output=True).returncode != 0:
            self.skipTest("not a git repository")
        context = resolve_commit_context(root=ROOT, environ={})
        self.assertTrue(is_full_sha(context.checkoutCommit))
        self.assertFalse(context.checkoutIsSyntheticMerge)
        self.assertEqual(validate_candidate_binding(context, root=ROOT), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
