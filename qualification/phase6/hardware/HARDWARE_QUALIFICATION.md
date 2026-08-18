# Physical hardware qualification

## Status: **NOT_RUN**

No physical machine is available to this project. Every result it has ever
produced is QEMU with software rendering. That sentence is not softened here and
nothing below converts it into anything else.

**NOT_RUN is a real outcome and it is blocking.** Blocking condition 3 is unmet
and no repository change can move it.

---

## 1. What Phase 6 adds

The device record, the collector, its privacy allow-list and the intake gate
already exist and are good: `release/hardware.py` defines seventeen collector
fields as an allow-list, names twelve excluded categories so the exclusion is
testable, records RAM by category rather than byte count, and refuses to qualify
a machine with any `NOT_RUN` test. `PHYSICAL_HARDWARE_EVIDENCE_PLAN.md` names
the target device class, and Phase 5's `HARDWARE_TRACK.md` bound the track to an
artifact.

None of that is restated. What was missing is the thing §17 requires:

> Every new journey must define `expectation.json` before execution.

Three journeys now do, and they were committed before any machine existed —
which is the only moment at which an expectation can be written honestly.

| Journey | Covers | Steps |
| --- | --- | ---: |
| `H1-boot-chain` | medium → boot → installer → encrypted install → login → desktop → Companion → reboot → persistence | 9 |
| `H2-renderer` | 3D, capability loss, capability restoration, pre-rendered, procedural 2D, switching | 6 |
| `H3-voice` | permission, denial, capture, recognition, synthesis, interruption, cancellation, offline | 8 |

---

## 2. What is bound

| | |
| --- | --- |
| Artifact | `e906a48793d7` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Installation medium | `bunny-os-0.3.0-live.e906a48793d7-x86_64.iso` |
| ISO digest | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |

The medium exists on the builder and its digest was re-verified during the
Phase 6 baseline freeze. **The digest must be checked again on the writing host
and once more by reading back the written medium**, before the machine is
powered on. Checking only on the host does not detect a bad write, and a hardware
report produced from a corrupted stick describes something that is not the
candidate.

---

## 3. The failure modes the expectations were written against

Each of these is a real defect this project has already found somewhere else,
encoded so a hardware run cannot repeat it:

* **A live boot recorded as an installation result.** H1 grades NOT_RUN if
  H1.1 passes and H1.3 does not. A successful live boot is a boot result.
* **A renderer measured under llvmpipe presented as a GPU result.** H2.1
  records the GL renderer string; if it says llvmpipe, every number in that
  journey is a VM number and is labelled as one.
* **A preference silently destroyed by a fallback.** H2.2 fails on preference
  destruction even when the fallback itself is flawless. Falling back cleanly
  while forgetting what the user chose is the defect, not the mitigation.
* **A capture path that is a loopback.** H3.3 grades NOT_RUN if the source is a
  monitor or null-sink loopback. That is how the VM voice work had to be run;
  it is not a microphone result.
* **A player resolved to a sibling of a multi-call binary.** H3.5 records the
  program and arguments as invoked. `paplay` resolving to `pacat` once played
  0.73 s of noise, exited 0, and left every gate green.
* **Cancellation measured only by its effect.** H3.7 requires the control
  plane's own answer. Voice-cancel had never worked while the instrument
  reported that it had.
* **A permission prompt that is drawn but cannot be pressed.** H3.1 requires the
  prompt to be answered with the machine's real input devices.
* **Denial tested after grant.** H3.2 runs first, in the file, so the order is
  not decided at run time by whoever is holding the machine.
* **A device described after the failure.** H1's precondition P1 requires the
  device record before first boot.

---

## 4. One machine is one row

§6: *"Do not generalize one machine into universal compatibility. Each machine
is one data point."*

`release/hardware.py` already enforces the useful half — the intake requires at
least one fully qualified x86-64 UEFI machine and refuses a report with any
`NOT_RUN` test. The support matrix stays as it is until there are enough rows to
say something about a class, and the first row will not be one.

---

## 5. What would close it

One x86-64 UEFI machine with Secure Boot and TPM 2.0, a real GPU, a real
microphone and a real audio output, that can be wiped. Then H1, H2 and H3 run
end to end against the medium above, with the device record written first.

Until then this gate is **NOT_RUN**, and Phase 6 does not present the existence
of a well-specified plan as progress against it.
