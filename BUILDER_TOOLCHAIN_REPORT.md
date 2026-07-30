<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Builder toolchain report

Date: 2026-07-30
Builder image: `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e`
Built from: `build/builder/Containerfile`, commit `9c525bf1ca34`
Base: `registry.fedoraproject.org/fedora@sha256:754c6d7d…`, digest-pinned

## Result

```text
tools pinned                20
output-affecting            16
evidence-generation-only     4
declared absent              1  (image-builder, with a reason)
unclassified                 0  (an unclassified tool blocks the lock)
```

## What changed in this pass

Two tools were added, both because they were reaching the artifact from outside
the pin.

### libfaketime — was taken from the build host

`build/scripts/build-image.sh` located it with:

```bash
faketime_library="$(find /usr/lib64 /usr/lib -name 'libfaketime.so.1' | head -1)"
```

So whichever libfaketime the build machine happened to carry was `LD_PRELOAD`ed
into the package transaction. That is not a theoretical hazard for this
particular library: its semantics decide whether the build clock freezes or
merely starts at the epoch and then runs, and the second of those put fifty
package headers on different seconds between two builds
(`RPM_DATABASE_DETERMINISM_REPORT.md`).

It is now installed in the builder image, copied to a stable path, and its
SHA-256 recorded in the lock. The build extracts it from the pinned image by
digest and verifies the checksum before preloading it.

```text
libfaketime   0.9.12-12.fc44
              /usr/local/lib/bunny-faketime/libfaketime.so.1
              sha256:7877f29c417228f151dbcbe182741d0ca516635dae3afb03eac8f3ee6a42d745
```

`BUNNY_FAKETIME_LIBRARY` still says *where* the library is, for an environment
that has already extracted it. It does not say *what* it is — the checksum is
verified either way, so an override cannot smuggle a different library past the
pin.

### sqlite — was installed and unrecorded

`sqlite` was already in the builder image and carried no classification and no
version in the lock. rpm and libdnf5 both keep their databases in SQLite and
those databases are files in the artifact, so the library's version, page size,
threading mode and compiled-in extensions all determine the bytes a transaction
leaves behind.

A version string is not enough. The lock now carries a section:

```text
libraryVersion            3.51.2
cliVersion                3.51.2
sourceId                  2026-01-09 17:27:48 b270f8339eb13b504d0b2ba154ebca966b7dde08e40c3ed7d559749818cbalt1
defaultPageSize           4096
threadSafe                1
compileOptions            53
compileOptionsSha256      b0820ccb9a3b128e507a367ea967872fb3b147800d405359dc85c7db9c883047
extensionsCompiledIn      13
```

Two SQLite builds at one upstream version can differ in all of these. The
database finaliser refuses to run against a SQLite whose version does not match
the lock, and the product build passes the locked version into the container so
a base or snapshot change that moved SQLite fails the build with both versions
named.

## Classification

`output-affecting` means a difference between two builders can change the
artifact. `evidence-generation-only` means it can change what is *reported* about
the artifact and not the artifact itself, and requires a stated reason and a
test. `unknown` is a valid state in the schema and the generator refuses to mint
one: an unclassified tool is one whose effect nobody has established, and an
unestablished effect cannot be assumed to be none.

```text
output-affecting (16)
    buildah  conmon  createrepo_c  crun  dnf5  gzip  libdnf5  libfaketime
    podman  python3  rpm  runc  skopeo  sqlite3  tar  zstd

evidence-generation-only (4)
    grype  libselinux-utils  policycoreutils  syft

declared absent (1)
    image-builder — Fedora-only, and the archive-only qualification path never
    invokes it. Its absence also means this builder can never produce a disk
    image, and so can never satisfy installation, recovery, hardware,
    encryption, update, rollback or secure-boot qualification.
```

## Version extraction is checked, not trusted

An earlier lock recorded `crun` as version **`version`** and `createrepo_c` as
**`)`**, because two `--version` outputs put the number in a different field than
the extraction assumed. Both strings would have compared *equal* between two
builders and satisfied the toolchain check while establishing nothing about
either tool.

`write-builder-lock.py` now refuses a version that is not version-shaped, and the
refusal names the tool and the value. A lock is worth exactly as much as the
weakest field nobody checked.

## What the pin is for

Both builders must present this builder digest. Their hosts may differ in every
other respect — different kernel, different provider, different administrator —
and that difference is the independence the comparison needs. What stops
differing is the set of programs that touch the artifact.

The reason this matters was measured rather than assumed: `ubuntu-24.04` is a
label, and two runs an hour apart had podman 4.9.3 and 5.8.4. The 4.9.3 runner
wrote `/etc/hostname` into the image and the 5.8.4 one did not, so a
reproducibility result changed because GitHub rotated a runner image.

## Reproducing

```text
make build-builder-image     # rebuilds and re-locks; the digest is the pin
make verify-builder-image    # refuses a mutable tag or a drifted tool
```

The builder image is not yet published. Until it is, both builders cannot present
the same digest because only one of them can obtain it — see
`PACKAGE_INPUT_PUBLICATION_REPORT.md`.
