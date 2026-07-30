# Physical hardware evidence intake

This directory holds the artifacts that substantiate a physical hardware
qualification. It is currently **empty of results**, and that is the honest
state: no physical machine has run Bunny OS.

`operations/data/hardware-evidence.json` is the index. A report there is
accepted only when `release/hardware.py` can verify two things.

## 1. The report carries no personal or device identifiers

Serial numbers, MAC addresses, usernames and personal hostnames must not appear
anywhere in a submission. The check walks every string in the record, not only
the fields a submitter remembered to clean, because the risk is the field nobody
thought about.

Record the machine by *class*, not identity:

| Instead of | Record |
|---|---|
| `Dell XPS 13 9310, SN 7X2K9M3` | `formFactor: "ultraportable-laptop"` |
| `Intel Core i7-1185G7` | `chipsetClass: "intel-tiger-lake"` |
| `AA:BB:CC:DD:EE:FF` | nothing; record `wifi: true` |
| `desktop-alice` | nothing |
| firmware `1.14.0` from `Dell Inc.` | `firmwareVendor`, `firmwareVersion` — these are fine |

## 2. Every claimed result names an artifact that exists

A report claims fifteen test outcomes. Each `PASS` or `FAIL` must reference a
file in this directory — a boot log, a photograph of a firmware screen, a
`journalctl` export, a serial capture. A report full of `PASS` values with no
artifacts is rejected. This is the check that distinguishes a qualification from
a claim.

Suggested layout for one machine:

```text
hardware/evidence/<report-id>/
  install.log
  encryption-unlock.log
  secure-boot-state.txt
  tpm-state.txt
  suspend-resume.log
  update.log
  rollback.log
  recovery-boot.log
  network.txt
  audio.txt
  camera.txt
  bunny-disabled.log
  local-only.log
```

## The fifteen tests

install, encryption, boot, secure-boot, tpm, network, audio, camera, suspend,
resume, update, rollback, recovery, bunny-disabled, local-only.

A machine is **qualified** only when every one of the fifteen resolves and none
failed. `NOT_RUN` on any test means the machine is not qualified — there is no
partial credit, because the stable gate's hardware row is a statement about a
whole machine.

## The first required target

At least one **x86-64 UEFI physical machine**. Preferred characteristics, in the
order they unblock other evidence rows: Secure Boot, TPM 2.0, NVMe, Wi-Fi,
Bluetooth, audio, microphone, camera, suspend/resume, integrated graphics.

Secure Boot and TPM are worth prioritising because they block the `Secure Boot`
evidence category and two encryption-matrix scenarios that no virtual machine
result can substitute for.

## Submitting

1. Create `hardware/evidence/<report-id>/` and put the artifacts in it.
2. Add a report object to `operations/data/hardware-evidence.json`.
3. Run `python scripts/release.py validate-hardware-evidence`.

The command fails closed. It will tell you which claims are unsubstantiated and
which strings look like identifiers.

`template.json` in this directory is a complete, correctly shaped example with
every result set to `NOT_RUN`.
