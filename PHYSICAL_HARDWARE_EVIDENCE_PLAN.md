<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Physical hardware evidence plan

Date: 2026-07-30
Current state: **zero reports, zero collections. No physical machine has ever run
Bunny OS.**

This plan exists so that when a device arrives, the evidence it produces is
already specified. Nothing here has been executed.

## The required first target

**One x86-64 UEFI machine with Secure Boot and TPM 2.0.**

Ordered by how much other evidence each characteristic unblocks:

| Characteristic | Unblocks |
|---|---|
| Secure Boot | the `Secure Boot` evidence category, which no virtual result substitutes for |
| TPM 2.0 | the TPM fallback scenario in the encryption matrix |
| NVMe | the NVMe installation scenario against real firmware |
| Wi-Fi | network evidence on a real adapter with real firmware |
| Audio, microphone, camera | three test rows |
| Suspend and resume | two test rows, and the most common real-world failure |
| Battery | one test row, and unmeasurable in a VM |
| Integrated graphics | session start without a discrete GPU |

Secure Boot and TPM are worth prioritising: they block evidence categories that
cannot be satisfied any other way.

## The collector

```text
bunny-os qualification collect
```

An **allow-list of seventeen facts**, recorded as classes rather than identities.
There is no code path that walks the system and reports what it finds, because that
is how a serial number ends up in an evidence file.

| Field | Recorded as |
|---|---|
| `bunnyOsVersion` | from `/usr/lib/bunny-os/release.json` |
| `sourceCommit` | same |
| `imageDigest` | same |
| `architecture` | `platform.machine()` |
| `firmwareMode` | `uefi`, `uefi-secure-boot` or `legacy-bios` |
| `secureBootState` | from the EFI variable's flag byte |
| `tpmAvailable` | boolean |
| `cpuFamily` | vendor and family/model **numbers**, not the marketing string |
| `gpuFamily` | the DRM driver name |
| `ramSizeCategory` | a band, not a byte count |
| `storageType` | `nvme`, `sata-ssd`, `sata-hdd`, `emmc`, `virtual` |
| `wifiChipset` | the driver name |
| `bluetoothChipset` | the driver name |
| `kernel` | `platform.release()` |
| `driverVersions` | `/sys/module/<name>/version` for the drivers found |
| `testResults` | the 21 guided outcomes |
| `recoveryMediaDigest` | SHA-256 of the recovery media, if supplied |

### Excluded, by name

`serialNumber`, `macAddress`, `ipAddress`, `hostname`, `username`,
`wifiNetworkName`, `personalPaths`, `personalFiles`, `bunnyPrompts`, `bunnyMemory`,
`browserHistory`, `assetTag`.

The collector has no function that reads any of them. A test asserts the module's
source contains none of `/address`, `gethostname`, `getpass`, `getlogin`, the
network daemon's name, or `iwconfig`.

`assert_collector_scope` refuses a submission carrying an excluded field by name,
and refuses any field outside the allow-list — so adding one is a reviewable act
rather than an accident.

### Redaction is enforced on top

`redaction_findings` walks **every string** in a submission, not only the fields a
submitter remembered to clean, and rejects the report on a MAC address, a labelled
identifier, or a serial-like token. The risk is the field nobody thought about, so
the scan does not depend on anyone thinking about it.

## The twenty-one guided tests

```text
boot                  installation          encrypted-installation
secure-boot           tpm                   graphics
display               wifi                  bluetooth
audio                 microphone            camera
suspend               resume                battery-reporting
update                rollback              recovery
bunny-disabled-mode   local-only-mode       accessibility
```

Each records: start time, end time, operator, expected result, actual result,
outcome, evidence reference, notes, relevant logs, redaction status.

### `NOT_RUN` is never converted to `PASS`

The rule this whole module exists for. `parse_guided_test` rejects a record
claiming `NOT_RUN` while carrying an actual result or an evidence reference:

```text
recorded NOT_RUN but carries actualResult. A test that produced a result was run;
NOT_RUN must never be converted to PASS
```

And `PASS` or `FAIL` requires an evidence artifact that exists:

```text
outcome PASS must name an evidence artifact; a claimed result with no artifact is
an assertion
```

A machine is qualified only when **all** tests resolve and none fails. There is no
partial credit: the stable gate's hardware row is a statement about a whole machine
rather than about most of one.

## Running it

```sh
# on the device under test
bunny-os qualification tests                     # list the 21 tests

bunny-os qualification record \
  --test boot --outcome PASS \
  --operator "<name>" \
  --expected "the system reaches the login screen" \
  --actual   "reached the login screen in 18 seconds" \
  --evidence boot.log --redaction completed

bunny-os qualification collect --recovery-media /path/to/recovery.iso
bunny-os qualification report --operator "<name>" --output report.json
```

Then, in the repository:

```sh
cp report.json operations/data/hardware-collections.json   # into the collections array
python scripts/release.py validate-hardware-evidence
```

## Signing the evidence

Three roles, and each says a different thing:

| Role | Attests |
|---|---|
| `test-operator` | the report describes what they saw |
| `approved-laboratory` | the laboratory ran the tests under its own procedures |
| `project-maintainer-after-verification` | a maintainer independently verified the submitted evidence — **not** that they ran the tests |

A maintainer signature must record *how* it verified; otherwise it attests only
that a file was read.

**The signature proves report integrity, not hardware certification.** The word
`certified` — and `certification`, `certifies`, `certify` — is refused in code, in
notes, in expected and actual results, in signature statements, and by the
collector. The permitted vocabulary is:

```text
tested
qualified for pilot
supported based on evidence
```

## Why this cannot be worked around

There is no sequence of commands on any builder that produces a physical hardware
result. `operations/devqualification.py` has enforced that since before this phase:
an evidence row claiming `environment: physical` requires a report id that resolves
in the hardware evidence file, so a physical claim fails while the file is empty.

That check was written to prevent exactly the temptation this plan documents.

## Consequences while it stays empty

- `Hardware` and `Secure Boot` evidence categories record `NOT_RUN` and block.
- `physical-hardware-evidence` reports `PENDING_HARDWARE` with the dependency *"one
  x86-64 UEFI machine with Secure Boot and TPM 2.0"*.
- `gate-stable-release` reports `NO-GO` on `physical-hardware`.
- `gate-oem-pilot` reports `BLOCKED` on `qualifiedHardwareModel` and
  `factoryFinalisationOnHardware`. The OEM pilot cannot begin without a device even
  if every other blocker closed tomorrow.
- Two accessibility flows are additionally blocked on there being a machine.

## Evidence

- `hardware/evidence/README.md`, `hardware/evidence/template.json`
- `operations/data/hardware-evidence.json` — zero reports
- `operations/data/hardware-collections.json` — zero collections
- `tools/bunny-os/bunny_os/qualification.py` — the collector
- `release/hardware.py` — intake, redaction, substantiation, signatures
- `tests/hardware_evidence/` — 62 tests, including the fake-report,
  serial-number and `NOT_RUN`-marked-`PASS` cases
