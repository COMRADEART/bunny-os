# Independent review status

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **four packages prepared, zero reviews commissioned, zero delivered.**

```text
python scripts/release.py validate-independent-reviews

  package-prepared   security       reviewer=unassigned
  package-prepared   cryptography   reviewer=unassigned
  package-prepared   accessibility  reviewer=unassigned
  package-prepared   legal          reviewer=unassigned
BLOCKED: outstanding reviews: accessibility, cryptography, legal, security
```

## The self-review wall

This repository contains a great deal of security and privacy review, and none
of it is independent. `PHASE_7_SECURITY_REVIEW.md` records twelve assessments;
`ENCRYPTED_SYNC_SECURITY_REVIEW.md`, `FLEET_SECURITY_REVIEW.md`,
`INSTALLER_SECURITY_REVIEW.md` and the rest are all internal. They are useful
and they are not the artifact a release gate is asking for.

`release/reviews.py` therefore rejects any reviewer whose name or organisation
matches a project principal:

```text
security: reviewer 'Bunny OS maintainer' of 'ComradeArt' is affiliated with the
project; a self-review cannot be recorded as an independent review
```

A review reaches `delivered` only with an identified external reviewer *and* a
report file that exists on disk. The gate checks the file, not the claim.

## The four packages

Each contains the eight required sections: scope, source commit, threat model,
design documents, test results, known limitations, explicit questions, and
expected deliverables. They are generated from
`operations/data/independent-reviews.json` so the status and the package cannot
disagree.

### Security architecture — `reviews/security/`

Scope: the privileged broker, the root update agent, the installer secret
channel, the SELinux domains, the update trust chain, and the Phase 7 enrolment,
policy and remote-administration boundaries.

The first question is the one that matters most to the release:

> Are the 8 Critical `golang.org/x/crypto` findings in the vendored podman and
> skopeo binaries reachable in a Bunny OS deployment where no podman unit is
> enabled?

**This review is the only route by which any Critical finding can become
non-blocking.** `release/vulnerability.py` rejects a Critical with a non-blocking
disposition and no completed independent review reference, at parse time.
`SECURITY_REACHABILITY_REVIEW.md` answered nine of ten reachability questions
with measured evidence and could not answer the tenth — whether the vulnerable
code path is compiled in and active — because it needs per-CVE symbol analysis
of a 45 MB stripped Go binary.

### Encrypted-sync cryptography — `reviews/cryptography/`

Scope: the envelope format, the key hierarchy, device pairing, account recovery,
deletion semantics.

`gate-sync-pilot` lists `independentCryptographicReview` as a requirement and it
is unmet. **The sync pilot cannot proceed on any other basis**, regardless of how
the stable release goes.

### Accessibility — `reviews/accessibility/`

Scope: the fourteen essential workflows.

This is the review where the cost of being wrong is borne by a user rather than
by the project. Every accessibility result to date is static, and
`release/matrix.py` refuses a source-inspection pass in the accessibility matrix
for that reason. The load-bearing question:

> Can a screen-reader user complete an encrypted installation unaided, including
> entering and confirming a passphrase and recording a recovery key?

Nobody knows. That is the honest position and it is why the row blocks.

### Licensing and trademark — `reviews/legal/`

Scope: the GPL-3.0-or-later / Apache-2.0 split the owner selected, its outbound
compatibility against the 6077-record SBOM, and the trademark draft.

The question that gates the OEM programme:

> Do the GPL-3.0 anti-tivoisation terms conflict with shipping Secure Boot with
> a vendor-controlled key on OEM hardware?

The licence gate passes without this review — the seven mechanical requirements
are met — but no OEM agreement should be signed until it is answered.

## What each review would unblock

| Review | Unblocks |
|---|---|
| Security | the only route to dispositioning any Critical finding; the `security` evidence row |
| Cryptography | `gate-sync-pilot` entirely |
| Accessibility | the `Accessibility` evidence category and the accessibility approval |
| Legal | OEM distribution and `brandingAndLicensingApproval` |

None of the four can be produced by running more tests. Each needs an identified
external party and, realistically, money.

## Commissioning one

1. Identify an external reviewer; record their name and organisation.
2. Set `state` to `commissioned` in
   `operations/data/independent-reviews.json`.
3. On delivery, place the report in the review's directory and set
   `reportReference` to its path.
4. Set `state` to `delivered`.

The gate verifies the file exists and that the reviewer is not a project
principal before accepting any of it.
