# Phase 5 baseline — the Phase 4 Alpha Release Candidate, as frozen

Written **before** any Phase 5 change, so that every later claim in Phase 5 has
something to be compared against that Phase 5 did not produce.

This file is a *record of Phase 4*, not a restatement of it. Phase 4's own
evidence lives in `qualification/phase4/` and **is never edited by Phase 5**.
Where a number here is disputed by a Phase 5 measurement, the Phase 5
measurement goes in `qualification/phase5/`, and this file stays as written.

---

## 1. Identity

| | |
| --- | --- |
| Phase 4 opened at | `b0b92482` |
| Phase 4 final tree commit | `e4d01389` |
| **Release-candidate artifact commit** | **`e906a48793d74544b39c14cc3e35e0654f5311e2`** |
| Phase 4 report | `ALPHA_RELEASE_CANDIDATE_REPORT.md` |
| Artifact identity record | `qualification/phase4/artifact/ARTIFACT.md` (+ `CORRECTION.md`) |
| Evidence file count | 166 |
| Status | **READY — Alpha Release Candidate only** |

**The candidate is the artifact, not the tree.** Twelve commits separate
`e906a487` from `e4d01389`, and eight of them touch `build/`, which is a
`COPY` root in `build/Containerfile`. A rebuild at `e4d01389` will **not**
reproduce the digests below. Any Phase 5 code change therefore requires a new
build identity (§3 of the Phase 5 directive); it may not inherit this one.

### Two corrections that are part of the baseline

`ARTIFACT.md` is committed evidence and was not edited. Two of its lines are
wrong and are corrected in `qualification/phase4/artifact/CORRECTION.md`:

* `dirty: 1 file(s)` → **`dirty: 0`**. The measurement was taken one minute
  after the last artifact was produced; the build's own log records `dirty: 0`
  at the moment it started.
* `localhost/bunny-os-beta:localhost/bunny-os-beta:e906a48793d7` →
  **`localhost/bunny-os-beta:e906a48793d7`**. A doubled prefix in the
  recording script.

Both are fixed at source in `build/scripts/rc-identity.sh`. Phase 5 inherits
the corrected values.

---

## 2. Artifact digests — frozen

### Live installation medium (the ISO an alpha tester writes)

    823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421
    bunny-os-0.3.0-live.e906a48793d7-x86_64.iso

### Shell-test machine image (voice and desktop qualification)

    83c31d0640e4aef6059004d5ff3f954879bd92a3723f4173dc71e53a39963a99
    bootc-fedora-44-qcow2-x86_64.qcow2

### Beta payload (the installed system's container image)

    localhost/bunny-os-beta:e906a48793d7
    manifest sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d

### Inputs

| | |
| --- | --- |
| Retained base image | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Base image location | `/var/lib/bunny-retention/base-images/sha256-c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b` |
| Builder image | `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` (source `9c525bf1`) |
| Package snapshot | `fedora-44-beta-20260810-tts`, manifest `fa89f5e28175abf037acb0e83a5a7fa2868b415db12732c2afff98017fb70ada` |
| Build timestamp | 2026-08-17T18:57:00Z (record); build stages 17:05:45Z → 18:56:00Z |
| Build environment | Fedora Linux 44 under WSL2, 22 cores, 15 GiB |

### Package versions of the parts Phase 4 changed

    gnome-shell-50.4-1.fc44        mutter-50.4-1.fc44
    gnome-settings-daemon-50.1-1.fc44
    accountsservice-23.13.9-16.fc44
    gdm-50.2-1.fc44               systemd-259.8-1.fc44

---

## 3. Test baseline

| Suite | Baseline `b0b92482` | RC-era uncontended runs |
| --- | --- | --- |
| Reference suite | 5737 passed, 24 skipped | 5762 run, **3 failed** (`cb2e819a`, `763a5b36`) |
| Installer sub-suite | 172 passed | 178 passed, OK — clean in every run |

**The reference suite is not reliably green.** Three tests in
`tests/companion/test_character_cli_vertical.py` fail intermittently: **5/5
alone, 1-in-3 inside `tests/companion`**. Phase 4 classified this as
cross-test interference and did not fix it. Closing it is Phase 5 §7.

Three runs were taken because the first two disagreed, and they failed for
three different reasons — a fact that is itself part of the baseline: one run
would have produced a wrong conclusion whichever one it had been.

---

## 4. Performance baseline

Instrument: the probe's `performance` verb. CPU as a **delta** in
`utime + stime` clock ticks read from `/proc` across a fixed idle interval —
*not* `ps`'s `%cpu`, which is an average since process start. RSS from
`VmRSS`.

| Process | Comparator `7edd3fd` | RC, 20 s | RC, 30 s |
| --- | --- | --- | --- |
| `gnome-shell` (4 procs) | 0.80 % / 391.2 MiB | 1.80 % / 388.7 MiB | **2.07 %** / 387.4 MiB |
| `companion` (1 proc) | 0.35 % / 61.6 MiB | 0.50 % / 63.1 MiB | **0.47 %** / 63.2 MiB |
| `orca` | 0.00 % | not running | not running |

* **Memory is flat.** The shell is 3.8 MiB *lower* than the comparator.
* **CPU is a real regression**: ~1.3 percentage points of one core, 2.6×.
* It is **steady state, not settling** — the second sample is *higher* than
  the first (1.80 → 2.07 %).
* The comparator record is `qualification/design/performance.json`.
  `qualification/voice-release/evidence/final/logs/cpu-idle.json` also holds
  an idle sample (7.75 %, 322.3 MiB) but from a different instrument over a
  60 s window on the voice image, and is **not** the comparator.

Phase 4's named first hypothesis, carried into Phase 5 §9 as a hypothesis and
not as a finding: UI polling, with the System overview card's 2 s cadence
first.

### Poller inventory as of `e4d01389` (source-read, not measured)

| Timer | Cadence | Site |
| --- | --- | --- |
| System overview card | 2 s | `lib/cards/systemOverview.js:35` |
| System monitor card | 2 s | `lib/cards/systemMonitor.js:37` |
| Media widget card | 2 s | `lib/cards/mediaWidget.js:28` |
| Assistant health poll | 2 s, ≤30 attempts | `lib/desktopShell.js:411` |
| Voice health poll | 2 s, ≤30 attempts | `lib/desktopShell.js:411` |
| Bottom dock (running apps) | 3 s | `lib/bottomDock.js:65` |
| Top bar indicators | 5 s | `lib/topBar.js:51` |
| Extension status timer | 5 s | `extension.js:202` |
| Housekeeping | 30 s | `lib/desktopShell.js:167` |
| Agenda widget | 60 s | `lib/cards/agendaWidget.js:28` |
| Clock | 60 s | `lib/topBar.js:215` |

The two health polls are **bounded** and stop on the first success, so they
are startup cost rather than idle cost. Phase 4's report named three timers;
the full set is eleven, and three of them run at 2 s.

---

## 5. Voice baseline

`voice-phase3-b`, `exit=0`, 19 stages — **identical** to the Phase 3 record.
Voice end to end on real audio, on the artifact.

---

## 6. Trust baseline

| | Granted (`g12`) | Denied (`g13`) |
| --- | --- | --- |
| Prompt drawn and answered | yes | yes |
| Decision recorded | `granted` | `denied` |
| Capsule started | **yes** | **no** |
| Produced | `holiday-resized.png`, 100×50 | nothing |
| Final state | `idle` | `idle` |
| Input digest after | unchanged | unchanged |
| Untouched neighbour | unchanged | unchanged |
| `findings` | `[]` | `[]` |

The denial is the stronger result: **no capsule unit was ever started**, and
that is a measurement rather than an absence of instrumentation, because the
granted run shows the same journal line present.

`g13`'s fixture cleared `…/exports/holiday-resized.png` — the file `g12` had
just created — so "nothing was produced" is distinguishable from "the
previous run's file is still there".

---

## 7. Installation baseline

| Dimension | Result |
| --- | --- |
| Encrypted install from the RC's own ISO | **PASS** — `findings: []`, ISO digest hashed by the run before it installed |
| Encrypted boot | **PASS** — two boots |
| First login through the real greeter | **PASS** — `g1` |
| First-run wizard | **PASS** — 11 of 11 choices applied |
| Second and third account | **PASS** — `robin` reaches the Bunny desktop (`g10`) |
| ACPI power key | **PASS** — clean shutdown on every boot of the chain (11 boots, `qualification/phase4/power-key/`) |

---

## 8. Persistence baseline

`g2 → g3 → g4` across two reboots. Settings and companion modes survive.
`character.companionMode` persists `compact` and `minimal` across two reboots.

The machine disk is **deliberately persistent** across the chain — its history
*is* the persistence evidence.

---

## 9. Known limitations carried into Phase 5

Each is stated as Phase 4 left it. Where Phase 5 changes the diagnosis, the
change is recorded in the Phase 5 report and **not** back-edited here.

| # | Limitation | Phase 4 disposition |
| --- | --- | --- |
| L1 | Reference suite not reliably green — CLI-vertical ×3, 1-in-3 in-package | Recorded, not fixed |
| L2 | Shell idle CPU 2.07 % vs 0.80 % at `7edd3fd` | Recorded as a tracked number |
| L3 | The greeter is stock Fedora, not Bunny | Recorded; not fixable without a rebuild |
| L4 | `bunny-nocturne.svg` fails to load — `Unknown image format: application/xml` | Recorded; diagnosis given as "the image has no SVG pixbuf loader" |
| L5 | The `Diagnostic-`/`s` tile — Pango `WORD_CHAR` inserts a hyphen | Recorded, cosmetic |
| L6 | The qualification harness grades without being graded | Named as the highest-value next work |
| L7 | 59 inherited Critical/High findings from `fedora-bootc:44`, no independent review | Outside Phase 4 |
| L8 | No physical machine has ever booted the candidate | Outside Phase 4 |
| L9 | No production signing key | Outside Phase 4 |
| L10 | Update and rollback matrices `NOT_RUN` | Outside Phase 4 |
| L11 | Host build volume: 11 GB free | Standing operator risk |

**L4's stated diagnosis is wrong and Phase 5 corrects it by measurement** —
see the Phase 5 report §8. `librsvg2-2.62.3-1.fc44`, `glycin-loaders-2.1.5-1.fc44`,
`glycin-libs` and `glycin-gtk4-libs` are all installed in the artifact
(`qualification/phase4/artifact/p4-build.log` lines 359, 369–371, 551). A
loader is present. This is recorded here because acting on the Phase 4
diagnosis would have meant adding a package that already ships.

---

## 10. Release gates as Phase 4 left them

`scripts/release.py gate --kind qualification-candidate` → **BLOCKED**
`scripts/release.py gate --kind stable-release` → **NO-GO**

| Gate | Phase 4 state |
| --- | --- |
| Installation | PASS |
| Encryption | PASS |
| First boot | PASS |
| Login | PASS |
| Voice | PASS |
| Trust | PASS |
| Persistence | PASS |
| Companion | PASS |
| Shutdown | PASS |
| Reference suite | INTERMITTENT |
| Security review | NOT DONE |
| Physical hardware | NOT RUN |
| Production signing | NOT DONE |
| Update | NOT RUN |
| Rollback | NOT RUN |
| Owner approvals | NOT DONE |

---

## 11. The finding Phase 5 is built on

Phase 4's largest output was not a product result. It was **six harness
defects, four of which had been producing passes** — see
`ALPHA_RELEASE_CANDIDATE_REPORT.md` §17. The instrument was wrong more often
than the product was.

The rules that came out of it, which Phase 5 inherits as constraints:

1. A journey that cannot fail is not a test. Grade the **outcome**, not the
   machine's health.
2. Before trusting a strengthened grader, **replay it over a recorded run
   that should fail**.
3. A denial must mean the confined program **never ran** — read from the
   journal, with the granted run as the control, so absence is a measurement.
4. Cleanup steps must **report what they removed**.
5. Redact secrets **before** publication; evidence is immutable.
6. One passing run is a sample, not a confirmation.
