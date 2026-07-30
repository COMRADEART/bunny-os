# Air-gapped management report

Date: 2026-07-29. Implementation: `enterprise/airgap.py`. Schema: `schemas/offline-policy-bundle.schema.json`. Tests: `tests/airgap`, 19 cases.

## Principle

Being offline never lowers the trust requirement. There is no unsigned import path, no "trusted local" exception, and no bundle kind that is exempt. `signatureVerified` is `const: true` in the schema; supplying `false` is a rejection rather than a configuration.

This matters because offline environments are where exceptions usually get made. A research laboratory or an air-gapped site cannot reach a signing service, so the tempting shortcut is a local override. That shortcut would make the removable medium the trust root.

## Workflow

Six stages, enforced in order:

1. Export a signed policy bundle for one organisation.
2. Transport it on approved removable media.
3. Verify signature, key namespace, digest, sequence, and expiry.
4. Apply policy through typed operations only.
5. Export a signed status report containing operational state only.
6. Verify and import the status report.

Skipping verification is refused. No cloud connection is used at any stage.

## Replay protection

Two attacks are specifically handled, because they are the realistic ones against a sneakernet workflow:

- **Stale policy replay.** Bundles carry a monotonic per-organisation sequence. A bundle whose sequence is not greater than the last applied one is refused, mirroring the update agent's highest-sequence rule. An attacker who keeps an old permissive bundle cannot re-apply it.
- **Indefinite reuse.** Bundles carry `expiresAt` with a 90-day maximum lifetime, so an old export cannot be applied years later.

## Key namespace

Only `fleet-` prefixed keys are accepted. A bundle signed with an `oem-`, `bunny-os-release-`, or `sync-` key is refused, and a revoked `fleet-` key is refused. This keeps the offline path from becoming a way to smuggle one authority's signature into another authority's decision.

## Bundle kinds

`policy-bundle`, `update-export`, `application-mirror`, `enrolment-proxy-configuration`, `offline-recovery-package`, `status-report`. All six require verified signatures; the test suite checks each one individually rather than trusting a shared code path.

## Partially disconnected environments

Local update mirror, local application mirror, local enrolment proxy, offline policy bundle, offline recovery package, and air-gapped update export. All remain signed and verifiable. None introduces an unsigned local exception.

## Findings

No Blocker or Critical finding.

Residual risk: a bundle within its expiry window and above the last applied sequence is accepted. That is the intended behaviour and the irreducible residual risk of any offline distribution — an attacker who obtains a currently-valid signed bundle can deliver it. Reducing this further would require per-device nonces exchanged out of band, which an air-gapped workflow cannot provide.

## Not evidenced

No bundle has been produced by a console, written to media, carried, verified on a device, or applied. No status report has been exported or imported. The 19 tests verify manifest rules and workflow ordering over synthetic manifests.
