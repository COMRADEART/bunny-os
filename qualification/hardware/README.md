<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Physical hardware qualification framework

> **Every physical test is currently NOT_RUN. No device has been qualified.
> No physical machine has ever run Bunny OS. QEMU/swtpm evidence never
> becomes physical evidence — a virtual TPM proves the software path, not
> the machine.**

This directory is the framework that will be used **when a real machine
becomes available**. It exists now, before the machine, so that the first
device produces evidence in the right shape on the first attempt — and so
that there is no window in which "we'll write it down properly later"
produces an unreviewable pile of pastes. Everything here makes the
NOT_RUN state explicit and makes fabrication hard: a PASS without an
evidence artifact does not validate, a NOT_RUN carrying observations does
not validate, and a record without an operator and timestamp is refused
(Stage-26 adversarial rule 17).

This framework **feeds** the existing intake in `release/hardware.py`.
It does not replace it. The intake remains the gate: it walks every string
of a submission for identifier leaks and it demands an existing artifact
for every claimed result.

## Minimum target device

| Requirement | Why |
|---|---|
| x86-64 | the only architecture the release gate scores |
| UEFI firmware | the boot path under qualification; legacy BIOS proves nothing about it |
| Secure Boot capable | blocks the Secure Boot evidence category no VM result can substitute for |
| TPM 2.0 | blocks two encryption-matrix scenarios; the record schema refuses anything else |
| NVMe or SATA SSD | the storage paths the installer targets |
| A named GPU | "graphics worked" must name the silicon and the driver it worked on |

## What is in this directory

| File | Purpose |
|---|---|
| `hardware-record.schema.json` | shape of the device record (JSON Schema draft 2020-12) |
| `test-run.schema.json` | shape of one per-test result record |
| `collect-hardware.sh` | DMI/PCI/USB/CPU/driver inventory, with built-in redaction pass |
| `collect-boot.sh` | journal, systemd-analyze, bootctl/bootc status, mounts, cmdline |
| `collect-power.sh` | upower, power supplies, suspend/resume journal markers |
| `collect-network.sh` | link state (MAC-redacted before write), device status, rfkill, listening sockets |
| `collect-graphics.sh` | DRM connector state, modes, bound GPU module and version |
| `collect-accessibility.sh` | orca/brltty/speech-dispatcher presence, a11y settings, brlapi key stat |

Every collector refuses to run (exit 2) where `/sys/class/dmi/id` is
absent, so none of them can be demonstrated on a development shell and the
output mistaken for evidence. A VM also has DMI — the check refuses the
obviously wrong environment; what establishes *physicality* is the
hardware record's binding (`installedArtifactDigest` plus a named operator
attesting to a real machine), not the collector.

## The physical test list

Twenty-nine tests, fixed in `test-run.schema.json` so a report cannot
invent a flattering test:

installer-boot, blank-disk-installation, encrypted-installation,
first-boot, gdm-login, gnome-session, wifi, ethernet, bluetooth, audio-io,
display-brightness, hidpi-scaling, external-display, usb-storage, suspend,
resume, hibernate, reboot, shutdown, lid-close-open, battery-status,
tpm-detection, secure-boot-development-path, update, rollback,
recovery-media-boot, encrypted-volume-recovery, keyboard-only-operation,
orca-operation.

Result vocabulary: `PASS`, `FAIL`, `PARTIAL`, `NOT_PRESENT`,
`NOT_SUPPORTED`, `NOT_RUN`.

- `NOT_PRESENT` is a statement about the device (no camera, no battery).
  **It is never a pass.**
- `NOT_SUPPORTED` means the hardware exists and the OS cannot drive it.
  Also never a pass.
- A `PASS` requires at least one evidence file with its sha256.
- A `NOT_RUN` row must carry **no** `observedAt` and **no**
  `evidenceFiles` — a not-run test observed nothing, and a row that says
  otherwise is refused rather than reinterpreted.

## Collection procedure

1. **Install** the candidate Bunny OS artifact on the target device and
   note its digest (`bootc status` reports it; `collect-boot.sh` captures
   it).
2. **Run the collectors on the device**, each into its own directory:

   ```sh
   ./collect-hardware.sh      out/hardware
   ./collect-boot.sh          out/boot
   ./collect-power.sh         out/power
   ./collect-network.sh       out/network
   ./collect-graphics.sh      out/graphics
   ./collect-accessibility.sh out/accessibility
   ```

   Each directory ends with a `manifest.sha256` binding every produced
   file to its digest, so later edits are detectable.
3. **Redact, then verify the redaction.** The collectors already strip
   MAC addresses, serial-bearing DMI fields, battery serials, hostnames
   (journal `--no-hostname`) and never print the Wi-Fi network name — but
   the redaction rules below still apply to *you*: read every file before
   it leaves the device. `collect-hardware.sh` writes
   `redaction-notes.txt` naming every redaction it performed.
4. **Fill the device record** and per-test records, and validate them
   against `hardware-record.schema.json` and `test-run.schema.json`
   (e.g. `python -m jsonschema`, or any draft 2020-12 validator). Tests
   you did not run stay `NOT_RUN` — the schemas will refuse the
   alternative.
5. **Submit through the existing intake**: place artifacts under
   `hardware/evidence/<report-id>/`, add the report to
   `operations/data/hardware-evidence.json`, and run

   ```sh
   python scripts/release.py validate-hardware-evidence
   ```

   The command fails closed. It re-checks redaction over every string and
   substantiation for every claimed result; passing the schemas here does
   not exempt a submission from that gate.

## Redaction rules

Must never appear in any committed file, in any field, in any log:

- serial numbers (chassis, board, product, disk, battery, display/EDID);
- MAC and Bluetooth addresses;
- `product_uuid`, asset tags, and any per-unit identifier;
- hostnames, usernames, Wi-Fi network names;
- the content of `/etc/brlapi.key` or any other secret (its existence,
  mode and owner are evidence; its bytes are a key).

The device is recorded by **class** (vendor, model, chipset, driver,
version), never by **identity**. `redactionStatus` in the device record
has exactly two values — `redacted` or `verified-clean` — and no
"not-required": for hardware there is no such state, because the risk is
the field nobody thought about. When in doubt, replace the value with
`REDACTED` and name the redaction in `redaction-notes.txt`.

## What this framework refuses, by construction

- A PASS with no evidence artifact (schema **and** intake reject it).
- A NOT_RUN carrying observations (schema rejects; the intake separately
  rejects NOT_RUN converted to a result).
- A record without operator or timestamps (schema requires both;
  Stage-26 adversarial rule 17).
- A device without TPM 2.0 posing as the qualification target
  (`tpm.spec` is `const "2.0"`).
- Collector output produced on a machine with no DMI tree (exit 2).
- The word "certified" — the intake refuses it; the permitted vocabulary
  is *tested*, *qualified for pilot*, *supported based on evidence*.

Until a machine exists, the honest content of this directory is exactly
what you see: schemas, collectors, and zero results.
