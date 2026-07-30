<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hosted independent build report

The first execution of `.github/workflows/independent-builder.yml`. It had been
committed and never run; `operations/data/builders.json` carried
`builderRecords: []` and `verify-builder-independence` blocked on that.

| | |
| --- | --- |
| Qualification target commit | `9ea5459bdaf122f8c5999683b2c8961555826954` |
| Profile | `beta` |
| Workflow | `.github/workflows/independent-builder.yml` |
| Dispatched against | `feature/qualification-evidence-closure` (workflow definition) |
| Built commit | `9ea5459bdaf122f8c5999683b2c8961555826954` (exact SHA input) |
| Mode | `BUNNY_ARCHIVE_ONLY=1` |

The `--ref` and the `commit` input are different things and are deliberately
different concepts. `--ref` selects which *workflow definition* runs; `commit`
selects which *source* is built. The guard job rejects a `commit` that is not a
full 40-character SHA, so a branch name cannot pin a build.

## Preflight

Verified before dispatch:

| Check | Result |
| --- | --- |
| Exact 40-character commit | `9ea5459bdaf122f8c5999683b2c8961555826954`, 40 characters, matches `^[0-9a-f]{40}$` |
| Commit exists and is reachable | present on `origin/feature/qualification-evidence-closure` |
| Digest-pinned base | matches `@sha256:[0-9a-f]{64}$` |
| No production signing secret reachable | guard job asserts all four names resolve empty |
| Archive-only mode enabled | `BUNNY_ARCHIVE_ONLY: "1"` in the workflow environment |
| Build output begins empty | asserted by the build job before building |
| Tool versions pinned | syft 1.50.0, grype 0.116.1, Python 3.13 |
| Artifact retention | 90 days for evidence, 30 days for the archive |

## Dispatch 1 — refused by the registry, not by the workflow

Run [30558573550](https://github.com/COMRADEART/bunny-os/actions/runs/30558573550),
dispatched with the base digest this repository had pinned since Phase 6.

```text
Guard — no production signing access    success
Hosted independent build                failure
Verify the uploaded evidence            skipped
Assert no gate was moved                skipped
```

```text
STEP 1/23: FROM quay.io/fedora/fedora-bootc:44@sha256:fb71f099…
Trying to pull quay.io/fedora/fedora-bootc@sha256:fb71f099…
Error: creating build container: unable to copy from source
docker://quay.io/fedora/fedora-bootc@sha256:fb71f099…: initializing source:
reading manifest sha256:fb71f099… in quay.io/fedora/fedora-bootc: manifest unknown
```

**The pinned base image no longer exists upstream.** Confirmed independently with
`skopeo` against the registry, not inferred from the build failure:

```text
$ skopeo inspect docker://quay.io/fedora/fedora-bootc@sha256:fb71f099…
FATA[0000] reading manifest sha256:fb71f099… : manifest unknown

$ skopeo inspect docker://quay.io/fedora/fedora-bootc:44
"Digest": "sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b"
"Created": "2026-07-30T11:05:54Z"
"org.opencontainers.image.version": "44.20260730.0"
```

`fedora-bootc:44` is rebuilt daily and old digests are garbage collected.

This is the more interesting half of the finding: **the local Fedora builder
still built against `fb71f099` on the same day**, because it had the layers in
its container store. A build that appears to reproduce may only be reachable from
one machine's cache. Pinning a digest records *which* base was used; it does not
make that base obtainable later, and the difference is invisible from the machine
that has it cached.

The guard job did its job — a mutable tag would have been refused — and the
failure is not a defect in this repository. It is a property of depending on a
daily-rebuilt upstream tag, and it is recorded in `KNOWN_LIMITATIONS.md`.

### What was not done about it

The base was **not** unpinned, and the digest check was **not** relaxed. The
currently published digest was supplied as the `base_image` input for dispatch 2,
and the local builder was rebuilt against the same digest, so both halves of the
comparison use one base. The base digest is a workflow *input*, so re-pinning
required no change to any committed file and the qualification target commit did
not move.

## Dispatch 2

Run [30558894088](https://github.com/COMRADEART/bunny-os/actions/runs/30558894088),
base `quay.io/fedora/fedora-bootc:44@sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b`.

<!-- RESULT -->

## The local half

Built on the Fedora Linux 44 WSL2 builder from a clean clone checked out at the
same commit, against the same base digest, in the same archive-only mode.

```text
builderId              local-fedora-wsl
builderType            local-machine
sourceCommit           9ea5459bdaf122f8c5999683b2c8961555826954
baseImageDigest        …@sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b
operatingSystem        fedora-44
kernelVersion          6.18.33.2-microsoft-standard-WSL2
administratorBoundary  dcb0c0cc3f17c803b94954fa466eba8b
workflowRunId          null
buildStarted           2026-07-30T15:53:55Z
buildCompleted         2026-07-30T16:00:15Z

raw archive digest        745c7a5ea330e510be8a75da8d4fd6405a78385fb114e872cff74826aab76005
normalised archive digest 298013d265241325b424e94c55ed076f59dbe24340b8324307b4d8c73a6d6b4b
archive size              1,852,282,880 bytes
SBOM packages             6,077
```

Archive-only mode was verified on that builder before either dispatch:

```text
PASS  no QCOW2 produced
PASS  no raw image produced
PASS  no ISO produced
PASS  no candidate manifest
PASS  OCI archive produced
PASS  archive is normalised
PASS  image-builder was skipped
PASS  provenance archiveOnly=true
PASS  provenance lists no disks
PASS  SBOM generated
PASS  package inventory generated
PASS  normalisation digests recorded

candidate gate on archive-only: correctly refused (exit 2)
stable gate on archive-only:    correctly refused (exit 2)
```

The candidate gate's refusal names what the build did not do rather than
reporting a bare rejection:

```text
BLOCKED: qualification-candidate also refuses the built artifacts present:
  build/out/beta/provenance.json: this is an archive-only build
  (BUNNY_ARCHIVE_ONLY=1). It produced an OCI archive and no disk image, so
  nothing was installed, nothing booted, no recovery media was written and no
  hardware was exercised. It cannot qualify: installation, recovery-media,
  hardware, encryption, update, rollback, secure-boot, stable-artifact. An
  archive-only build is evidence for reproducibility comparison only.
```

## What a hosted archive-only build does not establish

It produces no disk image. Therefore it qualifies **nothing** about
installation, recovery media, hardware, encryption, update, rollback or secure
boot, and it is never a release candidate. Both protected gates refuse such an
artifact by name, and `tests/portability/test_archive_only.py` holds that.

Its one purpose is to be a second builder under a different administrator, so
that a *pair* exists for the reproducibility comparison. Independence is decided
over the pair by `release/builders.py`, not by either record alone.
