<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Two-person release approval

Four of the seven signing roles require two people. This document is the workflow,
and the reasoning for the one control in it that is easy to leave out.

**Current state: not operable.** One potential signer exists, no production key of
any role exists, and the four two-person roles cannot be provisioned. The
two-person *development* drill passes 9 of 9 and establishes that the path works;
it satisfies nothing about production. See
`TWO_PERSON_DEVELOPMENT_SIGNING_DRILL_REPORT.md`.

## Which roles need two people

| Role | Two-person | What one key alone could do |
|---|---|---|
| `osRelease` | **yes** | cause an artifact to be accepted as an official release |
| `updateMetadata` | **yes** | cause an enrolled device to install a new OS image |
| `recoveryImage` | **yes** | cause recovery media to be booted as genuine |
| `oemProfile` | **yes** | cause an OEM customisation to apply to a hardware model |
| `applicationCatalogue` | no | cause a catalogue entry to be installable |
| `fleetPolicy` | no | cause an enrolled device to apply organisation policy |
| `syncServiceIdentity` | no | authenticate a sync service to a device |

The three excluded roles rotate operationally often enough that two-person
approval would be routinely bypassed, and bypassed controls are worse than absent
ones. `release.signing.TWO_PERSON_ROLES` is the authority, and
`parse_key_record` refuses a production key in a two-person role whose
`twoPersonApproval` flag is false.

## The workflow

### 1. The candidate is published

The release approver publishes the artifact and its digest to a location both
signers can reach. Publishing the digest is a convenience, not evidence: neither
signer may use it.

### 2. Each signer obtains the artifact independently

Each signer downloads the artifact themselves and computes the digest themselves.

This is the step most likely to be skipped, and skipping it collapses the whole
control. If signer B approves the digest signer A sent them, then signer A chose
what B approved, and there is one signature with two names on it.

### 3. Each signer reviews the evidence

Each signer independently reads:

- `build/out/qualification/stable-evidence-report.json`
- `build/out/qualification/stable-evidence-dashboard.md`
- the gate output for `stable-release`
- the open blocker codes

A signer who cannot say why the release is ready is not in a position to approve
it.

### 4. Each signer signs an approval manifest

Not the artifact bytes — a manifest carrying the digest, the role, and the
channel. That is what an approval *is*: an agreement about which artifact.

Each signature is made:

- with that signer's own key, on that signer's own token;
- on that signer's own machine;
- recorded to that signer's own operation log.

### 5. The pair is evaluated

`release.signing.evaluate_two_person_approval` accepts the pair only when **all**
of these hold:

| Check | Refusal if it fails |
|---|---|
| `role-verification` | approvals are for another authority |
| `distinct-key-ids` | one key is not two signers |
| `distinct-signer-ids` | both approvals name the same signer |
| `distinct-operation-logs` | both approvals cite the same log |
| `distinct-signers` | **one person supplying two signer identities is not two-person approval** |
| `artifact-digest-agreement` | the signers approved different artifacts |
| `unanimous-approval` | at least one signer refused, and a refusal is final |

### 6. A refusal is final

No override, no tie-break, no third signer, no escalation. A refusal is a result,
and the release does not proceed.

## The control that is easy to leave out

`distinct-signers` compares an **operator fingerprint** — a hash derived from the
operating account and host — rather than only the key ids and logs.

Two key ids and two log files are trivially produced by one person with two
files. An operator fingerprint is not. It is not proof: a determined operator can
defeat it with a second machine and a second account, and the project says so
rather than claiming otherwise. What it does is convert "one person supplying two
signer identities" from *the default outcome of a single-maintainer project* into
a deliberate act.

That is the honest strength of the control, and it is why
`satisfiesProductionRequirement` is hard-coded `false` in the development drill:
the drill's two fingerprints differ only because the drill declares two labels,
and a production authorisation needs two that differ without one.

## What the development drill establishes

Nine checks, all passing, against two real Ed25519 development keys and the real
2,041,734,656-byte developer OCI archive:

| # | Check | Establishes |
|---|---|---|
| 1 | `signer-a-approval` | signer A signed and verified the manifest |
| 2 | `signer-b-approval` | signer B signed and verified it independently |
| 3 | `distinct-keys` | the key material differs, and B's signature does not verify as A |
| 4 | `distinct-key-ids` | two identities in the `osRelease` namespace |
| 5 | `distinct-operation-logs` | two logs, two contents |
| 6 | `artifact-digest-agreement` | both approved the same digest, and the pair authorises |
| 7 | `role-verification` | a `recovery-` key is refused for `osRelease` |
| 8 | `revocation-test` | one signer's approval is not substitutable by the other |
| 9 | `disagreement-refusal` | a refusal blocks the authorisation |

Two of the nine are refusals. A refusal that does not happen fails the drill.

## What it does not establish

- **Nothing about production signing.** Both keys carry the reserved `dev-`
  prefix and are refused by `require_production_key`.
- **Nothing about two people.** One person ran it.
- **Nothing about key custody.** The drill's keys live in a directory outside the
  repository. A production key must declare hardware-token, offline-HSM or
  protected-signing-service custody.
- **Nothing about the release.** Nine other stable-gate requirements are unmet.

## Reproducing

```text
make two-person-development-signing-drill

python scripts/two_person_drill.py --artifact build/out/developer/bunny-os.oci.tar
python scripts/release.py two-person-development-signing-drill
```

Safe in pull-request CI, and run there: the drill mints its own `dev-` prefixed
keys outside the working tree and cannot produce a releasable artifact.

Recorded results: `operations/data/two-person-signing-drill.json`.
