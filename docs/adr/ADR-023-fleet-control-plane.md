# ADR-023: Fleet control plane boundary

- Status: accepted as design; no server exists in this repository
- Date: 2026-07-29

## Decision

The organisation control plane is a separate repository, a separate deployment lifecycle, and a separate trust domain. This repository holds only the device side — `enterprise/` — plus the protocol schemas both sides share. No server code lives in `services/`, `build/`, or any boot or recovery path.

Three components are named as independent boundaries and are not created here: `bunny-fleet-server`, `bunny-enrolment-service`, and `bunny-enterprise-console`. Each has its own operational risk, its own dependency surface, and — if hosted — its own availability and abuse-response obligations. Mixing them into the OS repository would make an OS release depend on a service release.

Update rings sit above the existing update channel rather than replacing it. The manifest keeps its closed three-value channel enum and its mandatory Ed25519 verification; a ring decides only when a device is offered an already-signed manifest. An organisation gains scheduling control and no influence over trust.

## Why not one repository

*A monorepo* was rejected because the trust boundaries differ in kind. The OS image is signed by release keys and installed by `bootc`; the control plane is a network service with a database and tenants. A vulnerability in a tenant-scoped API should not require an OS respin, and an OS release should not wait on a console deploy.

*Extending the update manifest with ring fields* was rejected because it would bump a schema every organisation's update agent must accept, and because it would place fleet-controlled data inside the artifact whose signature is the root of update trust. Keeping rings outside the manifest means no fleet input reaches the trust decision.

*A generic remote management protocol* was rejected in favour of the closed 14-operation boundary in `docs/REMOTE_ADMINISTRATION.md`.

## Consequences

Devices must operate correctly with the control plane unreachable: policy is cached, the last applied bundle stays in force, updates continue on the device's own schedule, and local administration remains available. The air-gapped path in `docs/AIR_GAPPED_MANAGEMENT.md` is the extreme case of the same property.

Signing keys are separated by namespace — `update-`, `bunny-os-release-`, `oem-`, `fleet-`, `sync-` — and `operations/data/phase7-key-separation.json` records what each authority can and cannot cause. A fleet-control key cannot cause an OS image to be installed.
