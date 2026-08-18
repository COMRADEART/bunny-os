<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 8 — External Validation & Alpha Authorization

## STATUS: **PHASE 8 — EXTERNAL VALIDATION IN PROGRESS**

Not BLOCKED — no external actor has returned a blocking result. Not
AUTHORIZED — no external actor has returned anything at all. Every external
gate is NOT_RUN, each now with a package, protocol, or record format its
owner can act on without further engineering work.

---

## 1. Executive summary

Phase 8's question is §21's: *is there sufficient independent evidence and
authorized approval to distribute this exact artifact as a controlled
Alpha?* The honest answer today is **no evidence either way** — the
independent actions have not happened — and this phase's work is that the
question is now fully *askable*: every gate has an owner, an input package,
a record shape, and blocking conditions fixed before any feedback exists.

What Phase 8 laid down, none of it moving a status it has no authority over:

* the ten Alpha-release blocking conditions, committed before any tester or
  reviewer exists (§17);
* six workstreams, each with owner, scope, inputs, output, evidence
  location, status (§3 of the brief; `qualification/phase8/workstreams/`);
* a reproducible security review package: all 44 Critical/High findings
  with per-binary analysis preserved uncollapsed, 41 REQUIRES_REVIEW,
  3 UNKNOWN, zero NOT_AFFECTED, zero guesses (§5–6);
* the hardware protocol and an empty hardware matrix whose validation rules
  (PASS needs evidence; NOT_SUPPORTED needs grounding; native-3D ≠
  fallback-3D) exist before any machine does (§7);
* signing readiness with drill and production kept as separate categories,
  and second-signer records whose absence is the measured state (§8–10);
* the operational Alpha program: tester IDs without PII, digest-bound
  reports, measured/user-reported separation, and the two tester-facing
  documents — the scope that never says "works on PCs" and the limitations
  translated into practical consequences (§11, §14–15);
* and one live demonstration of the standing machinery: both
  evidence-immutability guards **refused Phase 8's own files** as additions
  to a frozen tree until the new tree was declared deliberately — the
  refusal a new tree is supposed to earn.

No closed Phase 7 gate was reopened. No engineering result was rerun for
green output. The subject artifact was not rebuilt, replaced, or re-tagged.

## 2. Phase 7 baseline

`PHASE 7 — ENGINEERING BLOCKERS CLOSED` at head `fef665c4`; certified commit
`e65e3df0` (2 × 6072 tests, zero failures, ext4 as `bunny`). All seven
engineering gates PASS with negative controls. Closed gates stay closed;
per §2 they reopen only on regression or artifact change, neither of which
occurred.

## 3. Subject artifact identity

| | |
| --- | --- |
| Identifier | `e906a48793d7` |
| Image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| OCI archive | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Signing status | **UNSIGNED** |

"Latest build" is not an identifier anywhere in this phase; every workstream
document opens with the digests above.

## 4. Artifact immutability

Frozen: not rebuilt, not silently replaced, no PASS transferred. The digests
were last recomputed from bytes on 2026-08-18
(`qualification/phase7/baseline/freeze.log`); the retained archive is the
authority. Any new artifact receives a new identity, digest, provenance and
qualification boundary — the policy is restated in every Phase 8 workstream
so no external actor can be handed ambiguous bytes.

## 5. Independent security review

**NOT_RUN — no reviewer exists.** The package is ready and reproducible:
`qualification/phase8/security-review/` (PACKAGE.md for the reviewer,
review-package.json built deterministically by `build_package.py`, eight
structural invariants enforced in the certified suite). Allowed outcomes:
APPROVED / APPROVED_WITH_CONDITIONS / BLOCKED / MORE_EVIDENCE_REQUIRED,
recorded in `operations/data/independent-reviews.json` binding to the image
digest. Until that record exists this gate is NOT_RUN, and this report does
not perform the review and label it independent.

## 6. Critical and High finding disposition

44 findings (8 Critical, 36 High). Dispositions: **41 REQUIRES_REVIEW,
3 UNKNOWN, 0 AFFECTED, 0 NOT_AFFECTED** — nothing replaced UNKNOWN without
evidence, and nothing was dispositioned by the party that must not do it.
The Phase 7 per-binary analysis is preserved uncollapsed: six advisories
split podman (at/above fix) from skopeo (affected); the three pseudo-version
rows (podman's own two advisories and `docker/docker`) are explicitly
UNKNOWN pending a commit-level dist-git comparison — named as the reviewer's
question, not guessed.

## 7. Physical hardware results

**NOT_RUN — zero machines.** `qualification/phase8/hardware-matrix.json`
exists with an empty machines list, eighteen dimensions, and validation
rules tested before any machine: PASS requires evidence, NOT_SUPPORTED must
cite the identity field grounding it, native 3D and fallback 3D are separate
rows, media digests verified on both ends. The protocol
(`qualification/phase8/hardware/PROTOCOL.md`) assigns HW-NNN identities with
records written before first boot. Nothing was inferred from the VM.

## 8. Signing readiness

`qualification/phase8/signing/SIGNING_READINESS.md`: the four-step procedure
(exact digest recomputed by the signer → authorized authority → detached
signature → verification independent of the signing command), the record
shape, and the absolute key-hygiene rule (private keys never in repository,
evidence, screenshots, logs, shell history, or reports — evidence carries
public identities, fingerprints and verification results only).

## 9. Production signing status

**NOT_RUN. The artifact remains UNSIGNED.** Zero signature files (measured
Phase 6, unchanged). The development drills — including the two-person drill
— remain SIGNING DRILL category and satisfy nothing in the PRODUCTION
ARTIFACT SIGNED category. `signing-record.json` does not exist; its absence
is the state.

## 10. Second approval

**NOT_RUN — one person.** `qualification/phase8/signing/APPROVALS.md`
defines the record: both approvers independently recompute and name the same
digest; CI green is not an approver; approval of a branch is not approval of
bytes. `approval-record.json` does not exist; its absence is the state.

## 11. Alpha tester protocol

Operational: `qualification/phase8/alpha/OPERATIONS.md` +
`REPORT_TEMPLATE.json` on top of the Phase 7 protocol. Tester IDs `T-NNN`
with no PII in evidence; every report binds to the digest the tester
computed themselves; journeys A–E plus exploratory reports; measured and
user-reported evidence in separate arrays, never converted into each other.

## 12. Alpha tester results

**None. Zero testers enrolled, zero reports.**
`qualification/phase8/alpha/reports/` is empty and says so. Nothing was
converted from absence into anything.

## 13. Defect triage

The §14 scheme is in force (eleven categories; reproduction confidence
CONFIRMED / LIKELY / REPORTED / UNREPRODUCED, with UNREPRODUCED kept as user
evidence, never discarded as invalid). No findings exist to triage.

## 14. Supported Alpha scope

`qualification/phase8/alpha/RELEASE_SCOPE.md`: VM (QEMU/KVM q35, OVMF,
virtio, llvmpipe) is the only tested environment; zero physical machines;
no verified native-3D configuration; updates NOT_SUPPORTED by recorded
decision; recovery engineering-qualified but no recovery media ships;
unsigned; security review pending. The tester knows what is experimental —
which is everything outside the VM envelope.

## 15. Known limitations

`qualification/phase8/alpha/ALPHA_KNOWN_LIMITATIONS.md` — the technical
state translated into practical consequences: this build never updates
itself including security fixes, verify the digest yourself, there is no
recovery kit, encrypted data is exactly as recoverable as the passphrase,
you may be the first person on your hardware, the TPM first-boot countdown
is designed behavior, expect 3D to decline politely, large-text and
high-contrast are verified while most other assistive flows are not.
Internal implementation speculation appears nowhere in it.

## 16. Release decision matrix

`PHASE8_EXTERNAL_RELEASE_DECISION_MATRIX.md` — ten rows, owner and decision
authority per row. PASS rows: exactly two, both internal (artifact identity;
the closed Phase 7 certification). Every external row: NOT_RUN with its
owner named. The rows are not averaged.

## 17. Blocking conditions

`qualification/phase8/conditions/ALPHA_RELEASE_BLOCKING_CONDITIONS.md`,
committed before any Alpha action (`17a34aa6`), ten conditions, none
weakened, no exception recorded. Scored today: conditions 1, 2, 7 and 8 are
**true** (review and approvals absent — absence blocks, it does not
authorize); conditions 3–5, 9 and 10 are undetermined for lack of any
testing evidence; condition 6 is false (identity verifies). Authorization
requires all ten false, on evidence.

## 18. Evidence inventory

| Path | What |
| --- | --- |
| `qualification/phase8/conditions/` | the ten blocking conditions, committed first |
| `qualification/phase8/workstreams/WORKSTREAMS.md` | six workstreams with owners and statuses |
| `qualification/phase8/security-review/` | PACKAGE.md, review-package.json, build_package.py |
| `qualification/phase8/hardware/PROTOCOL.md` + `qualification/phase8/hardware-matrix.json` | the protocol and the empty matrix |
| `qualification/phase8/signing/` | SIGNING_READINESS.md, APPROVALS.md; the two record files deliberately absent |
| `qualification/phase8/alpha/` | OPERATIONS.md, REPORT_TEMPLATE.json, RELEASE_SCOPE.md, ALPHA_KNOWN_LIMITATIONS.md, empty reports/ |
| `PHASE8_EXTERNAL_RELEASE_DECISION_MATRIX.md` | the decision matrix |
| `tests/release/test_review_package.py`, `test_hardware_matrix.py` | 16 structural invariants, in the certified suite |
| guard maintenance | both immutability guards declared `qualification/phase8/` after refusing it — the refusal and the declaration are the audit trail |

Validated on the reference target (ext4, as `bunny`) at `9c6cfacb`: the
release suite (111 tests) and both portability validators, clean. The closed
Phase 7 certification was not rerun.

## 19. Final disposition

# PHASE 8 — EXTERNAL VALIDATION IN PROGRESS

The strongest status this phase could truthfully reach without external
actions, reached. Not STABLE RELEASE, not PRODUCTION READY, not ALPHA
RELEASE AUTHORIZED — the unit of release authority is the exact artifact
plus its evidence plus the required human decisions, and the human decisions
have not happened. No approval was manufactured, no review simulated, no
hardware claimed, no unsigned byte called signed, no VM allowed to stand in
for metal, and no absent tester counted as a quiet yes.

What the owners pick up from here:

| Owner needed | Their input is ready at |
| --- | --- |
| Independent security reviewer | `qualification/phase8/security-review/PACKAGE.md` |
| A physical machine's operator | `qualification/phase8/hardware/PROTOCOL.md` |
| Key authority | `qualification/phase8/signing/SIGNING_READINESS.md` |
| A second approver | `qualification/phase8/signing/APPROVALS.md` |
| Alpha testers | `qualification/phase8/alpha/` — scope and limitations first |
