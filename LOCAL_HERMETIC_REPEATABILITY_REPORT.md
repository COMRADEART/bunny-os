<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Local hermetic repeatability report

Date: 2026-07-30
Branch: `feature/reproducible-build-remediation`
Builder: `local-fedora-wsl`, Fedora Linux 44 under WSL2
Command: `make local-hermetic-repeatability` (qualification mode)

Two clean hermetic builds of one commit, each from a fresh clone into an empty
workspace, with its own container store and no layer cache, against the retained
base, the retained package snapshot and the declared build epoch.

This measures **determinism**, not reproducibility. Both builds share a kernel, a
container store implementation, a clock, a filesystem and an operator; a defect
in any of them reproduces in both and this comparison cannot see it. It is the
gate that must pass before a hosted build is dispatched, and it is only that
gate.

## Result

**The local repeatability gate passes.** Commit `39cf924`, run 6.

```text
outcome        REPRODUCIBLE          (exit 0)

MATCH   17     bootConfiguration, desktopEntries, extendedAttributes,
               fileDigests, filesystemTree, initramfs, kernel,
               normalisedArchive, ociLayers, ownership, packageInventory,
               permissions, rawArchive, sbom, schemas, selinuxLabels,
               systemdUnits
DIFFER   0
NOT_COLLECTED 0

shipped archive, both builds
    429736674037ed40136f1643a67bc826794f5f0d604a546b4cf4c0c54b622d61

rpmdb.sqlite                0 of 12,959 pages differ, LOGICALLY_IDENTICAL
transaction_history.sqlite  LOGICALLY_IDENTICAL
entry mtimes                0 differing
excluded runtime-state paths 0 differing
```

Both builds produced the same 1.85 GB archive, byte for byte.

Run 6 re-measures run 5's result against changed inputs rather than carrying it
forward. The package snapshot was rebuilt to ship the Fedora signing keys, which
regenerated its repository metadata, so run 5 was measured against inputs that no
longer exist. The archive digest moved from `7f032d8e…` to `42973667…`
accordingly — the two runs built different trees against different snapshots, and
each is internally consistent.

Assuming repodata bytes cannot reach the artifact would probably have been
correct and would have been an assumption, which is the failure mode this whole
sequence is a record of.

The comparison still records two things alongside the pass, and both are
deliberate:

```text
every dimension matched, but the two builders are not independent, so this is
same-host repeatability and does not satisfy the production gate

SELinux evidence is incomplete beyond this stage: appliedSelinuxContexts is
owned by installed-system qualification and is not satisfied by an
archive-only build
```

A `REPRODUCIBLE` outcome here is permission to dispatch a hosted build. It is
not reproducibility, and the record says so in its own output rather than
leaving it to a reader.

*The run history below is retained rather than overwritten, because the sequence
is the finding.*

## Run history

Each run measured something the previous one had inferred.

### Run 1 — fifteen files

Attempt 1's two-builder comparison. Fifteen files differed out of 104,247, all
build-environment state. Recorded in `INDEPENDENT_REPRODUCIBILITY_REPORT.md`.

### Run 2 — thirteen fixed, two remaining, and a wrong diagnosis

```text
compared files      104,252 vs 104,252
differing files     2   (was 15)
DIFFER              fileDigests, ociLayers, rawArchive
NOT_COLLECTED       normalisedArchive, packageInventory, sbom, selinuxLabels
```

Four of seventeen dimensions were not collected, because the collector was
invoked without `--sbom` and `--normalisation` and no intended-SELinux manifest
was generated. A comparison missing four dimensions cannot support a
reproducibility claim.

The two remaining files — `usr/share/rpm/rpmdb.sqlite` and
`transaction_history.sqlite` — were attributed to "SQLite page allocation or
B-tree construction order". **That was an inference and it was wrong.**

### Run 3 — the databases match, the layers do not

After measuring the databases rather than assuming
(`docs/SQLITE_DETERMINISM_BASELINE.md`) and fixing the build clock in two places
(`RPM_DATABASE_DETERMINISM_REPORT.md`):

```text
MATCH          13  bootConfiguration, desktopEntries, extendedAttributes,
                   fileDigests, filesystemTree, initramfs, kernel, ownership,
                   packageInventory, permissions, schemas, selinuxLabels,
                   systemdUnits
DIFFER          4  normalisedArchive, ociLayers, rawArchive, sbom

rpmdb.sqlite               0 of 12,959 pages differ, LOGICALLY_IDENTICAL
transaction_history.sqlite LOGICALLY_IDENTICAL
entry mtimes               0 differing
```

Every file in the image identical, and 65 of 80 layers matching while all
fifteen of ours did not. Two causes, neither in the files the comparison looks
at:

* layer 65 is `COPY build /tmp/bunny-os`; its 87 members differed in mtime and
  nothing else. The in-container mtime pass cannot reach a layer whose files a
  later step deleted.
* layer 79 differed at offset 47,478,304, inside
  `/var/cache/ldconfig/aux-cache`, which stores an **inode number** per shared
  object. It also moved glibc's SPDX `packageVerificationCode`, which is what
  `sbom` was reporting.

### Run 4 — one line of output instead of two archives

After clamping layer timestamps at commit and removing the ldconfig cache:

```text
MATCH          14  … and sbom
DIFFER          3  normalisedArchive, ociLayers, rawArchive
excluded runtime-state paths differ on 1: var/log/dnf5.log
```

That last line came from the diagnostic added after run 3. `dnf5.log` records
every transaction with a wall-clock timestamp per line, so it differs between two
builds by construction — and `/var/log` is excluded from the compared set as
runtime state, correctly for a dimension and irrelevantly to a layer tar.

Finding it cost one line of output. Finding its predecessor cost extracting two
1.8 GB archives and diffing layer members by hand.

## What each run changed about the apparatus, not the build

Three defects were in the evidence rather than the artifact, and each would have
made a favourable result mean less than it appeared to.

| Defect | Consequence |
| --- | --- |
| the four input locks were untracked | every "fresh clone" ran with the pins hand-copied in; a hosted builder has nothing but the commit |
| both builds shared a container store and layer cache | the second build could be served the first one's layers wholesale — a comparison that can only pass |
| entry mtimes and excluded paths had nowhere to be reported | an archive difference with every content dimension matching had nothing to point at |

All three are fixed, and the first two are now refused before a build starts.

## Method

```text
build A2   /var/tmp/bunny-hermetic-a2   fresh clone, empty output, own store
build B2   /var/tmp/bunny-hermetic-b2   fresh clone, empty output, own store
base       retained mirror, digest verified against the lock before each build
packages   snapshot fedora-44-beta-20260730, 474 packages, verified before each
epoch      from build/inputs/reproducibility-lock.json
mode       BUNNY_HERMETIC_BUILD=1 BUNNY_ARCHIVE_ONLY=1, --no-cache
comparison qualification mode; a missing dimension is a refusal
```

Qualification mode is enforced at two points, so a diagnostic run cannot become
qualification evidence by being compared later:

* the collector refuses to write an incomplete collection;
* the comparison join refuses a collection produced in diagnostic mode, and
  refuses to run without an intended-SELinux manifest from both sides.

## What a pass here would and would not establish

**Would.** That this commit, built twice on one machine from verified inputs,
produces the same artifact — including the same rpm and libdnf5 databases, the
same package inventory, the same intended SELinux contexts and the same archive.

**Would not.** Anything about a second builder. The
`/var/cache/ldconfig/aux-cache` finding illustrates why: its content came from
inode allocation, a property of the filesystem the build ran on. Two builds on
one host got different inode numbers, which is why it was visible at all; two
builds on different hosts would differ for that reason and for others nobody has
looked for yet.

Reproducibility is the claim that survives changing the machine, and it requires
the retained inputs to be obtainable by a machine that does not already have
them. See `PACKAGE_INPUT_PUBLICATION_REPORT.md`.

## Verdict against the brief's requirement

The brief requires, before dispatching a hosted build, that every archive-stage
dimension be collected and match. The exit code of
`local-hermetic-repeatability.sh` says exactly one thing — whether a hosted build
may be dispatched against this tree — and it exits 2 on anything but
`REPRODUCIBLE`.
