# Pilot programme

Implementation: `enterprise/pilot.py`. Evidence: `operations/data/phase7-readiness.json`. Tests: `tests/pilot`.

**No pilot may begin.** `make pilot-readiness` reports NO-GO and `make gate-oem-pilot`, `make gate-enterprise-pilot`, and `make gate-sync-pilot` all fail closed.

## Order

```text
internal-pilot            max 25 devices
small-community-pilot     max 100
research-lab-pilot        max 100
small-business-pilot      max 250
oem-engineering-pilot     max 50
```

Smallest first. `assert_pilot_order` refuses a larger pilot before its predecessors have completed, because "run a small pilot first" is only a control if skipping it fails.

## Every pilot must define

Scope, duration, device count, supported hardware, support owner, success criteria, privacy notice, incident process, rollback plan, exit plan. A missing field blocks the pilot.

## Success criteria are operational only

`enrolmentSuccessRate`, `policyDeliverySuccessRate`, `updateSuccessRate`, `rollbackSuccessRate`, `recoverySuccessRate`, `supportTicketCategories`, `serviceAvailability`, `hardwareReliability`.

Productivity, output volume, engagement, session length, prompt counts, keystrokes, attention, and performance ratings are refused. Measuring people requires a separate research protocol with its own explicit consent, which Phase 7 does not provide.

## Entry gates

Eleven gates. Current state from `operations/data/phase7-readiness.json`:

| Gate | State |
|---|---|
| `stableReleasePublished` | false — `STABLE_RELEASE_GO_NO_GO.md` records NO-GO |
| `signedStableArtifacts` | false — no release public key, no signed candidate |
| `reproducibleBuildEvidence` | false — `make reproducible-build-check` fails closed by design |
| `postReleaseSecurityReview` | false — document does not exist, no release occurred |
| `postReleasePrivacyReview` | false — document does not exist, no release occurred |
| `phase7SecurityReview` | true — `PHASE_7_SECURITY_REVIEW.md` |
| `phase7PrivacyReview` | true — `PHASE_7_PRIVACY_REVIEW.md` |
| `multiTenancyIsolationTests` | true — `tests/multitenancy` passes |
| `syncCryptographyIndependentReview` | false — not commissioned, no reviewed backend installed |
| `oemRecoveryValidation` | false — no physical hardware qualified, no recovery media booted |
| `supportCapacityConfirmed` | false — see `SUSTAINABILITY_REPORT.md` |

## No demand or scale estimates

This document contains no forecast of participant numbers, deployment scale, or revenue. None has been measured and inventing one would misrepresent the project's position.
