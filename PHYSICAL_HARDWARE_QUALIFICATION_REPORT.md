# Physical hardware qualification report

Date: 2026-07-30
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`
Result: **NO MACHINE QUALIFIED. Zero reports submitted, zero collections
submitted.**

`operations/data/hardware-evidence.json` contains an empty `reports` array and
`operations/data/hardware-collections.json` an empty `collections` array. No
physical machine has run Bunny OS at any point in this project's history.

`python scripts/release.py validate-hardware-evidence` exits 2:

```text
hardware evidence: 0 accepted of 0 submitted
qualified x86-64 UEFI machines: none
guided collections: 0 accepted of 0 submitted, 0 complete and signed
BLOCKED: no x86-64 UEFI physical machine is fully qualified. This cannot be
produced by running more tests; it needs a device.
```

## What exists instead

An intake process that is ready to receive a report and will reject a bad one,
and — added by the qualification evidence closure — an **on-device collector** and
a **guided test runner** so that a device produces the right evidence the first
time.

That is the deliverable; the qualification itself is not achievable without
hardware.

### The collector added this phase

```text
bunny-os qualification collect
bunny-os qualification record --test <name> --outcome <PASS|FAIL|NOT_APPLICABLE|NOT_RUN> …
bunny-os qualification report --operator <name>
```

An **allow-list of seventeen facts**, recorded as classes rather than identities:
CPU vendor and family *numbers* rather than a marketing string, a RAM size *band*
rather than a byte count, a Wi-Fi *driver name* rather than an interface or a
network.

Twelve categories are excluded by name — serial number, MAC and IP address,
hostname, username, Wi-Fi network name, personal paths and files, Bunny prompts and
memory, browser history, asset tag — and the collector has no function that reads
any of them. A test asserts its source contains none of `/address`, `gethostname`,
`getpass`, `getlogin`, the network daemon's name, or `iwconfig`.

`assert_collector_scope` refuses a submission carrying an excluded field *by name*,
so adding one is a reviewable act rather than an accident.

### Twenty-one guided tests, up from fifteen

The intake gate still scores fifteen. The guided runner covers twenty-one, adding
`graphics`, `display`, `bluetooth`, `microphone`, `battery-reporting` and
`accessibility`. Each records start and end time, operator, expected result, actual
result, outcome, evidence reference, notes, logs and redaction status.

### Signatures, and a word that is refused

Three signer roles — `test-operator`, `approved-laboratory`, and
`project-maintainer-after-verification`, the last of which must record *how* it
verified or it attests only that a file was read.

**A signature proves report integrity, not hardware certification.** The word
`certified` and its family are refused in code: in notes, in expected and actual
results, in signature statements, and by the collector. The permitted vocabulary is
`tested`, `qualified for pilot`, `supported based on evidence`.

See `PHYSICAL_HARDWARE_EVIDENCE_PLAN.md` for the full plan and the running
instructions.

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

### `NOT_RUN` is never converted to `PASS`

Added this phase, and it is the conversion the whole module exists to prevent.
`parse_guided_test` rejects a record claiming `NOT_RUN` while carrying an actual
result or an evidence reference:

```text
recorded NOT_RUN but carries actualResult. A test that produced a result was run;
NOT_RUN must never be converted to PASS
```

The on-device collector refuses the same thing before it can be written down.

### There is no partial credit

A machine is qualified only when all fifteen tests resolve and none fails. One
`NOT_RUN` means the machine is not qualified, because the stable gate's hardware
row is a statement about a whole machine rather than about most of one.

## The fifteen tests the gate scores

install, encryption, boot, secure-boot, tpm, network, audio, camera, suspend,
resume, update, rollback, recovery, bunny-disabled, local-only.

All fifteen map into the twenty-one guided tests, and a test asserts the mapping.

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
- The `physical-hardware-evidence` candidate prerequisite reports
  `PENDING_HARDWARE` with the dependency *"one x86-64 UEFI machine with Secure Boot
  and TPM 2.0"*. It is one of six of the fourteen that no further work in this
  repository moves.
- `gate-stable-release` reports `NO-GO` on `physical-hardware`.
- `gate-oem-pilot` reports `BLOCKED` on `qualifiedHardwareModel` and
  `factoryFinalisationOnHardware`. The OEM pilot cannot begin without a device
  even if every other blocker closed tomorrow.
- Two accessibility workflows — installer screen reader and encryption prompt —
  are additionally blocked on there being a machine to run them on.

## Submitting a report

See `hardware/evidence/README.md` and `PHYSICAL_HARDWARE_EVIDENCE_PLAN.md`.
`hardware/evidence/template.json` is a complete, correctly shaped example with
every result `NOT_RUN`, and the test suite asserts that the template itself does
not claim a qualified machine.

```text
python scripts/release.py collect-hardware-evidence     # what the collector gathers
python scripts/release.py validate-hardware-evidence

make collect-hardware-evidence
make validate-hardware-evidence
```

Covered by 62 tests in `tests/hardware_evidence/`, including the fake-report,
serial-number and `NOT_RUN`-marked-`PASS` adversarial cases.
