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

## Inspection rather than assertion

`bunny-oem inspect --root <path>` produces the record by looking at a root filesystem tree — a mounted image, a container rootfs, or a fixture — instead of trusting one supplied by the factory.

Seventeen of the twenty-two checks are settleable this way: leftover login accounts, privileged group membership, autologin, NetworkManager profiles carrying a PSK, `authorized_keys`, credential-shaped file content, `NOPASSWD` sudo and permissive polkit rules, installer logs and answer files, shell history, a fixed `machine-id` or cloned SSH host keys that would be identical on every unit shipped, residual device identity, enrolment and sync state, a completed first-run marker, and retained diagnostics containing a serial.

Five cannot be settled offline and report `UNKNOWN`, which is already a refusal:

| Check | Why |
|---|---|
| `recovery-verified` | requires physically booting the recovery media |
| `image-signatures-verified` | requires bootc deployment state on a running system |
| `secure-boot-state-recorded` | requires firmware state from efivars |
| `tpm-state-recorded` | requires TPM presence on the running unit |
| `burn-in-completed` | requires a time-based campaign report |

So an offline probe **alone never seals a device**. `merge_attestation` supplies those five from a signed live record and refuses an attestation that tries to override a check the probe already settled — which is exactly the move a dishonest factory would make.

`describe-checks` reports `offlineInspectable` per check, so the five permanent `UNKNOWN`s are not mistaken for a broken probe.

## Not evidenced

No device has been provisioned, sealed, or handed over, and no live attestation has ever been produced. The probe has been exercised against a real Fedora root filesystem, where it correctly reported two genuine failures — a login account and a fixed `machine-id` — and refused handoff.
