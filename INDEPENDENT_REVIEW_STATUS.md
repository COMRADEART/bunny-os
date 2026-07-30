# Independent review status

Date: 2026-07-30
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`
Result: **four packages prepared, four bounded requests ready to send, zero reviews
commissioned, zero delivered.**

```text
python scripts/release.py validate-independent-reviews

  package-prepared   security       reviewer=unassigned
  package-prepared   cryptography   reviewer=unassigned
  package-prepared   accessibility  reviewer=unassigned
  package-prepared   legal          reviewer=unassigned

  request accessibility  ready
  request cryptography   ready
  request legal          ready
  request security       ready

delivered review records: 0 of 0
BLOCKED: outstanding reviews: accessibility, cryptography, legal, security
No reviewer name or completion date has been invented; the requests are ready to send.
```

## What the qualification evidence closure added

**Four bounded review requests**, each with the ten sections a reviewer needs
before they can start: exact scope, commit, artifacts, threat model, questions,
expected report format, severity model, expected independence statement,
confidentiality requirements, and **prohibited claims**.

| Request | Scope | Load-bearing question |
|---|---|---|
| `reviews/security/REQUEST.md` | per-CVE reachability of 24 findings, plus the broker, update chain, installer secret channel, SELinux domains, Phase 7 boundaries | is the vulnerable code path compiled in and active? |
| `reviews/cryptography/REQUEST.md` | envelope, key hierarchy, pairing, recovery, deletion, revocation, signing design | is account recovery a backdoor? |
| `reviews/accessibility/REQUEST.md` | 17 workflows, 7 of them critical | can a screen-reader user complete an encrypted installation unaided? |
| `reviews/legal/REQUEST.md` | outbound compatibility, anti-tivoisation, the Apache/GPL boundary, trademark | do the GPL-3.0 anti-tivoisation terms conflict with vendor-controlled Secure Boot on OEM hardware? |

`request_gaps` checks each request for all ten sections and for an explicit refusal
of "certified" / "compliant" / "endorsed" claims — three omissions that produce an
unusable report.

**A signed review-record schema.** A delivered review now needs more than a state
change. `parse_review_record` requires and checks:

| Requirement | Refusal |
|---|---|
| an identified reviewer who is not a project principal | *"a repository maintainer cannot mark their own review as independent"* |
| an independence declaration in the reviewer's own words | *"not a flag"* — at least a sentence |
| a scope commit equal to the candidate commit | *"a review does not transfer between commits"* |
| named scope artifacts | *"an unscoped review cannot be relied on for anything in particular"* |
| a report digest that **recomputes** from the file | *"the report was changed after the record was written"* |
| a detached signature over that digest | *"without a signature a delivered report can be substituted and the record still validates"* |
| no open critical or high finding beside a `pass` | *"that is a conditional pass at best"* |

A `conditional` conclusion with any open finding is not acceptable either: a
conditional pass whose conditions are unmet is a fail with better manners.

**No reviewer name or completion date has been invented.** The requests tell the
reviewer to record the commit they are given, so no future commit is hard-coded
anywhere.

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

1. Send the matching `reviews/<kind>/REQUEST.md`, with the commit the reviewer
   should scope to.
2. Identify the reviewer; record their name and organisation.
3. Set `state` to `commissioned` in `operations/data/independent-reviews.json`.
4. On delivery, place the report in the review's directory and set
   `reportReference` to its path.
5. Add the reviewer's signed `IndependentReviewRecord` to the document's `records`
   array.
6. Set `state` to `delivered`.

```text
python scripts/release.py validate-independent-reviews
make validate-independent-reviews
```

The gate verifies the file exists, recomputes its digest, checks the scope commit
against the candidate commit, requires a signature, and refuses any reviewer who is
a project principal — before accepting any of it.

## Related

- `INDEPENDENT_SECURITY_REVIEW_REQUEST.md`
- `INDEPENDENT_CRYPTOGRAPHY_REVIEW_REQUEST.md`
- `INDEPENDENT_ACCESSIBILITY_REVIEW_REQUEST.md`
- `LEGAL_REVIEW_REQUEST.md`
- `security/reachability/schemas/independent-review-record.schema.json`
- `tests/review_evidence/` — 30 tests, including the self-review-marked-independent
  and unsigned-report adversarial cases
