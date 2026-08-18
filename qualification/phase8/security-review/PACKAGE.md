# Independent security review — the package

For the reviewer. You are being asked to review **exact bytes**, not a
branch: artifact `e906a48793d7`, image digest
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
built from commit `e906a48793d74544b39c14cc3e35e0654f5311e2`, **UNSIGNED**,
frozen since Phase 4 and re-verified from bytes on 2026-08-18. If the bytes
you were given do not hash to these digests, stop and say so — that is
blocking condition 6.

## What is in the package

`review-package.json` — machine-readable, deterministic
(`build_package.py`; rerun it and diff): the artifact identity and all 44
Critical/High findings, each with advisory id, affected package, installed
version, fixed version where known, affected binaries, exposure, and
exploitability where any evidence exists.

The per-binary layer is the load-bearing part. podman and skopeo embed
different versions of the same modules, so a module-level row merges two
different questions — six advisories split between them (for example
`golang.org/x/crypto`: podman at/above fix, skopeo affected). The package
never collapses "package vulnerable" into "every binary vulnerable", nor
"one binary unaffected" into "package fixed"; the eight Criticals
additionally carry the named-vulnerable-symbol presence per binary.

## Current dispositions — and why they are what they are

| Disposition | Count | Meaning here |
| --- | ---: | --- |
| REQUIRES_REVIEW | 41 | awaiting exactly the review this package is for |
| UNKNOWN | 3 | podman's own advisories and `docker/docker`: Fedora snapshot pseudo-versions that cannot be honestly ordered against a release number; deciding them needs a commit-level comparison against dist-git |
| AFFECTED / NOT_AFFECTED | 0 | nothing in this repository establishes either at finding level, and nothing was guessed |

## What the project can tell you, and where

* The one advisory where both measured tests fail and the project explicitly
  offers no disposition: the grpc server-side Critical — see
  `qualification/phase6/security/REVIEW_PACKAGE.md` §4 for the concrete
  reachability question.
* Why nothing is patched: the packages are in the base image; `bootc`
  requires podman/skopeo; updates are declared UNSUPPORTED for this release
  class with the refusal measured (`UPDATE_TRUST_ARCHITECTURE_DECISION.md`).
  An installed Alpha receives no security updates — weigh your outcome
  accordingly.
* A correction you should read before trusting older evidence:
  `qualification/phase6/security/PIPEFAIL_CORRECTION.md`.

## Your outcome

One of: `APPROVED` / `APPROVED_WITH_CONDITIONS` / `BLOCKED` /
`MORE_EVIDENCE_REQUIRED` — recorded in
`operations/data/independent-reviews.json`, binding to the image digest
above. For every condition or blocker: the exact finding, severity, required
remediation, owner, artifact affected, and decision authority. Until that
record exists, this gate is NOT_RUN and nothing here counts as a review.
