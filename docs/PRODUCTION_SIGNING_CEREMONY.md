# Production signing ceremony

**No production signing ceremony has been held. No production key exists. This
document is the procedure, not a record of one having happened.**

`operations/data/signing-keys.json` records `productionKeyCeremonyHeld: false`,
and `release.signing.require_production_key` refuses every key currently in
existence.

## Entry conditions

The ceremony may not proceed until all of these hold. They are listed first
because the ceremony is the wrong thing to do while any is unmet.

1. **Two people.** Four of the seven roles require two-person approval. There is
   currently one potential signer, so the ceremony cannot legitimately produce
   an `osRelease`, `updateMetadata`, `recoveryImage` or `oemProfile` key.
2. **Protected storage in hand.** A hardware token, offline HSM, or a protected
   signing service. `parse_key_record()` refuses a production key stored in a
   directory.
3. **A decided key policy.** Expiry period, rotation cadence, and the overlap
   window, recorded before generation rather than chosen afterwards.
4. **A recovery plan.** `docs/KEY_RECOVERY.md`, reviewed, with the emergency
   path tested using development keys.
5. **A publication route.** Somewhere the public keys will actually live, that a
   verifier can reach independently of the artifact being verified.

## Roles and separation

Seven keys, one per authority, generated in separate ceremonies or at least
separately witnessed. See `docs/SIGNING_ROLE_SEPARATION.md`.

Generating one key and using it for several roles defeats the entire separation
argument, and `parse_key_id` will reject the reuse at the first verification.

## Procedure

### Before the ceremony

1. Fix the date and the two participants. Record who they are.
2. Prepare an air-gapped machine. Verify its image independently.
3. Prepare the storage device. Verify it is genuine.
4. Prepare the key policy document: role, expiry, rotation cadence, overlap
   window, publication location.
5. Prepare the witness log template.

### During the ceremony

6. Both participants present. Neither leaves the room with the material
   unattended.
7. Record the start: date, time, participants, machine, storage device.
8. Generate the keypair on the air-gapped machine, directly onto the protected
   storage. **The private key must never touch a general-purpose filesystem.**
9. Record the public key fingerprint. Both participants verify it independently
   and both record it in the witness log.
10. Export the public key. Verify the exported key matches the fingerprint.
11. Set expiry and any storage-device policy — PIN, touch requirement, retry
    limits.
12. Test a signature and a verification on the air-gapped machine, using a
    throwaway artifact, before the machine is destroyed or wiped.
13. Record the end: time, outcome, anything unexpected.
14. Both participants sign the witness log.

### After the ceremony

15. Publish the public key at the prepared location.
16. Add a `KeyRecord` to `operations/data/signing-keys.json` with
    `keyClass: production`, the real storage class, and
    `twoPersonApproval: true` where the role requires it.
17. Add the key to the image build inputs so it ships in the trust root.
18. Record the ceremony reference so evidence records claiming
    `keyClass: production` can resolve it. Until such a reference exists,
    `operations/devqualification.py` fails any production-key claim — which is
    what it does today.
19. Store the witness log where it survives the loss of any one participant.
20. Wipe or destroy the air-gapped machine's storage.

## What must never happen

- A private key inside the repository. `build/scripts/sign-stable-rc.py` refuses
  a key path inside the working tree, and this was verified in practice rather
  than asserted: the refusal message is *"private signing keys must not be
  stored in the repository"*.
- A private key on a networked general-purpose machine.
- One key serving two roles.
- A ceremony with one participant producing a key for a two-person role.
- A ceremony recorded as having happened when it did not. Nothing in this
  repository may claim a production signature until step 18 is real.

## Current status

| Item | State |
|---|---|
| Ceremony held | **no** |
| Production keys | **none, for any of the seven roles** |
| Second signer available | **no** |
| Protected storage acquired | **no** |
| Key policy decided | **no** |
| Public key publication route | **not established** |

The `Signing` evidence category therefore records `FAIL`, and it is one of the
six categories `release/evidence.py` refuses to let anyone waive.

## What has been done instead

A complete development signing drill, with keys carrying the reserved `dev-`
prefix, generated outside the repository. Nine of nine checks pass against real
1.85 GB and 1.33 GB artifacts, including four rejection checks. See
`DEVELOPMENT_SIGNING_DRILL_REPORT.md`.

The drill proves the *path* works. It proves nothing about release signing, and
the development keys it mints are refused by every production gate by
construction.
