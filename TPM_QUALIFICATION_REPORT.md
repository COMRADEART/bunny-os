<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# TPM qualification report

Software-TPM boot qualification of the qualified archive
(Commit G `b9c317d3`, archive `29e54aaf…`, QCOW2 `0b7dd90d…`), under the
`tpmq-1` authority (Commit K). Root cause of the blocking symptom:
`TPM_GRUB_RESET_ROOT_CAUSE.md`, confidence **CONFIRMED**.

## Fix classification: Path A — harness-only defect

The reset was shim fallback's designed one-time boot-option-restoration
reboot; the artifact required no change and received none. The defective
component was the qualification harness:

| Harness defect | Correction |
| --- | --- |
| `-no-reboot` terminated QEMU at the first guest reset, so the boot design's single deliberate reboot recorded as a dead guest | the `tpmq` runner classifies resets from QMP events and, in continuation mode, observes what follows them; `-no-reboot` is reserved for stop-and-inspect classification runs |
| every run received a fresh OVMF variable store with no model of what that means (the removable/fallback path on every boot) | fresh vs reused variable stores are an explicit experimental axis with declared expectations: fresh boots owe exactly one restoration reset with a TPM, reused boots owe zero |
| no QMP event capture, so "reset" was inferred from the screen | every run records the full event stream; a reset claim without a QMP event in its basis is refused by the adversarial battery |
| swtpm stdout/stderr discarded | captured per run |
| floating `q35` machine alias | pinned `pc-q35-10.2` in the authority |

Path A obligations and their discharge:

* **Fix the harness** — `qualification/tpm/scripts/run_tpm_experiment.py`
  and `run_matrix.py`, above.
* **Retain the old records as invalidated harness evidence** — the
  `ISQ-20260801-tpm-present-*` and `tpm-absent-*` records remain untouched
  under `qualification/installed-system/evidence/`; the installed-system
  report carries a superseded-finding note. They are not importable as TPM
  results: they bind to `isq-1`, not `tpmq-1`.
* **Rerun the full paired matrix** — `TPM_BOOT_REGRESSION_REPORT.md` and
  `qualification/tpm/evidence/matrix-summary.json`.
* **No new archive target** — no artifact byte changed; Commit G/H/I/J and
  every digest they bind remain the authority. Nothing was relabelled.
* **New scenario authority** — `tpmq-1`
  (`qualification/tpm/evidence-context.json`, Commit K). The retired
  `isq-1` TPM scenarios (`tpm-present`, `tpm-absent`) are superseded by the
  `tpmq-1` matrix; non-TPM `isq-1` evidence is unaffected.

## What this pass establishes

```text
QEMU/KVM TPM integration:  PASS   (crb and tis device models, socket-backed swtpm)
OVMF TPM boot path:        PASS   (TCG2 protocol exposed and consumed through completed boots)
GRUB TPM boot path:        PASS   (Fedora GRUB 2.12 loads and boots with a TPM present and
                                   enumerated, no GRUB TPM error in any transcript; this is
                                   "does not fail", not "measurements verified" — see
                                   TPM_GRUB_ISOLATION_REPORT.md)
software-TPM regression:   PASS   (matrix below; reset count zero outside the designed
                                   restoration reboot, which occurs exactly once per fresh
                                   variable store and never otherwise)
```

The gate that computes this is `make tpm-qualification-gate`
(`import_tpm_results.py`): supported cells at five boots each, every record
bound to the authority, internally consistent, hash-verified, every reset
classified, `UNKNOWN` blocking, and the no-TPM control passing before any
TPM cell counts.

Its measured output over the whole matrix:

```text
records                       87
problems                       0
no-tpm-cold        5/5   resets 0     satisfied
crb-fresh-cold     5/5   resets 5     satisfied   (one designed restoration reboot per boot)
tis-fresh-cold     5/5   resets 5     satisfied   (identical on the other interface)
crb-reused-cold    5/5   resets 0     satisfied
tis-reused-cold    5/5   resets 0     satisfied
crb-qemu-reset     5/5   resets 0     satisfied   (platform reset, complete second boot)
tis-qemu-reset     5/5   resets 0     satisfied
retained evidence  831 files, all digest-verified against their records
softwareTpmBoot    PASS
physicalTpm        NOT_RUN
```

Thirty-five supported boots, plus fifty-two control, reproduction and
diagnostic boots. Every reset in the matrix is classified; none is
`UNKNOWN`.

## What this pass can not establish, and does not claim

```text
Physical TPM hardware:        NOT_RUN   (structurally: no record of this schema can claim it)
OEM firmware compatibility:   NOT_RUN
Production Secure Boot:       NOT_QUALIFIED (development firmware exists; no keys were created)
TPM-bound disk unlock:        NOT_QUALIFIED (no such product feature exists to test)
TPM recovery behaviour:       NOT_QUALIFIED
Global hardware qualification: unchanged
```

The importer emits `physicalTpm: NOT_RUN` unconditionally; no software-TPM
record can move it, and `tests/tpm/` proves the relabelling frauds
(VM-as-physical, TCG-as-KVM, no-TPM-as-TPM, disabled-TPM-as-qualified) are
refused by structure.

## The TPM under test: identity, banks, capabilities

Collected from the pinned swtpm build with `tpm2-tools` against a freshly
initialised state directory; raw output in
`qualification/tpm/evidence/swtpm-capabilities/`.

| Property | Value |
| --- | --- |
| Manufacturer | `IBM` (`0x49424D00`) |
| Vendor string | `SW` |
| Firmware version | `0x20240125` |
| Startup | `TPM2_Startup(CLEAR)` accepted |
| PCR allocation | sha1, sha256, sha384 **and** sha512 banks, PCRs 0–23 each |
| swtpm features | tpm-1.2, tpm-2.0, flags-opt-startup, cmdarg-seccomp, cmdarg-migration, nvram-backend-dir/file, tpmstate-opt-lock |

The PCR-bank configuration was **not** changed. Every cell ran against the
default allocation above, so bank configuration is not a variable in any
result and no result is contingent on one. A deliberate bank experiment
would be a distinct cell with its own record, and none was run.

An event log was not collected: the product parses none, no boot path in
these runs consumes one, and collecting one would have meant adding a
component to the boot chain being measured.

## The firmware under test: what was verified, not assumed

| Question | Answer, and how it was established |
| --- | --- |
| TPM-capable? | Yes — proven by behaviour, not filename: shim's `fallback_should_prefer_reset()` locates a TCG/TCG2 protocol on this firmware, which is the branch that produces the restoration reset, and the guest enumerates the TPM in every completed boot |
| Compatible with both selected QEMU TPM interfaces? | Yes — `tpm-crb` and `tpm-tis` produce identical firmware behaviour across every paired cell |
| Secure-Boot-capable? | A separate secboot image ships in the same package (`OVMF_CODE_4M.secboot.qcow2`, sha256 `377708ac44c1…`) and was **not** used; every record's `secureBootState` is `disabled` |
| SMM state | `off` in the supported path (no `smm=on` machine option); an SMM-on diagnostic cell is recorded separately |
| Identity | package `edk2-ovmf-20260508-6.fc44.noarch`; code image sha256 `6551948da24a…`; variable template sha256 `035317bb2923…` — all three pinned in the authority and re-derived on every context resolution |

No OVMF debug build was used. Every firmware observation above comes from
the release image the product's qualification actually runs.

## Coverage this pass does not have

* **OS-level `reboot` from a logged-in session** is not measured; the
  harness cannot drive it without login injection. Guest-initiated reset
  (shim's in-guest `ResetSystem`) and platform reset (QMP `system_reset`)
  are measured instead. `TPM_BOOT_REGRESSION_REPORT.md` states the gap, and
  so does the gate's own machine-readable output.
* **Failed-unit data is the serial console's view**, not the journal's. The
  offline journal classification (`dispose_failed_units.py`) was not re-run
  in this pass, so this pass neither confirms nor revises the BrlAPI pass's
  `gdm`/`avahi-daemon` intermittency finding.
* **Secure Boot** was not exercised at all: no development-firmware boots
  were run, no keys of any kind were created, and `secureBootState` is
  `disabled` in every record. The consistency layer refuses any record
  claiming otherwise.

## User-visible behaviour worth knowing

First boot of the shipped disk image on a TPM-equipped machine with empty
NVRAM shows shim's five-second "Boot Option Restoration" countdown and
reboots once before the OS appears; an operator can press a key and choose
"Continue boot", and `FB_NO_REBOOT=1` (shim variable) suppresses the reboot
permanently. The mechanism is upstream shim 16.1's, not Bunny's: the code
path is in the distribution's `fallback.c`, and a stock Fedora Cloud 44
disk under the identical harness reproduces it exactly — 3/3 with one
restoration reset each when a TPM is attached, 3/3 with zero resets when it
is not (`TPM_BOOT_REGRESSION_REPORT.md`). Recorded in
`KNOWN_LIMITATIONS.md`.

## Gate positions after this pass

Unchanged unless the gate itself recalculates them:

```text
Archive reproducibility:  PASS (Commit H)
BrlAPI engineering:       PASS (Commit J)
Software TPM boot:        PASS (this pass)
Physical TPM:             NOT_RUN
Encryption:               NOT_QUALIFIED
Global SELinux:           BLOCKED
Global accessibility:     NOT_RUN
Update/rollback/recovery: NOT_RUN
Independent reviews:      PENDING
Production signing:       BLOCKED
Qualification candidate:  calculated by the gate, not by this report
Stable release:           NO-GO
Pilots:                   BLOCKED
```
