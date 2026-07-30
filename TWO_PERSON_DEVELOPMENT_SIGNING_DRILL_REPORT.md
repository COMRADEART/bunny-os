<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Two-person development signing drill report

Date: 2026-07-30
Key class: **development**
Role exercised: `osRelease`
Result: **9 of 9 checks PASS**

**This is not release signing evidence and does not satisfy the production
second-signer requirement.** Both keys carry the reserved `dev-` prefix and are
refused by `release.signing.require_production_key`. One person ran the drill.
`evaluate_two_person_drill` returns `satisfiesProductionRequirement: false`
unconditionally.

What the drill establishes is that the **two-person path works, including its two
refusals** — which is the part that is easy to get wrong and impossible to notice.

## Setup

Two Ed25519 keys generated with `openssl genpkey -algorithm ed25519`, **outside the
repository**, at `~/.bunny-dev-keys/two-person/`. The drill refuses a key directory
inside the working tree, matching the control
`build/scripts/sign-stable-rc.py` already enforces.

| Key | Signer |
|---|---|
| `dev-bunny-os-release-signer-a` | signer-a |
| `dev-bunny-os-release-signer-b` | signer-b |

Before anything else, the drill asserts that both keys are refused by
`require_production_key`. If that assertion failed the drill would abort, because
nothing else about it would be safe.

### What is signed

An **approval manifest** carrying the SHA-256 of the real developer OCI archive —
`bunny-os.oci.tar`, 2,041,734,656 bytes, digest `25cab482caf4…` — not the archive
bytes.

That is not a shortcut. A two-person release approval is an agreement about *which
artifact*, and the manifest carrying the real digest is the object both signers must
agree on. The archive-bytes signing path is already covered by the nine-check drill
in `DEVELOPMENT_SIGNING_DRILL_REPORT.md`, against a 1.85 GB artifact.

## Results

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | `signer-a-approval` | **PASS** | signed and verified the manifest over the 2,041,734,656-byte archive |
| 2 | `signer-b-approval` | **PASS** | signed and verified the same manifest independently |
| 3 | `distinct-keys` | **PASS** | the private keys differ, and B's signature does not verify against A's public key |
| 4 | `distinct-key-ids` | **PASS** | two identities in the `osRelease` namespace |
| 5 | `distinct-operation-logs` | **PASS** | two logs, two contents |
| 6 | `artifact-digest-agreement` | **PASS** | both approved `25cab482caf4`; authorisation granted |
| 7 | `role-verification` | **PASS** | `dev-recovery-signer-b` refused for `osRelease` — *"signing roles are not interchangeable"* |
| 8 | `revocation-test` | **PASS** | a signature made by A does not verify as B, so revoking one signer's key removes that signer's approval and cannot be substituted by the other |
| 9 | `disagreement-refusal` | **PASS** | signer B refusing blocks the authorisation — *"at least one signer refused; two-person approval requires both, and a refusal is final"* |

**Two of the nine are refusals.** A refusal that does not happen fails the drill:
`evaluate_two_person_drill` treats any non-`PASS` outcome as failing, including on
the rejection checks.

## The two worth reading the detail of

### Disagreement is final

```text
signer B refusing blocks the authorisation: unanimous-approval: at least one
signer refused; two-person approval requires both, and a refusal is final
```

There is no override, no tie-break, no third signer and no escalation. A refusal is
a result. That is enforced in `evaluate_two_person_approval` rather than described in
a runbook, because a control with an override is a control that will be overridden.

### One person supplying two identities is refused

The check that carries the weight is `distinct-signers`, which compares an **operator
fingerprint** — a hash derived from the operating account and host — rather than only
key ids and log paths:

```text
both approvals carry operator fingerprint <x>; one person supplying two signer
identities is not two-person approval
```

Two key ids and two log files are trivially produced by one person with two files.
An operator fingerprint is not.

**It is not proof.** A determined operator can defeat it with a second machine and a
second account. What it does is convert "one person supplying two signer identities"
from *the default outcome of a single-maintainer project* into a deliberate act, and
that is the strongest control available without a second human. It is also exactly
why this drill cannot satisfy the production requirement: its two fingerprints differ
only because the drill declares two labels.

## What this does not establish

- **Nothing about release signing.** Development keys cannot satisfy a production
  gate, by construction.
- **Nothing about two people.** One person ran it. The whole point of two-person
  approval is that two people exercise independent judgement, and one person cannot
  simulate that.
- **Nothing about key custody.** These keys live in a directory. A production key
  must declare `hardware-token`, `offline-hsm` or `protected-signing-service`, and
  `parse_key_record` refuses a production key that does not.
- **Nothing about the four two-person roles being provisioned.** They have no key of
  any class in the `oemProfile` case, and no production key in any case.
- **Nothing about the release.** Nine other stable-gate requirements are unmet.

## Reproducing

```text
make two-person-development-signing-drill

python scripts/two_person_drill.py --artifact build/out/developer/bunny-os.oci.tar
python scripts/release.py two-person-development-signing-drill
```

Safe in pull-request CI and run there: the drill mints its own `dev-` prefixed keys
outside the working tree and cannot produce a releasable artifact. The CI job
additionally asserts that `satisfiesProductionRequirement` is `false`, so a change
that made the drill claim otherwise would fail the build.

Recorded results: `operations/data/two-person-signing-drill.json`.
Evaluated output: `build/out/qualification/two-person-signing-drill.json`.

## Related

- `docs/TWO_PERSON_RELEASE_APPROVAL.md` — the workflow this exercises
- `docs/SECOND_SIGNER_ONBOARDING.md` — what a second signer would need
- `SECOND_SIGNER_READINESS_REPORT.md` — twelve of fifteen readiness items done
- `DEVELOPMENT_SIGNING_DRILL_REPORT.md` — the nine-check single-signer drill
- `docs/PRODUCTION_SIGNING_CEREMONY.md` — the ceremony that has not been run
