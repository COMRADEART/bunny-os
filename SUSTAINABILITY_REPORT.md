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
