<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Second signer onboarding

This document exists to be read by a person who does not yet exist.

Bunny OS has one potential release signer. Four of the seven signing roles —
`osRelease`, `updateMetadata`, `recoveryImage`, `oemProfile` — require two-person
approval and therefore **cannot be provisioned at all** with one signer. No
production key of any role exists, and no key ceremony has been held.

Nothing in this document has happened. It is the material a second signer would
need, prepared so that finding one is the only remaining step.

Related: `docs/PRODUCTION_SIGNING_CEREMONY.md` (the ceremony itself),
`docs/SIGNING_ROLE_SEPARATION.md` (the seven roles),
`docs/TWO_PERSON_RELEASE_APPROVAL.md` (the dual-control workflow),
`SECOND_SIGNER_READINESS_REPORT.md` (the current state).

## Role responsibilities

A release signer holds material that can cause software to be installed on
somebody else's computer. That is the whole of the responsibility, and everything
below follows from it.

| You are accountable for | Meaning |
|---|---|
| Custody of your key | It never leaves its hardware token or HSM. Not for a backup, not for a migration, not for a hurry. |
| Refusing | The most important thing a second signer does is decline. A signer who has never refused has not been tested. |
| Verifying before approving | You approve an artifact **digest**, computed by you, from bytes you obtained yourself. Not a digest someone sent you. |
| Recording | Every signing operation goes into your own operation log, held by you, not shared with the other signer. |
| Rotation and revocation | You initiate revocation of your own key the moment you suspect exposure, without waiting for agreement. |
| Declaring conflicts | If you have an interest in a release shipping, say so and abstain. |

What you are **not** accountable for: whether the release is any good. That is
the release approver's judgement. Your signature says "this is the artifact the
project intended", not "this is fit to use".

## Key generation requirements

1. **Generated on the token, never imported.** The private key must be created
   inside the hardware token or HSM and must never have existed as a file.
   `release/signing.py` refuses a production key whose `storage` is not
   `hardware-token`, `offline-hsm` or `protected-signing-service`.
2. **Ed25519.** The project uses Ed25519 throughout. A signer presenting a key of
   another algorithm needs the verification path changed, which is a project
   decision, not a signer decision.
3. **Key id in the role namespace.** Your key id begins with the role's prefix —
   `bunny-os-release-`, `update-`, `recovery-`, `oem-` — and carries a suffix
   identifying you. The reserved `dev-` prefix is refused on every production
   path, so a development key cannot be presented by accident.
4. **Generated in your presence, by you.** Not on your behalf. If the other
   signer generated your key, there is one signer with two keys.
5. **The public key is published before first use**, with an expiry, at a
   location the project controls and you can verify.

## Supported hardware tokens

The requirement is on properties, not on a brand:

| Property | Why |
|---|---|
| On-device key generation | So the key never exists as a file |
| Non-extractable private key | So custody is a physical fact rather than a policy |
| PIN or biometric unlock, with a retry limit | So a stolen token is not a stolen key |
| Ed25519 signing | So the verification path is unchanged |
| Physical presence confirmation per signature | So malware on the host cannot sign silently |
| Firmware from a vendor that publishes updates | So a firmware flaw is fixable |

A FIDO2 or PIV token meeting all six is acceptable. A smartcard in a reader that
caches the PIN is not: it defeats the last row.

An offline HSM is acceptable in place of a token and brings its own procedure,
which is the project's to write once a second signer exists and states which they
will use.

## Offline storage requirements

- The token lives in your physical possession or in a locked container you
  control. Not in the project's possession.
- The two signers' tokens are **not stored in the same building**. Two tokens in
  one drawer are one token for every threat that matters.
- The PIN is not written down anywhere the token is.
- The token is not left connected to a machine between signing operations.

## Backup procedure

**There is no backup of a private key.** A key you can restore from a backup is a
key an attacker can restore from a backup.

What is backed up instead:

1. **The public key**, in three places, one of them not controlled by the
   project.
2. **The key record** — id, role, published and expiry timestamps, storage class
   — in `operations/data/signing-keys.json`.
3. **Your operation log**, by you.

Recovery from a lost key is *rotation*, not restoration. That is why the rotation
procedure below is not optional and why the overlap requirement is enforced in
code.

## Recovery procedure

If your token is lost, destroyed, or you believe it may have been used without
you:

1. **Say so immediately.** Before investigating, before being sure. A false alarm
   costs a rotation; a delayed real alarm costs the trust chain.
2. The remaining signer revokes your key id. Revocation does not need your
   agreement — a signer who might be compromised cannot be part of the decision
   to revoke themselves.
3. Generate a replacement on a new token, following the generation requirements.
4. Publish the replacement **before the predecessor's expiry**, with an
   overlapping trust period. `release.signing.rotation_overlap` refuses a rotation
   without one, with the reason:

   ```text
   no overlapping trust period: the replacement is published at or after the
   predecessor expires, so a device that updates late would trust neither key
   ```

   That failure mode strands deployed devices, which is why it is enforced rather
   than described.
5. Record the revocation and the replacement in `operations/data/signing-keys.json`.
6. Re-run the signing drill against the replacement.

## Rotation procedure

Rotation is routine, not an emergency. Every production key rotates on a schedule
so that the procedure is exercised while nothing is wrong.

1. Generate the replacement on a new or reset token.
2. Set `supersedes` on the replacement to the predecessor's key id. A replacement
   that does not declare what it supersedes is refused.
3. Publish the replacement while the predecessor is still valid. The project
   requires a **90-day minimum overlap**; the drill exercises a 92-day overlap and
   confirms a rotation with a gap is refused.
4. Sign one artifact with each key during the overlap, to prove both verify.
5. Let the predecessor expire. Do not revoke it — revocation and expiry mean
   different things to a device, and using revocation for a routine rotation
   teaches devices to distrust a key that was never compromised.

## Revocation procedure

Revocation says: *do not trust anything this key signed after time T*. It is not
rotation and is not used for one.

1. Either signer may revoke either key. Neither needs the other's agreement.
2. Set `state` to `revoked` and record `revokedAt`.
3. Publish the revocation before publishing anything else.
4. Re-sign any artifact that must remain installable, with a valid key.
5. Record what the revoked key had signed, and decide per artifact whether it is
   withdrawn or re-signed. This is a release-approver decision.

## Dual-control workflow

Fully specified in `docs/TWO_PERSON_RELEASE_APPROVAL.md`. In brief:

1. The release approver publishes the candidate artifact and its digest.
2. **Each signer independently obtains the artifact and computes the digest.**
   Not from the other signer, and not from the publication that named it.
3. Each signer reviews the release evidence and decides.
4. Each signer signs an approval manifest carrying the digest, with their own
   key, on their own machine, recording to their own log.
5. `release.signing.evaluate_two_person_approval` accepts the pair only when the
   key ids, signer ids, operation logs and operator fingerprints all differ and
   both digests agree.
6. **Either refusal is final.** There is no override, no tie-break, and no
   escalation. A refusal is a result.

## Conflict-of-interest policy

Declare and abstain if:

- you have a financial interest in the release shipping on a particular date;
- you are employed by, contracted to, or hold equity in an OEM, enterprise
  customer, or other party with an interest in the outcome;
- you authored the change under approval **and** are the only other signer — in
  which case the pair is one person's judgement twice;
- you are being pressured to approve, by anyone, including the project.

Abstaining blocks the release. That is the correct outcome: a release that needs
a conflicted signature does not have two-person approval.

A repository maintainer may be a signer. A repository maintainer may not be
*both* signers, and the fingerprint check exists to make that a deliberate act
rather than the default.

## Signing drill

Before your first production signature, run the drill with a **development** key
of your own:

```text
python scripts/signing_drill.py --keydir ~/.bunny-dev-keys/<your-name>
python scripts/two_person_drill.py --keydir ~/.bunny-dev-keys/<your-name>
```

The nine-check drill exercises signing, verification, rotation and four
refusals. The two-person drill exercises two signers, two keys, two logs, and two
refusals — revocation and disagreement. Both use `dev-` prefixed keys that
`require_production_key` refuses, so neither can produce a releasable artifact.

Passing the drill establishes that you can operate the path. It establishes
nothing about production, and the drill's own report says so.

## Audit requirements

| Requirement | Detail |
|---|---|
| One operation log per signer | Held by that signer. Two signers sharing a log is one signer. |
| Every operation recorded | Including refusals, and including operations that failed. |
| Log entries name the digest | Not the artifact's filename. |
| Logs are append-only in practice | A log you can edit is a log you can edit after the fact. |
| Annual reconciliation | Each signer's log is compared against the published signatures. A signature with no log entry, or a log entry with no signature, is an incident. |
| Key records are current | `operations/data/signing-keys.json` reflects reality, and the gate reads it rather than a report. |

## What a second signer does not fix

Being explicit, because "we found a second signer" is easy to hear as "signing is
solved":

- It does not create a production key. That needs a ceremony.
- It does not make the stable gate pass. Nine other requirements are unmet.
- It does not resolve the 24 `Unknown` vulnerability dispositions.
- It does not qualify any hardware.

It closes one requirement of fourteen, and it is a requirement nothing else can
close.
