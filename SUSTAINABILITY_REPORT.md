# Sustainability report

Date: 2026-07-29. Companion document: `docs/SUSTAINABILITY.md`.

## Current capacity

One maintainer.

No funded support rota, no on-call rotation, no second signer for release keys, no hardware laboratory, no independent security auditor under contract, no accessibility auditor under contract, and no operations team.

## Why this is the binding Phase 7 constraint

Every Phase 7 capability creates a *continuing* obligation, not a one-time delivery:

| Capability | Ongoing obligation |
|---|---|
| Stable OS | Security response, maintenance releases, support lifecycle |
| OEM partnership | Security advisories with an SLA, driver and firmware regression handling, per-model recovery validation |
| Enterprise fleet | Policy delivery availability, certificate rotation, audit retention, incident response |
| Hosted sync | Availability, abuse response, backup and disaster recovery, key-loss support, data-deletion compliance |
| Enterprise console | Web application security patching, dependency updates, tenant support |

A single maintainer cannot honour a security-advisory SLA to an OEM partner while also operating a multi-tenant service and maintaining a stable OS. Shipping any of these without capacity would create commitments the project cannot meet, and the failure mode would be an unpatched vulnerability in a device someone bought.

This is why `supportCapacityConfirmed` is `false` and why `make gate-enterprise-pilot` and `make gate-sync-pilot` fail on it.

## What must be sustained

Stable OS maintenance, security response, release signing, infrastructure, documentation, hardware testing, accessibility, application curation, and optional service operations.

Release signing deserves specific mention: there is currently one potential signer and no key ceremony, no offline key storage procedure, and no rotation rehearsal. A single signer is a single point of failure for the entire update trust chain.

## Possible funding models

Donations, sponsorship, paid support, OEM support contracts, enterprise management subscriptions, optional encrypted sync subscriptions, training, consulting.

No revenue estimate appears here, because none has been measured. No customer, sponsor, or partner exists.

## Free and local, permanently

Bunny OS itself, local Bunny use, local models, recovery, security updates, local backups, local administration, and community documentation.

Core privacy and security protections do not depend on payment. Security updates are not a paid tier. Encryption, recovery, local-only operation, and the privacy defaults are part of the operating system, not an upsell.

## Potentially paid

A managed fleet console, hosted encrypted sync, OEM engineering support, enterprise support, extended maintenance agreements.

## The line that does not move

The free OS is not degraded to drive subscriptions. Concretely, and checkable in code:

- No-account mode remains fully supported. `operations/modes.py` qualifies `local-only` and `bunny-disabled` as first-class configurations.
- Nothing syncs by default, and no core function is withheld to encourage account creation.
- Recovery never depends solely on a cloud service.
- Local-only AI is a supported policy, not a limitation.

## Maintenance burden

Not expressed in hours. The honest statement is that the Phase 7 surface — OEM profiles and factory tooling, a policy agent, a fleet control plane, a multi-tenant service, an encrypted sync service, and an enterprise console — is larger than current capacity, and that a pilot requires either additional maintainers or a reduced scope.

Producing an hour figure without a staffed team to measure against would be invented, and `docs/PHASE_7_BASELINE.md` already declined to invent one.

## Recommendation

Before any pilot, decide explicitly which Phase 7 capabilities the project will actually operate. The design supports all of them; the project can currently operate none of them. A reduced scope — for example, OEM profiles and air-gapped management, with no hosted service at all — would be sustainable in a way that a hosted multi-tenant sync service would not.

## Sustainability decision, 2026-07-30

Updated from verified information only. Where a number is not known, it is
recorded as not known rather than estimated, because an invented operating cost
would be worse than an absent one.

### Current maintainers

**One.** No funded rota, no on-call, no second reviewer. Every review in this
repository is a self-review, which `release/reviews.py` now refuses to record as
independent.

### Available release signers

**One potential signer. Zero provisioned keys.**

Four of the seven signing roles — `osRelease`, `updateMetadata`,
`recoveryImage`, `oemProfile` — require two-person approval, and
`release/signing.py` refuses a production key record for those roles without it.
With one person those roles **cannot be provisioned at all**. This is not a
policy that could be relaxed; it is the reason a compromised or unavailable
single signer would be unrecoverable.

### Available test hardware

**None.** `operations/data/hardware-evidence.json` contains zero reports. One
Windows workstation hosts a Fedora 44 WSL2 builder with nested KVM, 22 cores and
895 GB free. That builder can build and boot virtual machines. It is not test
hardware and cannot produce a physical result.

### Infrastructure actually provisioned

| Item | State |
|---|---|
| Build machine | one, shared with the developer's workstation |
| CI | GitHub Actions workflows defined; no self-hosted runner |
| Registry | none |
| Update server | none |
| Fleet control plane | none — ADR-023 places it outside this repository and it does not exist |
| Enrolment service | none |
| Sync service | none |
| Signing infrastructure | none; no hardware token, no HSM, no signing service |
| Artifact hosting | none |

### Recurring costs actually incurred

**None.** No service is operated, no infrastructure is rented, no domain is
registered for a service, and no support commitment exists. The build machine
already existed.

This is not a claim that operating would be cheap. It is a statement that
nothing has been spent, so no cost model derived from experience exists.

### Independent-review costs

**Not quoted.** Four reviews are prepared and none has been priced, because
pricing one requires approaching a reviewer and none has been approached. Any
figure here would be invented.

What is known is the ordering: the cryptographic review blocks the sync pilot
outright, and the security review is the only route by which any of the 8
Critical findings can become non-blocking.

### Support capacity

**Unconfirmed, and the honest reading is that it is zero for a supported
release.** A stable release implies a security-response commitment. With one
maintainer, no rota and no second signer, a security fix requiring a signed
update could not be issued if that person were unavailable.

### Release-maintenance burden

Per release, from what this phase actually observed rather than from an estimate:

- a full profile build takes roughly 10 minutes of machine time, and three
  profiles were built;
- SBOM generation over a 1.85 GB archive produces a 60 MB SPDX document;
- vulnerability scanning, licence scanning and inspection add several minutes;
- a two-workspace reproducibility comparison requires hashing both archives in
  full;
- the twelve-artifact candidate set requires a live ISO and a recovery ISO that
  have not been built, so the full candidate cost is **not yet known**.

Human time is the real burden and it is not measured, because no release has
been made.

### Decision

**Operate no Phase 7 services.**

This is one of the five permitted conclusions and it is the correct one. Every
alternative requires capacity that demonstrably does not exist:

| Option | Blocked by |
|---|---|
| Operate OEM tooling only | no hardware, no `oem-` key, no support owner, unresolved anti-tivoisation question |
| Operate enterprise tooling only | no control plane, no enrolment service, no penetration test, no incident-response owner |
| Operate encrypted sync only | no cryptographic review, no service, no key-recovery or deletion drill, no residency disclosure |
| Operate a limited combination | strictly harder than any single option above |
| **Operate none** | **nothing — this is achievable today** |

Operating none is not a failure state. The Phase 7 source is complete, tested
and correct; it simply is not accompanied by the capacity to run the services it
describes, and the gates enforce that rather than describing it.

### What would change this decision

In order of leverage:

1. **A second person.** It unblocks two-person signing, makes independent
   builder reproducibility trivial, and converts support capacity from zero to
   something. It is the single highest-leverage change available.
2. **One x86-64 UEFI machine.** Unblocks two evidence categories and the OEM
   pilot's first requirement.
3. **Funding for one independent review.** The security one, because it is the
   only route to the Critical findings.

None of these is an engineering task, which is why they are recorded here rather
than in `NEXT_PHASE.md` as work items.
