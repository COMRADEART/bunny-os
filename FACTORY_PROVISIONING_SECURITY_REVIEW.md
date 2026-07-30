# Factory provisioning security review

Date: 2026-07-29. Scope: `oem/validation/finalize.py`, `oem/cli.py`, and the sealing contract in `docs/OEM_MODE.md`. Tests: `tests/factory`, 21 cases.

## Threat

A factory has network access, administrative credentials, test accounts, and physical access to every device before a customer receives it. Residue from that environment on a shipped device is a credential leak with no user-visible symptom. A device that ships with a factory Wi-Fi PSK, a provisioning SSH key, or a log full of hardware serials has been compromised before it is unboxed.

## Controls

`bunny-oem finalize` evaluates 22 checks and refuses handoff unless every one reports `PASS`.

Credential residue: factory accounts, factory groups, autologin, Wi-Fi profiles, SSH keys, test provider credentials and Secret Service items, sudo and polkit rules.

Identifier residue: temporary logs, journal exports, and diagnostic bundles containing device identifiers; shell history for root and every factory account; installer transaction journals, answer files, and session artefacts; retained diagnostic records containing a hardware serial.

Cloned-secret residue: `/etc/machine-id` must be empty or newly generated; SSH host keys must be absent or regenerated rather than cloned across units. A fleet of devices sharing a machine-id or host key is a correlation vector and a spoofing opportunity.

Phase 7 state residue: no factory device identity, no enrolment token or certificate, no organisation binding, no sync account or device key, no cached encrypted object.

Handoff state: the first-run marker must record setup as incomplete so the customer creates the first account; recovery must boot and its signature verify; the OS image and every OEM extension must verify against their declared trust roots.

Honest recording: Secure Boot and TPM state must be recorded truthfully, including `disabled` and `absent`. Burn-in must have completed without unrecovered error.

## Fail-closed properties

Three, and they are the substance of the review:

- `UNKNOWN` and `NOT_RUN` are failures. A check that could not be performed is never treated as a pass. This mirrors the repository's existing stance that unknown evidence is blocking.
- A missing check id is a failure, so adding a check cannot silently weaken an older evidence file — an old record simply stops sealing.
- An unrecognised check id is an error, not an ignored key, so a typo cannot masquerade as a passing check.

## Findings

No Blocker or Critical finding in the evaluator.

**One Major limitation.** The evaluator assesses a *supplied record*. It does not inspect the device. A factory that submits a record claiming every check passed will seal a device that still holds credentials. Closing this requires the executor, which does not exist: `bunny-oem provision` and `seal` report `available: false`, `writesPerformed: false`, and exit 78.

This is a limitation rather than a defect because no factory exists and no device has been provisioned. It becomes Critical the moment a real provisioning line runs, and it must be closed before then. Recorded in `KNOWN_LIMITATIONS.md`.

## What was verified

Each of the 22 checks blocks handoff independently. `UNKNOWN` and `NOT_RUN` block. A missing check blocks. An unknown check id and an invalid status raise. The CLI emits "Customer handoff refused" and exits 2. The unavailable operations report `writesPerformed: false` and exit 78.

## What was not verified

No device has been provisioned, diagnosed, burned in, sealed, or handed over. No factory environment has been assessed. No record has been produced by anything other than a test fixture.
