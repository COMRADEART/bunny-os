<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Storage and retention policy

Qualification produces multi-gigabyte disk images and long capture files. None of
it belongs in git, and one earlier attempt put a git worktree inside `build/`
where the repository validator walked into it and validated another branch as
`main`. That is the mistake this policy exists to prevent.

## Location

Everything lives outside the repository:

    /var/lib/bunny-qualification/
      environments/     host environment and readiness results, per FQH id
      artifacts/        Bunny artifacts under test, by digest
      vm-images/        base guest images
      overlays/         per-run writable overlays, disposable
      evidence/         collected observations, per run id
      logs/             serial and journal captures
      screenshots/      compositor frames
      captures/         PipeWire and speech-dispatcher traces
      recovery-media/   development-signed recovery ISOs
      temporary/        scratch, cleared by every reset

Override with `BUNNY_EVIDENCE_ROOT`. A dedicated mounted volume is fine.

## Rules

- **No git worktree inside the repository**, and never under `build/`.
- **No VM disk in the repository**, at any size.
- Per-run writable disks stay outside git unless a retention policy explicitly
  requires otherwise.
- Committed evidence records carry the `sha256` of externally retained artifacts,
  so the record proves which file it describes without containing it.

## Retention manifest

Every retained artifact gets a manifest row:

    path              size            sha256
    createdAt         sourceRun       retentionClass
    containsSecrets   redactionStatus

`containsSecrets` is a decision, not a guess. Anything true there is not
committed and not retained beyond the run.

Built by `scripts/retention-manifest.py`, which digests every retained file and
scans it for secret patterns. It exits 2 rather than describing a secret-bearing
artefact as retained, and marks it `REVIEW_REQUIRED` rather than rewriting it —
a passphrase is removed by a person who understands how it got there.

An unreadable file is treated as unclean. Not scannable is not clean.

Retention classes:

| Class | Meaning |
|---|---|
| `authority` | referenced by an evidence record; retained indefinitely |
| `diagnostic` | supports an investigation; retained while the finding is open |
| `disposable` | reproducible from an authority artifact; deleted at reset |

## Never retained

Plaintext passphrases, in any file, of any class. `reset-test-state.sh` greps
retained evidence for secret patterns after every reset; a hit is a harness
defect, not a nuisance.

## Space

The readiness gate requires 400 GiB free where evidence will be written. Guest
matrices with repeated cold boots and retained serial logs consume more than
expected, and a matrix that dies from a full disk mid-run produces a partial
record that must be discarded rather than patched.
