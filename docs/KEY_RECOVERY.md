# Key recovery

What happens when a signing key is lost, compromised, or expires unnoticed.

None of this has been exercised against production keys, because no production
key exists. The rotation, revocation and wrong-role paths **have** been exercised
against development keys; see `DEVELOPMENT_SIGNING_DRILL_REPORT.md`.

## The three situations

### 1. A key expires unnoticed

The least dramatic and the most likely. `usable_key()` refuses an expired key,
so signing stops and releases stop. Devices already holding the trust root keep
working; nothing installs.

*Recovery:* rotate. The overlap requirement exists precisely so this does not
become an emergency — `rotation_overlap()` refuses a replacement published at or
after the predecessor expires, because a device that updates late would trust
neither key.

*Prevention:* the expiry is in `operations/data/signing-keys.json` and the
evidence model treats expired evidence as blocking, so an expiring key surfaces
as a failing gate before it surfaces as an outage.

### 2. A key is lost

The storage device fails, or is destroyed, and the private key is unrecoverable.
No signature can be produced for that role.

*Recovery:*

1. Hold a new ceremony for that role only.
2. Publish the new public key with an overlap window against the lost key's
   expiry. The lost key is not revoked — it was never compromised, and revoking
   it would invalidate artifacts that are still genuine.
3. Ship the new trust root in the next image.
4. Devices that update within the overlap transition automatically. Devices that
   do not are in situation 3's recovery path from the user's point of view: they
   need recovery media.

*This is why overlap is mandatory rather than advisory.* Without it, losing a
key strands every device that has not updated recently.

### 3. A key is compromised

Someone else can sign as that authority. This is the emergency.

*Immediate:*

1. Add the key id to `build/keys/revoked-keys.json`. This file ships inside the
   signed image, so revocation is distributed through the same channel the key
   protected — which means a device that never updates never learns. That
   limitation is real and is stated here rather than papered over.
2. Stop signing with the compromised role.
3. Determine the blast radius from `docs/SIGNING_ROLE_SEPARATION.md`. This is
   what the role separation is *for*: a compromised `fleet-` key cannot cause an
   OS image to be installed, and a compromised `sync-` key cannot decrypt
   content. Establish which of the seven authorities was actually lost before
   treating everything as lost.
4. Hold a ceremony for a replacement, with a *shortened* overlap — the trade is
   between stranding slow updaters and extending the window in which the
   attacker's signatures verify.

*Then:*

5. Re-sign every still-current artifact with the replacement key.
6. Publish what happened, with the compromised key id and the dates between
   which its signatures should not be trusted.
7. Review how it happened before generating the replacement, or the replacement
   inherits the flaw.

## Emergency recovery when every key is lost

If all seven private keys are lost at once — a fire, a single point of storage —
there is no cryptographic recovery. There is no escrow and no shared secret, by
design: an escrow is another copy of the key, and the threat model does not
improve by having more copies in more places.

The recovery path is social, not technical:

1. Announce it, with the fingerprints of the lost keys.
2. Hold ceremonies for all seven roles.
3. Publish the new public keys through as many independent channels as exist, so
   a verifier can corroborate rather than trust one.
4. Accept that devices which cannot reach a new trust root need recovery media
   and a manual re-installation. **This is the scenario that makes independently
   bootable recovery media a release blocker rather than a nice-to-have.**

The honest summary: losing every key means every deployed device that has not
updated must be reached out-of-band. The mitigations are overlap windows,
storing keys for different roles in different places, and recovery media that
works.

## Two-person approval and recovery

Four roles require two-person approval. That protects against a single
compromised or coerced signer, and it introduces a failure mode: if one of the
two becomes unavailable, those roles cannot sign.

There is currently **one** potential signer, so the project is already in the
degraded state — not because someone left, but because a second was never
recruited. This is the single most valuable non-technical thing that could
change, and it is recorded in `SUSTAINABILITY_REPORT.md`.

## What has actually been tested

Against development keys, in `scripts/signing_drill.py`:

| Path | Result |
|---|---|
| Rotation with an overlapping trust period | accepted, 92-day overlap |
| Rotation with a gap | refused, with the reason |
| Revoked key presented for signing | refused |
| Key from the wrong authority | refused |
| Signature over a corrupted artifact | refused |

Against production keys: **nothing**, because there are none.
