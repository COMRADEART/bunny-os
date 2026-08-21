# Phase 8 workstreams

Six workstreams, each with its own owner, evidence location and status. Their
evidence is never combined into one generic "release ready" result — the
decision matrix (`PHASE8_EXTERNAL_RELEASE_DECISION_MATRIX.md`) cites each row
separately, and §21's question is answered per gate.

Every workstream action begins by naming the artifact:
**`e906a48793d7`**, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
source commit `e906a48793d74544b39c14cc3e35e0654f5311e2`, UNSIGNED.
"Latest build" identifies nothing and is refused.

---

## A — Independent security review

| | |
| --- | --- |
| Owner | an external reviewer who is no project principal — **does not exist yet** |
| Scope | the subject artifact's vulnerability position: 8 Critical + 36 High findings, exposure, exploitability, dispositions |
| Required inputs | `qualification/phase8/security-review/` package (artifact identity, per-finding inventory with the Phase 7 per-binary analysis preserved) |
| Expected output | one of APPROVED / APPROVED_WITH_CONDITIONS / BLOCKED / MORE_EVIDENCE_REQUIRED, with per-condition records (finding, severity, remediation, owner, artifact, decision authority) |
| Evidence location | `qualification/phase8/security-review/` (package), `operations/data/independent-reviews.json` (result) |
| Status | **NOT_RUN** — package prepared; no reviewer exists |

## B — Physical hardware qualification

| | |
| --- | --- |
| Owner | whoever operates a physical x86-64 UEFI machine — **no machine exists yet** |
| Scope | the §7 journey per machine, from the subject ISO (`823d50ca…`), medium digest verified on the writing host and from the written medium |
| Required inputs | `qualification/phase8/hardware/PROTOCOL.md`, a machine, the ISO |
| Expected output | one hardware record per machine ID + per-dimension rows in `qualification/phase8/hardware-matrix.json` |
| Evidence location | `qualification/phase8/hardware/` and the matrix |
| Status | **NOT_RUN** — protocol and matrix schema exist; zero machines |

## C — Production signing readiness

| | |
| --- | --- |
| Owner | the key authority — **does not exist yet** |
| Scope | establish a production key under controlled access; sign the exact artifact bytes; verify independently of the signing command |
| Required inputs | `qualification/phase8/signing/SIGNING_READINESS.md` procedure; the artifact digests |
| Expected output | a `signing-record.json` binding digest → signer authority → signature id → independent verification, dated. SIGNING DRILL and PRODUCTION ARTIFACT SIGNED are separate categories and remain so |
| Evidence location | `qualification/phase8/signing/` — public identities, fingerprints and verification results only; **no private key material anywhere** |
| Status | **NOT_RUN** — artifact remains UNSIGNED; the development drill (9/9, constructed inputs) satisfies nothing here |

## D — Second-signer approval

| | |
| --- | --- |
| Owner | a second person with release authority — **does not exist yet** |
| Scope | an independent approval that names the same artifact digest, not the branch, not a CI run |
| Required inputs | the artifact digest; the first approval record |
| Expected output | an approval record: digest, first approver, second approver, decision, date |
| Evidence location | `qualification/phase8/signing/APPROVALS.md` + record file |
| Status | **NOT_RUN** — one person |

## E — Controlled Alpha tester validation

| | |
| --- | --- |
| Owner | Alpha testers under the controlled protocol — **zero enrolled** |
| Scope | journeys A–E of `qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md`, operationalized by `qualification/phase8/alpha/OPERATIONS.md` (tester IDs, no PII, digest binding, measured vs user-reported separation) |
| Required inputs | the ISO + its digest, the scope document, the limitations document |
| Expected output | per-tester journey records and triaged findings (`REPORT_TEMPLATE.json` shape) |
| Evidence location | `qualification/phase8/alpha/reports/` |
| Status | **NOT_RUN** — protocol operationalized; zero reports |

## F — Release governance and authorization

| | |
| --- | --- |
| Owner | the release decision authority (the project owner, for the Alpha class) |
| Scope | keep the blocking conditions fixed; accept or refuse exceptions with the §15 record; move the final status only on evidence from A–E |
| Required inputs | the decision matrix rows from A–E |
| Expected output | the final §19 status; if AUTHORIZED, the §21 record of which humans decided what, when, about which bytes |
| Evidence location | `PHASE8_EXTERNAL_RELEASE_DECISION_MATRIX.md`, `PHASE8_EXTERNAL_VALIDATION_AND_ALPHA_AUTHORIZATION.md` |
| Status | **IN PROGRESS** — governance artifacts being laid down; no authorization possible while A–E are NOT_RUN |
