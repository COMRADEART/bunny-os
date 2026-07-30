# Physical hardware qualification report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NO MACHINE QUALIFIED. Zero reports submitted.**

`operations/data/hardware-evidence.json` contains an empty `reports` array. No
physical machine has run Bunny OS at any point in this project's history.

`python scripts/release.py validate-hardware-evidence` exits 2:

```text
BLOCKED: no x86-64 UEFI physical machine is fully qualified. This cannot be
produced by running more tests; it needs a device.
```

## What exists instead

An intake process that is ready to receive a report and will reject a bad one.
That is the deliverable of this phase; the qualification itself is not
achievable without hardware.

### Redaction is enforced, not requested

`release/hardware.py` walks **every string** in a submission — not only the
fields a submitter remembered to clean — and rejects the report if it finds a
MAC address, a labelled serial number, hostname or username, or a token that
looks like an asset tag. The risk is the field nobody thought about, so the scan
does not depend on anyone thinking about it.

Machines are recorded by class: `formFactor`, `chipsetClass`, `firmwareVendor`,
`firmwareVersion`. Never by identity.

### Claims must be substantiated

A report claims fifteen test outcomes. Every `PASS` or `FAIL` must name an
artifact that exists in `hardware/evidence/`. A report full of `PASS` values and
no artifacts is rejected:

```text
hw-0001: claimed results are unsubstantiated: install: no evidence artifact named
```

This is the check that distinguishes a qualification from an assertion, and it
is covered by the `fake physical-hardware report` adversarial test.

### There is no partial credit

A machine is qualified only when all fifteen tests resolve and none fails. One
`NOT_RUN` means the machine is not qualified, because the stable gate's hardware
row is a statement about a whole machine rather than about most of one.

## The fifteen tests

install, encryption, boot, secure-boot, tpm, network, audio, camera, suspend,
resume, update, rollback, recovery, bunny-disabled, local-only.

## The required first target

**At least one x86-64 UEFI physical machine.**

Preferred characteristics, ordered by how much other evidence they unblock:

| Characteristic | What it unblocks |
|---|---|
| Secure Boot | The `Secure Boot` evidence category, which no virtual result substitutes for |
| TPM 2.0 | The TPM fallback scenario in the encryption matrix |
| NVMe | The NVMe installation scenario against real firmware |
| Wi-Fi | Network evidence on a real adapter with real firmware |
| Audio, microphone, camera | Three hardware test rows |
| Suspend and resume | Two hardware test rows and the most common real-world failure |
| Integrated graphics | Session start without a discrete GPU |

Secure Boot and TPM are worth prioritising: they block evidence categories that
cannot be satisfied any other way.

## Why this cannot be worked around

Every other blocker in this phase either was closed, or has a documented route
to closure that involves running something. This one does not. There is no
sequence of commands on this builder that produces a physical hardware result,
and `operations/devqualification.py` has enforced that since before this phase:
an evidence row claiming `environment: physical` requires a report id that
resolves in the hardware evidence file, so a physical claim fails while the file
is empty.

That check was written to prevent exactly the temptation this report documents.

## Consequences

- The `Hardware` evidence category records `NOT_RUN` and blocks.
- The `Secure Boot` category records `NOT_RUN` and blocks.
- `gate-stable-release` reports `NO-GO` on `physical-hardware`.
- `gate-oem-pilot` reports `BLOCKED` on `qualifiedHardwareModel` and
  `factoryFinalisationOnHardware`. The OEM pilot cannot begin without a device
  even if every other blocker closed tomorrow.
- Two accessibility workflows — installer screen reader and encryption prompt —
  are additionally blocked on there being a machine to run them on.

## Submitting a report

See `hardware/evidence/README.md`. `hardware/evidence/template.json` is a
complete, correctly shaped example with every result `NOT_RUN`, and the test
suite asserts that the template itself does not claim a qualified machine.

```text
python scripts/release.py validate-hardware-evidence
make validate-hardware-evidence
```
