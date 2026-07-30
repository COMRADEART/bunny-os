# Signing role separation

Seven signing authorities with disjoint key-id namespaces. The separation is
checked at parse time by `release/signing.py`, not maintained by convention, so
a key minted for one authority cannot be presented for another.

## The roles

| Role | Namespace | Can authorise | Cannot |
|---|---|---|---|
| `osRelease` | `bunny-os-release-` | An artifact being accepted as an official release | Cause a device to install anything |
| `updateMetadata` | `update-` | A device to install a new OS image | Alter release acceptance |
| `recoveryImage` | `recovery-` | Recovery media to be accepted as genuine and booted | Touch the installed deployment |
| `applicationCatalogue` | `catalogue-` | A catalogue entry to be installable | Install an OS image |
| `oemProfile` | `oem-` | An OEM customisation to apply to a matching model | Alter update trust, privacy defaults, or security protections |
| `fleetPolicy` | `fleet-` | An enrolled device to apply organisation policy | Cause an OS image to be installed; disable signature verification |
| `syncServiceIdentity` | `sync-` | A sync service to authenticate to a device | Decrypt user content |

## The two walls

### Role separation

`validate_namespaces()` asserts that no namespace prefix is a prefix of another,
so key ids parse unambiguously. `parse_key_id(keyId, expectedRole=...)` raises
when a key from one authority is presented for another:

```text
key 'recovery-001' belongs to the recoveryImage authority but was presented for
osRelease; signing roles are not interchangeable
```

The property that matters: a fully compromised fleet control plane holding every
`fleet-` key still cannot cause an OS image to be installed, because update
signature verification is not expressible as a policy at any enforcement level
and the fleet namespace is not accepted by the update agent.

### Development and production

Every development key carries a reserved `dev-` prefix *before* its role prefix:
`dev-bunny-os-release-drill1`. `require_production_key()` refuses any key with
that prefix:

```text
key 'dev-bunny-os-release-drill1' is a development key and can never satisfy a
production release gate; development artifacts are not releasable
```

This is what makes the development signing drill safe to run automatically,
including in pull-request CI: it exercises the whole path and cannot produce
anything a release gate would accept.

## Lifecycle requirements

Per key, validated by `parse_key_record()`:

- **Protected storage.** A production key must declare `hardware-token`,
  `offline-hsm` or `protected-signing-service`. A development directory is
  refused for a production key.
- **Public-key publication.** `publicKeyReference` is mandatory. Update trust
  roots ship inside the image at `/usr/share/bunny-os/update-keys`.
- **Expiry.** `expiresAt` is mandatory and `usable_key()` refuses an expired key.
- **Publication date.** A key not yet published is refused, so a
  post-dated key cannot be used early.
- **Rotation with overlap.** `rotation_overlap()` requires the replacement to be
  published *before* the predecessor expires and to declare what it supersedes.
  A gap is refused: a device that updates late would otherwise trust neither key.
- **Revocation.** `revoked-keys.json` ships inside the signed image and
  `usable_key()` refuses a revoked id regardless of expiry or state.
- **Two-person approval.** Required for `osRelease`, `updateMetadata`,
  `recoveryImage` and `oemProfile` — the four where a single compromised signer
  could install software on a device or bless a release.
  `syncServiceIdentity` is excluded because it rotates operationally.

## Current state

No production key of any role exists. Three roles — `oemProfile`, `fleetPolicy`,
`syncServiceIdentity` — have no key of any class.

There is one potential signer, so the two-person requirement on four roles
**cannot currently be met**. This is a capacity blocker, not a code blocker, and
it is recorded in `SUSTAINABILITY_REPORT.md` and
`operations/data/signing-keys.json`.

## Related

- `docs/PRODUCTION_SIGNING_CEREMONY.md` — the procedure that has not been run.
- `docs/KEY_RECOVERY.md` — what happens when a key is lost or compromised.
- `DEVELOPMENT_SIGNING_DRILL_REPORT.md` — the drill that has been run.
- `operations/data/phase7-key-separation.json` — the five Phase 7 namespaces,
  a subset of the seven here.
