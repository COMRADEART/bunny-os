# Sustainability

## What must be sustained

Stable OS maintenance, security response, release signing, infrastructure, documentation, hardware testing, accessibility, application curation, and — if it is ever launched — optional service operations.

## Current capacity

One maintainer. No funded support rota, no on-call rotation, no second signer for release keys, no hardware laboratory, and no independent security or accessibility auditor under contract.

This is the binding constraint on Phase 7. Every capability in this phase adds ongoing obligation: an enrolled fleet expects policy delivery, a hosted sync service expects availability and abuse response, and an OEM partner expects security advisories with an SLA. Shipping any of them without capacity would create a support commitment the project cannot honour, which is why `supportCapacityConfirmed` is `false`.

## Possible funding models

Donations, sponsorship, paid support, OEM support contracts, enterprise management subscriptions, optional encrypted sync subscriptions, training, consulting.

No revenue estimate appears here. None has been measured.

## Free and local, permanently

Bunny OS itself, local Bunny use, local models, recovery, security updates, local backups, local administration, and community documentation.

Core privacy and security protections do not depend on payment. Security updates are not a paid tier. Encryption, recovery, local-only operation, and the privacy defaults are part of the OS.

## Potentially paid

A managed fleet console, hosted encrypted sync, OEM engineering support, enterprise support, extended maintenance agreements.

## The line that will not move

The free OS is not degraded to drive subscriptions. Concretely: no core function is withheld to encourage account creation, no-account mode stays fully supported, and `docs/LOCAL_ONLY_AND_BUNNY_DISABLED.md` remains a qualified configuration rather than a downgrade.

## Maintenance burden

Not estimated in hours. The honest statement is that the Phase 7 surface — OEM profiles, factory tooling, a policy agent, a fleet control plane, a multi-tenant service, and an encrypted sync service — is larger than the current maintainer capacity, and that a pilot would require either additional maintainers or a reduced scope. Producing a number without a staffed team to measure against would be invented.
