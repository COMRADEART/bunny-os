# Phase 3 full-suite results — baseline, current, delta

## Baseline

Stage 2 close (commit 375fa830): Linux reference target 5734 tests, 7
failures — all seven closed at the opening of Phase 3 (presentation-pressure
flake, hysteresis recovery, SPDX headers, pins, ShellCheck; tasks recorded in
the Phase 3 report). Windows interim at the same era: 5,6xx tests, 7 errors +
1 failure, all environmental.

## Current — commit 04e294f5 (artifact commit 376acf0e; image-side delta none)

### Windows host (win-suite log in this directory)

Ran 5698, **failures=1, errors=7**, skipped=131.

| Test | Class | Detail |
| --- | --- | --- |
| tests.capsules.test_launcher_section.TheQuoting — 6× `test_a_metacharacter_stays_a_character`, 1× `test_an_apostrophe_survives` | PRE-EXISTING, ENVIRONMENTAL | `FileNotFoundError: [WinError 2]` — the quoting tests execute a POSIX shell that does not exist on Windows. Pass on the Linux reference target. |
| `test_provenance_accounts_for_every_selected_tts_byte` | PRE-EXISTING, ENVIRONMENTAL | 436604323 != 436603718 — zlib/libm output differs between Windows and Linux and shifts the packaged-asset byte total (the recorded generated-assets portability limitation). Passes on Linux. |

**NEW failures: none. FIXED since baseline: the seven Stage 2 Linux
failures. No ambiguity class is used.**

### Linux reference target (linux-suite log in this directory)

Recorded from the ext4 copy as user `bunny` (the reference-runbook
conditions): **Ran 5737 — OK, 24 skipped**, then the installer sub-suite
**Ran 172 — OK**; `linux-suite exit=0`. Zero failures, zero errors.

**NEW failures: none. The seven Stage 2 baseline failures: FIXED.**

One interim re-run (after the host-storage incident killed the first run
mid-suite) reported 48 failures + 7 errors; every one was HARNESS /
ENVIRONMENTAL, not product: the rebuilt suite copy was root-owned (git
"detected dubious ownership" as `bunny`) and its rsync had excluded
`.git/objects/pack`, breaking git-history-backed tests. The copy was
rebuilt as a `git clone --local` owned by `bunny` and the run above —
the governing verdict — went clean without any product change.

## Delta

| | Baseline (Stage 2 close) | Current (04e294f5) |
| --- | --- | --- |
| Linux | 5734 ran, 7 failures | 5737 + 172 ran, 0 failures, 0 errors |
| Windows | 5,6xx ran, 1F + 7E environmental | 5698 ran, 1F + 7E, same causes |

FIXED: the seven Stage 2 Linux failures. NEW: none. PRE-EXISTING +
ENVIRONMENTAL: the eight Windows-host records above. No ambiguity class
is used anywhere in this file.
