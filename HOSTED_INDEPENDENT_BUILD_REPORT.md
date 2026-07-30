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

## Dispatches 2 to 6 — five more real defects

It took five more dispatches to reach a hosted build that completed. Each failure
was a real defect; none was visible by reading the workflow. They are recorded as
F10–F14 in `docs/CI_PORTABILITY_BASELINE.md`:

| Run | Failed on |
| --- | --- |
| 30558894088 | `crun` refused the OCI spec version Ubuntu's podman writes |
| 30561595976 | the storage driver cannot be changed under an initialised store |
| 30563069708 | the SBOM step was killed — first diagnosed as disk, wrongly |
| 30564352327 | a `[storage]` section replaces the defaults, so `runroot` must be set |
| 30564513627 | **build succeeded**; the verify job used a flat artifact layout that never existed |

Two of those are worth carrying forward.

**The disk diagnosis was wrong, and measuring said so.** The SBOM step died with
no message and `cancelled`, on a runner with ~14 GB free. Disk was the obvious
answer, so ~25 GB of unused toolchains were removed and the SBOM cut to one output
format. The next run entered the step with **28 GB free and was killed anyway**.
The constraint is memory: the runner has 7.8 GiB of RAM, not the 16 assumed, and
syft catalogues a 1.85 GB archive holding 164,962 entries. 16 GB of swap and
`SYFT_PARALLELISM=1` fixed it. The disk reduction was kept — it was a real
constraint, just not this one.

Measuring also showed `/mnt` on this runner is the same filesystem as `/`, so
relocating the container store there had done nothing. That change was reverted
rather than left in place looking as though it had helped.

**A step that reports nothing invites a plausible answer.** `cancelled` with an
empty log is indistinguishable from a deliberate cancellation. Free disk *and*
free memory are now printed around every heavy step.

## Dispatch 7 — the first build that completed

Run [30564513627](https://github.com/COMRADEART/bunny-os/actions/runs/30564513627).

```text
success        Guard — no production signing access
success        Hosted independent build
failure        Verify the uploaded evidence in a separate environment
skipped        Assert no gate was moved by this workflow
```

The build job succeeded and produced a complete bundle. The verify job failed on
a path bug of its own: `upload-artifact` preserves the structure below the least
common ancestor of its path list, so the bundle contains `ci/` and `beta/`
subdirectories, and every path the verify job used was flat.

```text
BLOCKED: cannot read downloaded/evidence/ci-provenance.json:
[Errno 2] No such file or directory
```

It failed closed, which is right, but on a path bug rather than on the evidence.
Fixed, and the fix listed what it downloaded before using it so a future layout
change reports what it found instead of only what it wanted.

### What the run measured

```text
Reclaim disk before building                 69s   reclaimed 19 GiB, 34 GiB free
Configure the container runtime and storage   9s   runc 1.3.4, overlay
Record the runner environment                 2s
Build the normalised OCI archive            384s
Generate the SBOM and package inventory     717s
Emit raw and normalised archive digests      22s
Collect the builder record                    1s
Collect the artifact manifest and provenance  2s
Upload comparison artifacts                   3s
Upload the OCI archive                       18s
```

```text
runnerImage       ubuntu24
runnerArch        X64
runnerName        GitHub Actions 1000000607
runnerEnvironment github-hosted
kernel            6.17.0-1020-azure
os                ubuntu-24.04
containerRuntime  podman version 4.9.3
ociRuntime        runc 1.3.4-0ubuntu1~24.04.1
storageDriver     overlay
imageBuilder      absent (BUNNY_ARCHIVE_ONLY=1)
workflowRunId     30564513627.1
cpus              2
```

Every property Workstream 11 requires:

| Required | Result |
| --- | --- |
| Exact commit checked out | `9ea5459bdaf122f8c5999683b2c8961555826954`, asserted against the input |
| Exact base digest pulled | `…@sha256:c466de53…` |
| Archive-only mode activated | `BUNNY_ARCHIVE_ONLY=1`; `image-builder` absent |
| OCI archive built | 1,852,026,880 bytes |
| No disk image built | `diskImages: []`, `archiveOnly: true` in the build provenance |
| No stable candidate declared | no candidate manifest; both gates refuse an archive-only artifact |
| SBOM generated | 6,077 SPDX packages (6,076 after the document root) |
| Package inventory generated | 6,076 entries |
| Builder record generated | schema 2, `builderType: hosted-ci`, `workflowRunId: 30564513627.1` |
| Raw digest generated | `59b9a56a34ad932a4c482438ecc0e3180ca5e9898fedd4c63b28165ab4e2c7df` |
| Normalised digest generated | `f3335931e3d2b00466dc4839e4f15999f05fbe4de0c0a22b045adc69faf92e4e` |
| Provenance generated | CI provenance and build provenance, both uploaded |
| Build logs retained | `build.log`, `oci-build.log`, `image-builder.log`, 90-day retention |
| No production key accessible | guard job asserted all four secrets resolve empty, on every dispatch |

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


## Dispatch 8 — the run that produced the imported evidence

Run [30566412012](https://github.com/COMRADEART/bunny-os/actions/runs/30566412012),
with the verify job's artifact paths corrected.

```text
success  Guard — no production signing access
success  Hosted independent build
success  Verify the uploaded evidence in a separate environment
success  Assert no gate was moved by this workflow
```

**Every job passed**, including the separate-environment verification:

```text
PASS  separate-verification-environment: verified in
      'verify-30566412012-GitHub Actions 1000000638', built in '30566412012.1'
builder hosted-ci-30566412012 on hosted-ci, boundary 4d8365eef238
one builder record is not a pair; independence is decided by verify-builder-independence
```

and the closure job confirmed the workflow moved no gate: the stable gate still
reports NO-GO and the candidate gate still blocks, both from an archive-only
build.

This is the run whose evidence is imported. Dispatch 7's bundle was valid and
complete — its build job succeeded, and its verify job failed on a path bug in
the workflow rather than on the evidence — but importing from a run where every
check passed leaves nothing to explain away.

### The two runs disagreed, and that is the finding

Same commit, same base digest, an hour apart:

| | run 30564513627 | run 30566412012 |
| --- | --- | --- |
| podman | 4.9.3 | 5.8.4 |
| matching dimensions | 8 of 17 | 11 of 17 |
| `filesystemTree` | DIFFER (`etc/hostname`) | MATCH |
| `permissions`, `ownership` | DIFFER (`etc/hostname`) | MATCH |
| differing files | 16 | 15 |

GitHub rotated the `ubuntu-24.04` runner image between them. Ubuntu's podman
4.9.3 writes `/etc/hostname` into the build container; 5.8.4 does not.

**A reproducibility result that changes because the runner image was updated is
not yet a reproducibility result.** This is the concrete case for pinning the
build toolchain rather than accepting whatever the hosted image ships, and it is
why `verify-builder-independence` refuses a pair whose toolchains differ even
when the difference looks harmless.
