<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Second signer readiness report

Date: 2026-07-30
Result: **onboarding material complete. No second signer exists, no production key
of any role exists, and no key ceremony has been held.**

## The position

| | |
|---|---|
| Potential signers | 1 |
| Production keys, any role | **0** |
| Roles requiring two-person approval | 4 of 7 |
| Roles that can currently be provisioned | **0 of the 4** |
| Key ceremonies held | 0 |
| Development keys | 7, all `dev-` prefixed and refused on every production path |

```text
$ python scripts/release.py signing-roles
productionKeyCount: 0
productionReady: false
```

Four roles — `osRelease`, `updateMetadata`, `recoveryImage`, `oemProfile` — require
two people. With one signer they cannot be provisioned at all. Not "provisioned with
a caveat": `parse_key_record` refuses a production key in one of those roles whose
`twoPersonApproval` flag is false, and a single signer cannot honestly set it true.

## What was delivered this phase

| Deliverable | Contents |
|---|---|
| `docs/SECOND_SIGNER_ONBOARDING.md` | role responsibilities, key generation, token requirements, offline storage, backup, recovery, rotation, revocation, dual control, conflict-of-interest policy, drill, audit |
| `docs/TWO_PERSON_RELEASE_APPROVAL.md` | the six-step dual-control workflow and the one control that is easy to leave out |
| `release/signing.py` two-person model | `SignerApproval`, `evaluate_two_person_approval`, `evaluate_two_person_drill` |
| `scripts/two_person_drill.py` | the drill, run against two real Ed25519 keys |
| `TWO_PERSON_DEVELOPMENT_SIGNING_DRILL_REPORT.md` | 9 of 9, and what it does not establish |
| `tests/signing/test_two_person_approval.py` | 26 tests, including both mandated adversarial cases |

**No second signer record was created.** Inventing one would be the single most
damaging thing this phase could do to the signing evidence, and
`operations/data/signing-keys.json` contains no production key of any class.

## The control that carries the weight

`evaluate_two_person_approval` compares an **operator fingerprint** — a hash derived
from the operating account and host — in addition to key ids, signer ids and
operation logs.

Two key ids and two log files are trivially produced by one person with two files.
An operator fingerprint is not.

It is **not proof**. A determined operator can defeat it with a second machine and a
second account, and the project says so rather than claiming otherwise. What it does
is convert "one person supplying two signer identities" from *the default outcome of
a single-maintainer project* into a deliberate act — and that is the strongest
control available without a second human.

This is why `satisfiesProductionRequirement` is hard-coded `false` in the
development drill: the drill's two fingerprints differ only because the drill
declares two labels.

## Readiness, item by item

| Requirement | State |
|---|---|
| Role responsibilities documented | **done** |
| Key-generation requirements documented | **done** — on-token generation, never imported |
| Supported hardware token specified | **done** — six properties, not a brand |
| Offline storage requirements documented | **done** — including "not in the same building" |
| Backup procedure documented | **done** — and it explains why there is no key backup |
| Recovery procedure documented | **done** — recovery is rotation, not restoration |
| Rotation procedure documented | **done** — 90-day minimum overlap, enforced in code |
| Revocation procedure documented | **done** — either signer may revoke either key, unilaterally |
| Dual-control workflow documented | **done** — six steps, seven checks |
| Conflict-of-interest policy documented | **done** — four grounds to abstain, and abstaining blocks |
| Signing drill available | **done** — nine-check and two-person, both runnable in CI |
| Audit requirements documented | **done** — six requirements, one log per signer |
| **A second signer** | **not met** |
| **A production key ceremony** | **not met** |
| **Two production keys in a two-person role** | **not met** |

Twelve of fifteen. The three unmet ones need a person.

## What the two-person drill establishes, and what it does not

**Establishes:** the two-signer path works, with two separate Ed25519 keys, two
separate operation logs, two separate operator fingerprints, over the real
2,041,734,656-byte developer OCI archive's digest. Nine of nine checks, two of which
are refusals — a revoked signer's approval is not substitutable, and a disagreement
blocks the authorisation.

**Does not establish:** anything about production signing (both keys are `dev-`
prefixed), anything about two people (one person ran it), anything about key custody
(the drill's keys live in a directory), and anything about the release (nine other
stable-gate requirements are unmet).

The drill's own report says all of this, and
`evaluate_two_person_drill` returns `satisfiesProductionRequirement: false`
unconditionally.

## Consequences

- `second-production-signer` reports `BLOCKED` with the dependency *"a second person
  and a key ceremony"*.
- The `Signing` evidence category records `FAIL`: no production key of any role
  exists, and the development drill cannot substitute.
- `gate-stable-release` reports `NO-GO` on `production-signing`.
- `gate-oem-pilot` cannot reach `signedOemProfile`: the `oemProfile` role has no key
  of any class.

## What finding a second signer does not fix

Being explicit, because "we found a second signer" is easy to hear as "signing is
solved":

- It does not create a production key. That needs a ceremony.
- It does not make the stable gate pass. Nine other requirements are unmet.
- It does not resolve the 24 `Unknown` vulnerability dispositions.
- It does not qualify any hardware.

It closes one candidate prerequisite of fourteen, and it is one nothing else can
close.

## Reproducing the current state

```text
python scripts/release.py signing-roles
python scripts/release.py development-signing-drill
python scripts/release.py two-person-development-signing-drill
```
