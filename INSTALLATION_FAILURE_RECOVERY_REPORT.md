# Installation failure and recovery report

Date: 2026-08-16  
Evidence: `qualification/installer-journeys/evidence/journey-d/`; backend
behaviour in `installer/backend/server.py` and `installer/backend/anaconda.py`
Result: **a deliberate failure did not produce success, and real failures
surfaced enough evidence to be diagnosed without a debugger in the guest.**

## Journey D: the refusal that has to hold

Journey D walks the full flow and types a deliberately wrong confirmation
phrase. What the run recorded:

- the destructive button never enabled; the driver reported
  **refused-as-expected** after 14 stages;
- the machine was powered off and the disk read from outside anyway —
  `installed.json` finds *no bootloader entry and no deployment*, which for
  this journey is the pass: refusing to install must leave nothing installed;
- the harness passes D on the refusal, not on the disk gate, and says so in
  its own source.

The confirmation phrase is generated per run (`ERASE /dev/vda A0EDDF` —
device plus a nonce), typed by hand in the completing journeys, so a
mis-click cannot erase a disk and a replayed phrase from a previous run
cannot either.

## How real failures surface

Runs 18–26 were real failures of a never-run path, and each was diagnosed
from what the installer itself surfaced. That is the recovery property this
report can honestly claim, and it is a property of the *backend*, proven by
use:

- the backend distinguishes **unavailable** (nothing was attempted — "No
  disk was touched" wraps every refusal up to `ApplyPartitioning`) from
  **failed** (installation began; the frontend keeps the Installing stage on
  screen rather than pretending the machine is clean);
- a failure event carries the engine journal tail, the anaconda log tails,
  SELinux state, and a namespace replay of the target mounts — because
  anaconda's module processes write no logs of their own (their handlers are
  never installed; the copied logs on the target are empty), the backend's
  own capture is the only record there is;
- the driver's serial tee (`/dev/ttyS0`, gated on the drive marker) put every
  one of those failures on the harness's log without guest cooperation.

## What has not run

`interrupted-installation` (power loss mid-write), `bootloader-failure`
(induced), and `recovery-installation` remain **NOT_RUN** in the matrix, each
needing a journey definition of its own. Nothing here claims them. The
closest measured neighbour: anaconda's own teardown discipline means a flow
that *completes* leaves a checkpointed, unmounted target (see the runtime
report) — but an interruption journey must prove the half-written disk is
refused by the verifier, and that run has not happened.
