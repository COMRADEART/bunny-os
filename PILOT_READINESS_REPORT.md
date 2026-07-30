# Pilot readiness report

Date: 2026-07-30. Recommendation: **NO-GO.** Evidence: `operations/data/phase7-readiness.json`. Command: `make pilot-readiness`.

No pilot may begin. Do not manufacture devices, deploy fleets, or launch a hosted sync service.

## Gate state, 2026-07-30

```text
$ python scripts/release.py gate --kind oem-pilot          # BLOCKED
$ python scripts/release.py gate --kind enterprise-pilot    # BLOCKED
$ python scripts/release.py gate --kind sync-pilot          # BLOCKED
$ python scripts/release.py gate --kind stable-release      # NO-GO
$ python scripts/release.py gate --kind qualification-candidate  # BLOCKED
$ python scripts/release.py gate --kind source              # PASS
```

Each pilot gate reports `BLOCKED` on the stable gate **plus** its own additional
requirements, none of which is satisfied:

| Gate | Additional requirements | Satisfied |
|---|---|---|
| `oem-pilot` | 6 — qualified hardware model, OEM recovery validation, signed OEM profile, factory finalisation on hardware, branding and licensing approval, named support owner | **0** |
| `enterprise-pilot` | 6 — fleet control plane implemented, tenant isolation penetration test, enrolment service deployed, console role testing, incident-response owner, support capacity | **0** |
| `sync-pilot` | 7 — independent cryptographic review, operated sync service, key-recovery drill, deletion drill, service privacy review, data-residency disclosure, incident-response owner | **0** |

The gates are **deliberately not nested into one another's success**. A passing
source gate contributes nothing to a pilot; nor does a passing candidate gate.
`pilot-closure-assertion` additionally fails the build if any pilot gate reports GO
while the stable gate blocks, whatever the pilot's own requirements say — asserted
rather than relied on, because those requirements are read from a data file a change
could populate.

`tests/pilot_gates/` proves that satisfying **every** pilot requirement is still not
enough while the stable gate blocks: the resulting `unmet` list has exactly one
entry, and it is `stable-release`.

## What each pilot is waiting on, specifically

- **OEM.** A physical device. Two of its six requirements need hardware nobody has,
  and the anti-tivoisation question in `reviews/legal/REQUEST.md` gates
  `brandingAndLicensingApproval`. No OEM agreement should be signed with it
  outstanding.
- **Enterprise.** A deployed control plane and an adversarial multi-tenant isolation
  test performed by someone other than the author. Neither exists; nothing is
  operated.
- **Sync.** `independentCryptographicReview`, which is prepared and not sent
  (`reviews/cryptography/REQUEST.md`), plus an operated service. The subsystem has
  never run.

The project's recommendation remains to **operate none of the Phase 7
capabilities**. That is a legitimate answer and is the standing one.

## Entry gates

Eight of eleven unmet.

| Gate | State | Why |
|---|---|---|
| `stableReleasePublished` | **unmet** | `STABLE_RELEASE_GO_NO_GO.md` records NO-GO. No stable version, tag, or candidate exists |
| `signedStableArtifacts` | **unmet** | `build/keys/` holds no release public key; no candidate artifact has been signed |
| `reproducibleBuildEvidence` | **unmet** | `make reproducible-build-check` fails closed by design; a second independent builder comparison has never run |
| `postReleaseSecurityReview` | **unmet** | Document does not exist; no release occurred |
| `postReleasePrivacyReview` | **unmet** | Document does not exist; no release occurred |
| `phase7SecurityReview` | met | `PHASE_7_SECURITY_REVIEW.md`; no unresolved Blocker or Critical in Phase 7 source |
| `phase7PrivacyReview` | met | `PHASE_7_PRIVACY_REVIEW.md`; administrator visibility documented |
| `multiTenancyIsolationTests` | met | `tests/multitenancy`, 23 cases including 8 adversarial |
| `syncCryptographyIndependentReview` | **unmet** | Not commissioned; no reviewed backend installed |
| `oemRecoveryValidation` | **unmet** | No physical hardware qualified; no recovery media booted |
| `supportCapacityConfirmed` | **unmet** | One maintainer, no funded support rota |

## Per-pilot gates

```text
make gate-oem-pilot          BLOCKED  4 unmet gates
make gate-enterprise-pilot   BLOCKED  5 unmet gates
make gate-sync-pilot         BLOCKED  4 unmet gates
make gate-phase-7            BLOCKED  inherits gate-stable-release
```

Each gate names its unmet conditions and the reason for each, so the output is actionable rather than a bare failure.

## Pilot order

Smallest first, and skipping is refused:

```text
internal-pilot          max 25 devices
small-community-pilot   max 100
research-lab-pilot      max 100
small-business-pilot    max 250
oem-engineering-pilot   max 50
```

## Success criteria

Operational only: enrolment success, policy delivery success, update success, rollback success, recovery success, support ticket categories, service availability, hardware reliability.

Refused: productivity, output volume, engagement, session length, prompt counts, keystrokes, attention, and performance ratings. Measuring people requires a separate research protocol with its own explicit consent, which Phase 7 does not provide and does not claim to.

## Required definitions

Every pilot must state scope, duration, device count, supported hardware, support owner, success criteria, privacy notice, incident process, rollback plan, and exit plan. A missing field blocks the pilot regardless of gate state.

An internal pilot definition is recorded in `operations/data/phase7-readiness.json` as a template. It is not approved and cannot run.

## No demand, scale, or revenue estimates

This report contains no forecast of participants, deployment scale, adoption, or revenue. None has been measured. `enterprise/pilot.py` enforces device ceilings but expresses no expectation that any device will be enrolled.

## What would change this recommendation

In order of dependency:

1. Close the five stable-release blocker codes and the 31 missing evidence entries.
2. Resolve the 59 fixable vulnerability findings, including 8 Critical and 28 High, or record a reviewed waiver.
3. Produce reproducibility evidence from two independent builders.
4. Publish a signed stable release and complete the post-release security and privacy reviews.
5. Commission an independent cryptographic review of the sync design.
6. Qualify at least one hardware model, including validated recovery.
7. Confirm support capacity, or reduce Phase 7 scope to what one maintainer can sustain.

Steps 1 to 4 are Phase 6 work, not Phase 7 work. Phase 7 cannot unblock itself.

## Maturity ladder, 2026-07-30

These five states are distinct and this repository is at the first. Every
document listed below reports the same position; if any of them disagrees, that
document is wrong.

| State | Meaning | Bunny OS |
|---|---|---|
| **Source implemented** | Design, schemas, validators, tests and documentation exist and pass | **yes** — Phases 1–7 |
| **Runtime validated** | The software has been built and observed doing the thing on real or virtual hardware | **partial** — images build from a digest-pinned base and boot under KVM; installation, encryption, update, rollback and recovery matrices have not run |
| **Release qualified** | `gate-stable-release` reports `GO` against a complete evidence record | **no** — 2 of 20 evidence categories pass |
| **Pilot approved** | A pilot gate reports `GO` and a controlled pilot has separate approval | **no** — all three gates `BLOCKED` |
| **Production operated** | A service or fleet is actually being run and supported | **no** — nothing is operated, and operating nothing remains a legitimate outcome |

Agreeing documents: `README.md`, `NEXT_PHASE.md`, `docs/PHASE_7_BASELINE.md`,
`PHASE_7_REPORT.md`, `KNOWN_LIMITATIONS.md`, `PILOT_READINESS_REPORT.md`.

Current authority for the closure position: `RELEASE_BLOCKER_CLOSURE_REPORT.md`
and `STABLE_EVIDENCE_REPORT.md`.

## Separated pilot gates, 2026-07-30

`scripts/phase7.py pilot-gate` remains in place and is unchanged. A second,
separated gate now runs alongside it: `scripts/release.py gate --kind <pilot>`,
which requires a passing **stable release gate** plus each pilot's own
additional requirements. Both must pass. `make gate-oem-pilot`,
`make gate-enterprise-pilot` and `make gate-sync-pilot` run both.

The point of the separation is that a passing Phase 7 *source* gate contributes
nothing to a pilot decision. Source completeness was never evidence that a
device may be manufactured, a fleet deployed, or a service launched.

| Gate | Additional requirements | Met |
|---|---|---|
| OEM pilot | qualified hardware model, OEM recovery validation, signed OEM profile, factory finalisation on hardware, branding and licensing approval, named support owner | **0 of 6** |
| Enterprise pilot | fleet control plane implemented, tenant isolation penetration test, enrolment service deployed, console role testing, incident-response owner, support capacity | **0 of 6** |
| Sync pilot | independent cryptographic review, operated sync service, key-recovery drill, deletion drill, service privacy review, data-residency disclosure, incident-response owner | **0 of 7** |

Every unmet requirement carries a recorded note explaining why, and
`tests/pilot_gates/` asserts both that no requirement is claimed as satisfied and
that each unmet one has a note.

The three mandated adversarial cases are tested and all three are refused: pilot
approval without a stable release, OEM approval without hardware, and sync
approval without a cryptographic review.

**Recommendation unchanged: begin no pilot.**
