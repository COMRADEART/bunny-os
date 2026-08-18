# Phase 7 blocking conditions

**Written before any Phase 7 qualification was run, and before any Phase 7
result was known.** The brief's §23: *"Write final blocking conditions before
final measurements"* and *"Do not weaken the conditions after results arrive."*

The reason is the same as Phase 6's: a condition authored after the results are
in is authored by somebody who already knows which conditions would be
inconvenient. This file is committed ahead of the work so the diff shows
whether any of it moved.

Each condition states the **test**, not the aspiration: what specifically has
to be true, and what evidence decides it.

The subject artifact is unchanged from Phase 6: **`e906a48793d7`**, built from
commit `e906a48793d74544b39c14cc3e35e0654f5311e2`, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`.
If Phase 7 changes product code or image contents, the §21 policy applies: a
new artifact with its own digest and provenance, and **no PASS transfers from
`e906a487` to it**.

---

## The ten

### 1. Known accessibility FAILs unresolved

**Blocking unless:** the two recorded FAILs — `high-contrast` and
`text-scaling` — are each **fixed, verified and regression tested**: the fix
is identified by commit; the verification is a runtime measurement on a booted
system built from a commit containing the fix, with explicit assertions that
measure the intended requirement (the text is larger, the palette changed —
not merely "pixels differ"); and a regression test exists that fails if the
mechanism is removed.

**Not sufficient:** the fix existing in source. The design-system phase
measured the mechanism working on the image built from `7edd3fd`; the matrix
rows still record what was measured on `b09f523`, and they stay FAIL until a
measurement against an artifact from the fixed lineage replaces them. "UI
appeared" is not accessibility (§8); a visible control may be unreachable and
a reachable one unnamed.

### 2. Rollback harness cannot prove the deployment actually booted

**Blocking unless:** a rollback harness runs the product's own rollback path
and records **four deployment identities** — before-update, update-target,
selected-rollback, and actually-booted — where the actually-booted identity is
confirmed by **at least two independent sources** (the kernel command line's
`ostree=` argument and `bootc status` from inside the booted system), and the
harness distinguishes PASS / FAIL / NOT_RUN such that **a healthy machine on
the wrong deployment is FAIL**, not PASS and not NOT_RUN.

**Not sufficient:** "machine reached healthy target". Three recorded runs of
`vm-rollback-test.sh` passed exactly that way while the machine booted its
default deployment every time.

### 3. Rollback user state not verified against a prior expectation

**Blocking unless:** an `expectation.json` naming the preservation rule for
each marker — companion mode, companion scale, companion position, voice
configuration, permissions, locale, hostname, and the designated user-data
markers — is committed **before** the rollback journey boots, and the
after-rollback readings are compared against that file, not against a rule
inferred from the result.

**Not sufficient:** state that happens to survive. The expectation must exist
first, or survival and expectation cannot be told apart.

### 4. Recovery path lacks an approved disposition

**Blocking unless** one of:

* **A** — a defined recovery journey (machine cannot boot normally → recovery
  medium boots → user can inspect the installation → a recovery action is
  available → the outcome is verified) **passes** against a recovery medium
  with its own recorded identity (build commit, media digest, base image,
  creation method, boot environment); or
* **B** — recovery is **explicitly declared NOT_SUPPORTED** for this release
  class by an accountable owner, with scope, risk statement, and an
  expiration/review date.

**Not sufficient:** the main installation ISO assumed to double as recovery
media. If one artifact serves both purposes, that is proved, not assumed.
Silent NOT_RUN is refused by this condition's own structure: absence of a
decision is option neither-A-nor-B, which blocks.

### 5. Independent security review incomplete

**Blocking unless:** `operations/data/independent-reviews.json` carries a
completed `security` review binding to the subject artifact's digest, by a
reviewer who is no project principal, with result `APPROVED` or
`APPROVED_WITH_CONDITIONS` and every condition discharged.

**Not sufficient:** another internal scan, however thorough. Phase 7's job on
this condition is to make the review package reproducible by an external
party; the package is not the review.

### 6. Required Critical/High findings lack disposition

**Blocking unless:** every Critical and High finding bound to the subject
artifact carries one of `FIXED`, `MITIGATED`, `NOT_APPLICABLE`,
`ACCEPTED_RISK` — none `PENDING_REVIEW`; `ACCEPTED_RISK` names a person, not a
role; `NOT_APPLICABLE` carries an argument a reviewer can check; and the count
argued against is the conservative module-granularity one.

### 7. Physical hardware qualification incomplete

**Blocking unless:** at least one machine with a complete device record made
before first boot has run the full journey — physical boot → installation →
encrypted boot → login → Bunny desktop → Companion → voice → Trust → reboot —
from the subject artifact's installation medium, with the medium's digest
verified on the writing host and from the written medium.

**One machine is one qualified hardware data point, not universal
compatibility**, and this condition says so in advance.

### 8. Production artifact remains unsigned where signing is required

**Blocking unless:** the released artifact's digest is signed by an authorized
signer under controlled key access, and the signature verifies against the
exact artifact. Record: signer authority, artifact digest, signature
identifier, verification result, date.

**Not sufficient:** the development signing drill. The drill proves the
procedure; it signs nothing that ships. Private keys never appear in the
repository, the evidence tree, logs, or screenshots.

### 9. Required second signer / approval absent

**Blocking unless:** a second approval exists that **independently identifies
the artifact** — digest named by the second approver, not inherited from the
first — recording artifact digest, first signer, second signer, decision,
date, where the two are different people.

**Not sufficient:** a successful CI run.

### 10. Frozen evidence can be modified without detection

**Blocking unless:** the evidence-immutability guard covers **every frozen
qualification tree, including Phases 4, 5 and 6**, and both halves are
measured: legitimate evidence unchanged → the guard passes; one historical
evidence file modified (negative control) → the guard fails. The record ends
at `fa49380` today and pins nothing after it; the guard's existence is not its
coverage.

**Not sufficient:** `git diff` returning empty. That is an observation about
the current checkout, not a guard that would catch the next commit.

---

## Also required for Track A, though not numbered conditions

**Alpha validation** (Track B) blocks the release, not Track A: structured
Alpha evaluation against `e906a487` with no open finding classified
RELEASE BLOCKER / SECURITY / DATA LOSS / PRIVACY. Zero testers means unmet,
not vacuously met.

**Script executability** is an engineering gate: every committed executable
script must be able to run where it claims to (shebang present, no CRLF in
committed shell scripts, executable bit consistent), proven with a negative
control. Phase 6 shipped two scripts as qualification infrastructure that
Linux could not start.

---

## Exceptions

An exception is permitted; a silent one is not. Any exception records:

| Field | Requirement |
| --- | --- |
| Condition | which of the ten |
| Approver | a named person with the authority |
| Reason | why the condition cannot be met now |
| Risk accepted | what specifically could go wrong |
| Expiration / review condition | the date or event at which it is revisited |

**No exception has been recorded.** This section exists so the absence is
visible rather than implied.

---

## What these conditions imply before any work is done

Conditions 5, 7, 8 and 9 depend on people and hardware that do not exist for
this project today, and condition 6 depends on 5. They were unmet when this
file was written and no repository change can move them. Conditions 1, 2, 3,
4 and 10 are engineering conditions; Phase 7's Track A exists to move exactly
those five.

That is stated here, in advance, so that Phase 7's final disposition reads as
the arithmetic of conditions fixed beforehand rather than as a verdict arrived
at once the results were in.
