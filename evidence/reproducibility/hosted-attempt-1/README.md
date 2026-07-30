<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hosted attempt 1 — failed, retained

Date: 2026-07-30
Target: `27223d357d8dd1adace6ff67e2ebd03bc620f1cf` (superseded Commit C)
Runs: H1 `30590381937`, H2 `30590413565`

**Both runs failed. Neither produced an artifact, and neither may be used in a
comparison.** They are kept because a discarded failure is a lesson nobody can
check, and because what they proved before failing is the more useful half.

## What failed

```text
sudo: command: command not found
```

`build/scripts/build-image.sh` routed podman through a wrapper that used
`sudo command podman` to reach past itself to the binary. `command` is a shell
builtin, so `sudo` needs an executable of that name: Fedora ships
`/usr/sbin/command` and Ubuntu does not.

The build was correct on the machine it was written on and died at the first
podman call on a machine that was not. No amount of reading the script would
have surfaced it. This is the first thing an independent builder found, and it
is precisely the class of defect an independent builder exists to find.

Fixed in `f5985f6`. The indirection was unnecessary as well as unportable —
`sudo` is the command word and `podman` is one of its arguments, so the function
never had a recursion problem to solve.

## What these runs did establish

Everything up to the build step passed on both runners:

```text
success  Guard — target and no signing access
success  Fetch the retained inputs by digest and put them where the locks say
success  Verify every input lock against what was fetched

  base-image-lock-present         ok
  builder-image-lock-present      ok
  package-snapshot-lock-present   ok   fedora-44-beta-20260730, 474 packages
  reproducibility-lock-present    ok   epoch 1785442979
  base-verified                   ok
  builder-verified                ok
  builder-tools-classified        ok
  snapshot-verified               ok
  snapshot-signatures-verified    ok   every RPM retains a verified signature
  epoch-lock-names-retained-base  ok
  epoch-lock-names-builder-image  ok
  epoch-lock-names-snapshot       ok
  architecture-retained           ok
```

Two machines that had never seen the retention store rebuilt it from the
published digests, and all thirteen lock subchecks passed on both. The
publication chain — publish, cold pull, hydrate, verify — works end to end on a
host that holds none of it.

Also established: the guard rejected nothing, meaning both runners confirmed
`27223d3` was the qualification target its own file described, and that no
production signing secret was reachable.

## Why the target was superseded

The fix touches `build/scripts/build-image.sh`, and `build/` is copied into the
image context, so it changes the artifact. A target whose tree no longer builds
the artifact it was created for is not a target. Commit C was re-created after
the local gate was re-measured on the fixed tree.

## Contents

```text
H1-run.json                 run metadata, status and per-job conclusions
H2-run.json                 the same for H2
H1-artifacts/               what the run uploaded before failing:
                              ci/runner-environment.txt
                              qualification/hydrated-inputs.json
H2-artifacts/               H2 uploaded nothing; it failed at the same step
```

`hydrated-inputs.json` is the interesting file: it records the three inputs
fetched by digest and where each was placed, which is the evidence that the
hosted half of the supply chain works.
