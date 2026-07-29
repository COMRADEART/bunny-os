# Factory provisioning

Evaluator: `oem/validation/finalize.py`. Command: `oem/bin/bunny-oem finalize`. Tests: `tests/factory`.

Extends `docs/OEM_MODE.md`, which already stated the intended sealing contract. This document makes it a checked list.

## Stages

Hardware diagnostics, storage validation, firmware validation, image installation, device identity creation, Secure Boot validation, TPM validation, recovery-image verification, burn-in testing, temporary factory account, handoff preparation.

The executor that performs these on real hardware is not implemented. `bunny-oem provision`, `seal`, and `build-image` report `available: false`, `writesPerformed: false`, and exit 78. A stub that pretended to provision would be worse than a refusal.

## Finalisation

`bunny-oem finalize --record <file>` evaluates 22 checks and refuses handoff unless every one reports `PASS`. Two rules make the refusal meaningful:

- `UNKNOWN` and `NOT_RUN` are failures. A check that could not be performed is never a pass.
- A missing check id is a failure, so adding a check cannot silently weaken an older evidence file. An unrecognised check id is an error, so a typo cannot masquerade as a pass.

The checks cover: factory accounts, groups, autologin, Wi-Fi profiles, SSH keys, test credentials, sudo and polkit rules, logs containing identifiers, shell history, installer session artefacts, machine-id regeneration, host-key regeneration, device identity absence, enrolment state absence, sync state absence, the first-user-setup marker, recovery verification, image signature verification, honest Secure Boot and TPM state recording, burn-in completion, and retained diagnostic serials.

Run `bunny-oem describe-checks` for the current catalogue.

## Exit codes

`0` handoff permitted, `2` refused with the blocking checks listed, `78` the operation needs a reviewed executor that is not installed.

## Not evidenced

No device has been provisioned, sealed, or handed over. Every result here is the evaluation of a supplied record, not an observation of hardware.
