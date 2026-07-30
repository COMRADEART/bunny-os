# Air-gapped management

Schema: `schemas/offline-policy-bundle.schema.json`. Implementation: `enterprise/airgap.py`. Tests: `tests/airgap`.

## The rule

Being offline never lowers the trust requirement. There is no unsigned import path, no "trusted local" exception, and no bundle kind that is exempt. `signatureVerified` is `const: true`; supplying `false` is a rejection.

## Workflow

1. The console exports a signed policy bundle for one organisation.
2. The bundle is carried on approved removable media.
3. The device or local proxy verifies the signature, key namespace, digest, sequence, and expiry.
4. Policy is applied through typed operations only.
5. The device exports a signed status report containing operational state only.
6. The console verifies and imports the status report.

Stages must proceed in order; skipping verification is refused. No cloud connection is required at any stage.

## Bundle kinds

`policy-bundle`, `update-export`, `application-mirror`, `enrolment-proxy-configuration`, `offline-recovery-package`, `status-report`.

## Replay protection

Two problems are handled explicitly because they are the realistic attacks on a sneakernet workflow:

- **Stale policy replay.** Bundles carry a monotonic per-organisation sequence. Applying a bundle whose sequence is not greater than the last applied one is refused, mirroring the update agent's highest-sequence rule in `docs/UPDATES.md`.
- **Expiry.** Bundles carry `expiresAt` with a 90-day maximum lifetime, so an old export cannot be applied indefinitely.

## Key namespace

Fleet-control signing keys use the reserved `fleet-` prefix and are separate from OS update keys, release keys, OEM keys, and sync keys. A bundle signed with a key from another namespace is refused, as is a revoked key. See `operations/data/phase7-key-separation.json`.

## Partially disconnected environments

Local update mirror, local application mirror, local enrolment proxy, offline policy bundle, offline recovery package, and air-gapped update export. All remain signed and verifiable.

## Not evidenced

No bundle has been produced by a console, carried on media, or applied to a device. The tests verify the manifest rules and the workflow ordering over synthetic manifests.
