<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 13 — Release Authority, Sufficiency Thresholds & Decision Governance

## STATUS: **PHASE 13 — GOVERNANCE READY, EVIDENCE PENDING**

**PHASE 13 DOES NOT AUTHORIZE THE ARTIFACT.**

The subject artifact `e906a48793d7` remains ROOT, FROZEN, UNCHANGED,
UNSIGNED. The derived candidate authorization state is
**EVIDENCE_PENDING** and the derived candidate decision is
**REQUIRES_MORE_EVIDENCE** — because zero external evidence exists, and
the machinery passing is not a favorable status. What this phase built
is the ability to *record, validate, bind, evaluate, and refuse*: when
the first real reviewer, tester, signer, hardware operator, second
approver, or release authority acts, the repository can take the action
in and can refuse every shortcut around the rules that were committed
before the action existed.

## 1. Executive summary

Phase 13 is the last internal governance-preparation layer. It defines
release authorities and keeps role-definition, assignment, and action
mechanically distinct; enforces separation of duties fail-closed; gives
Alpha sufficiency thresholds an owner-controlled, versioned, sealed
activation mechanism that starts undefined; imports the ten inherited
blocking conditions verbatim behind a sha256 pin; resolves conflicting
evidence to a required human decision, never an average; makes risk
acceptance explicit, scoped, expiring, and non-transferable; binds
authorization records to exact bytes with mandatory expiry and
irreversible revocation; refuses authorization inheritance across
artifact edges; and derives one candidate authorization state through a
documented, tested, most-restrictive-wins priority. The one principle,
enforced everywhere:

> The repository may evaluate whether authorization requirements are
> satisfied. It may never create the authority that satisfies them.

90 new guard tests (436 release-suite total) execute every refusal
branch, and both immutability guards refused the tree before declaring
it.

## 2. Starting artifact identity

Unchanged from Phases 7–12 and verified against the intake boundary on
every derivation:

| Field | Value |
| --- | --- |
| Artifact | `e906a48793d7` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Status | ROOT, FROZEN, UNCHANGED, **UNSIGNED** |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |

Nothing in this phase rebuilt, replaced, mutated, requalified, or
superseded it. Phase 13 started at `ec03e699` with a clean tree.

## 3. Scope and non-goals

In scope: the governance layer under `qualification/phase13/`
(authority model, sufficiency registry, blocking registry, decision
registries, decision engine, derived status), its guard suite, and the
immutability declaration. Non-goals, enforced structurally: no security
review, production signing, second approval, hardware validation,
tester evidence, or release authorization was performed, simulated, or
invented; no threshold value was chosen; no person was named to any
role. One placement note: the brief names the engine
`tools/release_authority_ops.py`; it lives at
`qualification/phase13/tools/release_authority_ops.py`, exactly where
Phases 9–12 put `intake.py`, `candidate_ops.py`,
`security_review_ops.py`, and `alpha_ops.py` — the established
convention, and `qualification/` is not a build COPY root, so the
engine can never reach the image.

## 4. Authority model

`governance/authorities.json` + `AUTHORITY_MODEL.md` define seven
authorities with stable identifiers: `AUTH-SECURITY-REVIEWER`,
`AUTH-SECURITY-OWNER`, `AUTH-ALPHA-PROGRAM`, `AUTH-RELEASE`,
`AUTH-KEY`, `AUTH-SECOND-APPROVER`, `AUTH-HARDWARE`. No real person is
named anywhere. Three levels are kept mechanically distinct:

- **ROLE_DEFINED** — the role exists in a JSON file. That is not an
  authority action, and the derived status says so per authority.
- **AUTHORITY_ASSIGNED** — a sealed assignment record
  (`record assignment`) names an identity. Still not an act.
- **AUTHORITY_ACTED** — the act exists: a gate-eligible ACCEPTED intake
  in the matching Phase 9 source for evidence-producing roles; a
  validated sealed Phase 13 decision for decision-making roles — which
  validates only against an assignment, so a decision-maker cannot have
  acted unassigned.

At phase close, all seven authorities are **ROLE_DEFINED**.

## 5. Separation of duties

`governance/separation-policy.json` names seven incompatible pairs
(reviewer/owner, reviewer/release, owner/release, alpha-owner/release,
release/key, release/second-approver, key/second-approver). One
identity holding both sides of a pair is a violation that refuses
`AUTHORIZED` — unless a **recorded, sealed overlap decision** names the
identity, both roles, the reason, the deciding authority, and the date.
Matching strings never permit overlap. The signer/approver check also
runs at the evidence level: a production signer appearing as a second
approver is a `CONFLICT` refusal without a recorded decision, and
Phase 9 already rejects one person approving twice.

## 6. Sufficiency threshold architecture

`sufficiency/threshold-policies.json` + `THRESHOLD_ARCHITECTURE.md`:
a policy is a sealed `SUFFICIENCY-POLICY-NNN` record with
`artifact_digest`, `thresholds` covering all eleven dimensions
(minimum accepted reports, distinct testers, distinct machine
identities, successful installations, completed core journeys,
evidence-period days; maximum unresolved blocker and critical
findings; performance and accessibility evidence requirements; minimum
distinct hardware machines), `effective_at`, `authority`, `status`, and
`supersedes`. Activation requires an assigned `AUTH-ALPHA-PROGRAM`
identity. Lifecycle: `SUFFICIENCY_POLICY_UNDEFINED` → `_PROPOSED` →
`_ACTIVE` → evaluated on every sync. Versioning: an activated policy is
sealed and immutable; a later threshold is a new record superseding the
old one; old policy, old evidence, and old evaluation are preserved; at
most one ACTIVE policy stands unsuperseded, and a policy for other
bytes activates nothing for this artifact. Measures derive from the
committed Phase 11/12 registers and the ledger — zero measured as zero.

## 7. Threshold undefined state

The registry is **empty**: `SUFFICIENCY_POLICY_UNDEFINED`. No
production value was invented — the fixture policy used by dry runs is
`TEST_FIXTURE_ONLY` and refused everywhere real records are read. The
guarded consequence, tested both ways: `READY_FOR_TESTERS` can never
become `SUFFICIENT` without an active, artifact-applicable policy — one
hundred accepted tester reports against undefined thresholds derive
`SUFFICIENCY_UNDETERMINED`, with the measures recorded beside the
refusal.

## 8. Evidence cut rules

Every authorization decision is explicit about artifact identity,
evidence applicability, policy version, evaluation time, decision time,
and authority (`decisions/DECISION_GOVERNANCE.md`). The record's
`evidence_cut` pins the exact `LEDGER.json` bytes by sha256 plus the
intake IDs relied on; a cut naming different bytes than the ledger
presented is refused. Evaluation time is an operator-stated `--as-of`
date recorded in the derived status — no clock is ever read, and the
derived decision reproduces from immutable inputs on every run.

## 9. Blocking conditions

`blocking/blocking-conditions.json` (derived by `build-blocking`)
imports the ten inherited conditions — **titles verbatim from the
committed decision record, none rewritten, none weakened** — and pins
their Phase 8 source
(`qualification/phase8/conditions/ALPHA_RELEASE_BLOCKING_CONDITIONS.md`)
by sha256; a drifted pin refuses. Classes `BLOCKING`, `NON_BLOCKING`,
`REQUIRES_HUMAN_DECISION`, `NOT_APPLICABLE` exist, every condition is
`BLOCKING`, and `BLOCKING → NON_BLOCKING` requires a sealed
reclassification decision with reason, authority, artifact, timestamp,
policy basis, and evidence references — by an assigned identity. The
registry also derives each condition's evidence character: today
conditions 1, 2, 7, 8 are TRUE **on absence of evidence** (pending,
per this project's established semantics), 3, 4, 5, 9, 10 are
UNDETERMINED (not cleared), 6 is FALSE (cleared). `AUTHORIZED` requires
every condition FALSE on evidence.

## 10. Conflict resolution

`classify_evidence_conflict` never averages: favorable and unfavorable
observations of the same thing derive `CONFLICT →
REQUIRES_HUMAN_DECISION` with the unfavorable assessment(s) effective,
all evidence exposed verbatim, the reason stated, and the required
deciding authority named per domain (security → `AUTH-SECURITY-OWNER`,
hardware → `AUTH-HARDWARE`, alpha → `AUTH-ALPHA-PROGRAM`, release →
`AUTH-RELEASE`). Only a sealed resolution by the assigned domain
authority changes the outcome; an observation without a stated
direction is refused rather than defaulted favorable.

## 11. Risk acceptance

`decisions/risk-acceptances.json` records `RISK-NNN` with all ten
required fields (risk id, artifact digest, finding ids, scope, reason,
authority, evidence, accepted-at, expires-at, revocation conditions).
Enforced rules, each with a negative control: acceptance never
transfers to a successor (digest equality only, no transfer branch);
expiry derives automatically and an expired acceptance **blocks**
authorization; an acceptance cannot close the underlying finding
(lifecycle authority stays with Phases 10/11) and cannot carry an
applicability claim — `ACCEPTED_RISK` is not `NOT_AFFECTED`; a
dangling finding reference fails closed; Critical findings require an
assigned `AUTH-SECURITY-OWNER` identity. The registry is empty.

## 12. Authorization model

`decisions/authorizations.json` records `AUTHORIZATION-NNN` with the
full field set (artifact digest and identity, decision, authority and
role, decision timestamp, evidence cut, the five gate statuses,
blocking conditions, accepted risks, policy versions, issued/expires).
Decisions: `AUTHORIZED`, `NOT_AUTHORIZED`, `BLOCKED`,
`REQUIRES_MORE_EVIDENCE`, `REVOKED`, `EXPIRED` — the repository
derives only the middle three. `AUTHORIZED` validates only over: the
extended authorization floor (a gate-eligible ACCEPTED intake in **all
five** sources — Phase 9's three-source floor widened to
`security-review`, `hardware`, `signing`, `second-approval`,
`alpha-feedback`); an assigned `AUTH-RELEASE` authority; no separation
violation; `PRODUCTION ARTIFACT SIGNED` signing evidence (a drill is
rejected at intake and rechecked here); a `SATISFIED` Phase 11 gate;
`SUFFICIENT` under an active policy; every blocking condition FALSE;
no expired acceptance; a matching evidence cut; and stated gate
statuses that agree with the derived ones. The registry is empty, and
the only recorded path in is `record authorization`, which runs the
full validation before sealing.

## 13. Expiry

No infinite authorization by omission: a record without `expires_at`
is invalid — tested. At evaluation, `as_of > expires_at` derives
`EXPIRED` automatically; nobody flips the state, and any evaluation
that needs an expiry answer without an operator-stated date refuses
(`BoundaryViolation`), never assumes.

## 14. Revocation

`REVOCATION-NNN` records target one authorization with artifact,
reason, authority (assigned `AUTH-RELEASE` or `AUTH-SECURITY-OWNER`),
timestamp, and evidence. `AUTHORIZED → REVOKED` holds with the record;
`REVOKED → AUTHORIZED` is refused by the transition table — a new
authorization is a new record from `READY_FOR_AUTHORIZATION`.
Revocation status is derived from the revocations registry and may not
be stored on the authorization record (a stored flag is refused);
editing the sealed revocation — including `revocation_status: false` —
is an **IMMUTABILITY FAIL**. Revocation outranks expiry.

## 15. Successor artifact behavior

Authorization binds to exact bytes. `authorization_applies` has
deliberately no graph or transfer-decision parameter: a Phase 10
transfer decision covers *evidence* applicability, and there is no
mechanism for authorization to ride. A modelled successor of the
subject is `REFUSED` and starts `NOT_AUTHORIZED` regardless of its
parent — tested, alongside the matching risk-acceptance refusal.

## 16. Candidate state machine

Twelve states: `EVIDENCE_PENDING`, `SECURITY_REVIEW_PENDING`,
`ALPHA_EVIDENCE_PENDING`, `SUFFICIENCY_UNDEFINED`,
`SUFFICIENCY_UNDETERMINED`, `REQUIRES_MORE_EVIDENCE`,
`READY_FOR_AUTHORIZATION`, `AUTHORIZED`, `BLOCKED`,
`REMEDIATION_REQUIRED`, `EXPIRED`, `REVOKED`. The transition table is
explicit and the full 12×12 sweep asserts every pair outside it
refuses; `AUTHORIZED` is reachable from exactly
`READY_FOR_AUTHORIZATION`, and every guard refuses silence. The
documented, tested decision priority (most restrictive wins):

```
REVOKED > EXPIRED > REMEDIATION_REQUIRED > BLOCKED
        > EVIDENCE_PENDING > SECURITY_REVIEW_PENDING
        > ALPHA_EVIDENCE_PENDING > SUFFICIENCY_UNDEFINED
        > SUFFICIENCY_UNDETERMINED > REQUIRES_MORE_EVIDENCE
        > READY_FOR_AUTHORIZATION > AUTHORIZED
```

One adjustment to the brief's example ordering, from this project's
established semantics: a condition TRUE **on absence of evidence**
derives the corresponding pending state ("absence blocks, it does not
authorize" — the Phase 10 candidate sits at `EVIDENCE_PENDING` today
for the same reason), while a condition TRUE **on adverse evidence**
derives `BLOCKED`. The registry records which is which, and neither
authorizes anything. A fully-satisfied world without a decision derives
`READY_FOR_AUTHORIZATION` with candidate decision `NOT_AUTHORIZED` —
the repository stops exactly one step short, by construction.

## 17. Negative controls

All §20 controls implemented and executed on every run:

| Control | Result |
| --- | --- |
| Internal JSON claiming AUTHORIZED | REFUSED; all five absent floor sources named |
| Valid authority record, wrong digest | DOES_NOT_APPLY |
| Signer == second approver | CONFLICT / REFUSED; permitted only by a recorded overlap decision |
| 100 accepted reports, thresholds undefined | SUFFICIENCY_UNDETERMINED |
| Edit an active policy | seal broken — IMMUTABILITY FAIL |
| Authorization past expires_at | EXPIRED, derived |
| Valid authorization + revocation | REVOKED; outranks expiry |
| Authorized parent, new successor | NOT_AUTHORIZED / REFUSED |
| PASS + FAIL evidence | CONFLICT → REQUIRES_HUMAN_DECISION |
| Accepted risk on A applied to B | REFUSED |
| Signing drill as production signing | REJECTED at intake; floor refuses |
| Missing expiry | record invalid |
| Edit a sealed revocation | IMMUTABILITY FAIL |
| Unassigned release authority | REFUSED — a role in a JSON file is not an authority action |
| Reclassification unrecorded / incomplete | refused; blocker unweakened |
| Every forbidden state transition | refused (full 12×12 sweep) |

## 18. Fixture isolation

Twelve fixtures, each carrying **all three** markers (`fixtureClass:
TEST_FIXTURE_ONLY`, `"fixture": true`, `"test_fixture_only": true`).
The Phase 9 boundary rejects the wrapper structurally (executed against
the real registration code in a constructed tree); Phases 10–12 refuse
`fixtureClass` as before; Phase 13's `is_fixture` treats *any one*
marker as disqualifying, and `verify` requires committed fixtures to
carry all three. `append_record` refuses fixtures; no committed
governance record may carry a marker. The real ledger, graph, decision
record, both registers, and the derived status are byte-compared before
and after every dry run — never asserted empty.

## 19. Immutability demonstration

The standing demonstration, repeated exactly: at `ed66b857` both
guards (`tests/release/test_frozen_evidence.py`,
`tests/companion/test_three_d_preservation.py`) **fail**, each naming
all twenty-eight committed phase13 files as additions — the refusal
preserved in the guard output at that commit. `65ea5600` then declares
`qualification/phase13/` in both guards' after-the-record lists (the
maintenance mechanism; no cut-time exemption grew, no guard weakened),
and both pass. The tree cannot be pinned while the decision is open —
its reproducibility guard is
`tests/release/test_phase13_release_authority.py`.

## 20. Validation results

At `65ea5600`, with discovery counts verified explicitly on both
targets via `discover().countTestCases()`:

| Check | Windows 11 | Fedora 44 WSL2, ext4, as `bunny` |
| --- | --- | --- |
| Release suite (discovered 436 = 346 prior + 90 new) | 436 OK (1 skip) | 436 OK (1 skip) |
| Portability suite (discovered 205) | 205 OK (3 platform skips) | 205 OK (1 skip) |
| Both immutability guards | 13 OK | 13 OK |
| `intake.py` / `candidate_ops.py` / `security_review_ops.py` / `alpha_ops.py` / `release_authority_ops.py` verify | all clean | all clean |

## 21. Limitations

Mechanical validation ends at the record: the tools verify that an
authority is named, assigned, and acted — not that a name is a real,
independent person (Phase 9's honesty boundary, inherited). The
sufficiency measures derive only what the committed registers can
support (e.g. hardware diversity counts gate-eligible accepted hardware
intakes; installation success counts bound Journey-A SUCCESS reports);
an owner may judge a dimension needs a richer measure when defining
thresholds. Expiry evaluation is only as honest as the
operator-stated `--as-of` date — the commit remains the tamper-evident
time. And the state machine governs the *decision*; the candidate
lifecycle authority remains Phase 10's.

## 22. Current external evidence status

**None.** Zero intakes of any kind; the Phase 9 ledger holds zero
entries and is byte-identical to its Phase 9 state. Every external gate
remains NOT_RUN; the security gate remains AWAITING_EXTERNAL_EVIDENCE;
the Alpha program remains READY_FOR_TESTERS with zero reports; no
authority is assigned; no policy, risk, authorization, revocation, or
resolution record exists.

## 23. Current candidate status

From `qualification/phase13/authorization-status.json`, derived and
reproducible: authorization state **EVIDENCE_PENDING** ("zero
gate-eligible accepted external intakes exist; every gate awaits its
owner, and absence authorizes nothing"), candidate decision
**REQUIRES_MORE_EVIDENCE**, floor unsatisfied with all five sources
missing, sufficiency **SUFFICIENCY_UNDETERMINED** under
**SUFFICIENCY_POLICY_UNDEFINED**, standing authorization **none**,
every authority **ROLE_DEFINED**. Conditions 1, 2, 7, 8 TRUE (on
absence), 3, 4, 5, 9, 10 UNDETERMINED, 6 FALSE — unchanged from
Phases 9–12, none weakened.

**PHASE 13 DOES NOT AUTHORIZE THE ARTIFACT.**

## 24. Exact next required action

Unchanged by design: **commission the independent security review**
(`qualification/phase11/security-review/REQUEST.md`) — the
deterministic ladder still names it first. For this phase's own thread,
two actions belong to people outside this repository: the Alpha program
owner records real sufficiency thresholds (`release_authority_ops.py
record policy`), and the organization records authority assignments
(`record assignment`) when real identities exist. Until an owner acts,
the correct description of the candidate is the status at the top of
this report.
