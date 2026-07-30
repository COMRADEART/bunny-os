<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent reproducibility report

Date: 2026-07-30
Candidate commit: `9ea5459bdaf122f8c5999683b2c8961555826954`
Base image: `quay.io/fedora/fedora-bootc:44@sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b`
Profile: `beta`, `BUNNY_ARCHIVE_ONLY=1` on both sides

**Two independently administered builders have now built the same commit and
their artifacts have been compared across all seventeen dimensions.** That had
never happened before: the previous edition of this report compared one builder
against nothing, and sixteen of the seventeen dimensions were `NOT_COLLECTED`.

## Result

```text
outcome: NON_REPRODUCIBLE
  MATCH         11: bootConfiguration, desktopEntries, extendedAttributes,
                    filesystemTree, initramfs, kernel, ownership,
                    packageInventory, permissions, schemas, systemdUnits
  DIFFER         5: fileDigests, normalisedArchive, ociLayers, rawArchive, sbom
  NOT_COLLECTED  1: selinuxLabels

independent builders: no
satisfies production gate: no
```

Machine-readable: `build/out/qualification/reproducibility-comparison.json`.
Source data: `operations/data/build-comparison.json`.

The headline is `NON_REPRODUCIBLE` and it is the right headline. What it does not
convey on its own is the *size* and *character* of the difference, so both are
recorded below.

## The two builders

| | local | hosted |
| --- | --- | --- |
| builderId | `local-fedora-wsl` | `hosted-ci-30566412012` |
| builderType | `local-machine` | `hosted-ci` |
| operating system | fedora-44 | ubuntu-24.04 |
| kernel | 6.18.33.2-microsoft-standard-WSL2 | 6.17.0-1020-azure |
| administrator boundary | `dcb0c0cc3f17c803b94954fa466eba8b` | `4d8365eef238…` |
| workflow run | — | `30566412012.1` |
| CPUs / RAM | 22 | 2 / 7.8 GiB |
| podman | 5.8.4 | 5.8.4 |
| skopeo | 1.22.2 | 1.13.3 |
| syft | 1.50.0 | 1.50.0 |
| grype | 0.116.1 | 0.116.1 |
| python3 | 3.14.3 | 3.13.14 |
| image-builder | present, unused | absent |
| source commit | `9ea5459bdaf1` | `9ea5459bdaf1` |
| base digest | `…c466de53` | `…c466de53` |
| raw archive | `745c7a5ea330e510…` | `6effd086f601a27e…` |
| normalised archive | `298013d265241325…` | `0c99bcd82cd519f4…` |

Both built in archive-only mode and produced no disk image.

## What matched

Eleven dimensions matched exactly, including every dimension that describes the
image's shape and the two that describe the product most directly:

* **`filesystemTree` — 164,356 paths, identical.** The two images contain exactly
  the same set of files.
* **`packageInventory` — 6,076 packages, identical.** Not "equivalent": the same
  set at the same versions. The builds ran hours apart against live Fedora
  repositories and resolved the same packages.
* **`permissions` and `ownership` — identical**, including every setuid bit.
* **`kernel` — `7.1.5-201.fc44.x86_64`**, same `vmlinuz` digest.
* `extendedAttributes` (all nine `security.capability` xattrs), `systemdUnits`,
  `desktopEntries`, `schemas`, `bootConfiguration` and `initramfs`.

## What differed, exactly

Not a summary — the comparison names every differing member.

### `fileDigests`: 15 files, out of 104,247

Both sides carry the same 104,247 files. Fifteen of them differ in content:

```text
etc/brlapi.key
usr/lib/fontconfig/cache/123d59b3…-le64.cache-9
usr/lib/fontconfig/cache/18f520a5…-le64.cache-9
usr/lib/fontconfig/cache/3830d5c3…-le64.cache-9
usr/lib/fontconfig/cache/6cdba951…-le64.cache-9
usr/lib/fontconfig/cache/6ee31038…-le64.cache-9
usr/lib/fontconfig/cache/d63f98f1…-le64.cache-9
usr/lib/fontconfig/cache/feeafda3…-le64.cache-9
usr/lib/sysimage/libdnf5/system.toml
usr/lib/sysimage/libdnf5/transaction_history.sqlite
usr/lib/sysimage/libdnf5/transaction_history.sqlite-shm
usr/lib/sysimage/libdnf5/transaction_history.sqlite-wal
usr/share/rpm/rpmdb.sqlite
var/lib/dnf/repos/fedora-cff72538bc9825a4/countme
var/lib/dnf/repos/updates-3cc07c89a20302f2/countme
```

**Every one is build-environment state. None is product code.** By kind:

| Kind | Files | Why it differs |
| --- | --- | --- |
| Randomly generated at install | `etc/brlapi.key` | brltty mints a fresh key per installation |
| Timestamped databases | `rpmdb.sqlite`, `transaction_history.sqlite` and its `-wal`/`-shm`, `system.toml` | rpm and dnf record install times |
| Derived caches | 7 fontconfig caches | embed paths and mtimes of the fonts they index |
| Telemetry counters | 2 dnf `countme` files | per-installation counters |

### `sbom`: 7 entries, out of 6,076

The differing entries belong to three packages: **brlapi, glibc, libdnf5** — the
packages that own the files above. `packageInventory` matches because the
*package set* is identical; `sbom` differs because syft records the digests of
the files those packages own, and fifteen of those files differ.

### `ociLayers`: 28 layer digests, out of 79

A layer digest changes when any file in it changes. Twenty-eight layers contain
at least one of the fifteen files.

### `rawArchive` and `normalisedArchive`

Both differ. Normalisation removes packing metadata — entry order, mtimes,
ownership names, gzip timestamps — and the difference survives it. That is
exactly what the two-digest design is for: **this is not a packing artefact.**
Fifteen files really do differ.

## What an earlier run showed, and why it is recorded

The first successful hosted build, run
[30564513627](https://github.com/COMRADEART/bunny-os/actions/runs/30564513627),
gave a **worse** result on the same commit and the same base: 8 matching
dimensions instead of 11. `filesystemTree`, `permissions` and `ownership` all
differed, on a single path — `etc/hostname`, present in the hosted image and
absent locally.

That runner had **podman 4.9.3**; the runner an hour later had **podman 5.8.4**,
matching the local builder. GitHub had rotated the `ubuntu-24.04` image between
the two runs.

Ubuntu's podman 4.9.3 writes `/etc/hostname` into the build container and 5.8.4
does not. So one of the sixteen files that differed was contributed by the
container runtime rather than by anything in this repository — and it vanished
when the runtimes happened to match.

This is recorded rather than discarded because it is the clearest available
demonstration of why `verify-builder-independence` refuses a pair whose
toolchains differ. Without pinning, a reproducibility result varies with whatever
the hosted runner image happened to ship that day.

## `selinuxLabels` was not collected, and is not a match

Measured: 164,962 entries, nine carrying `security.capability`, **zero carrying
`security.selinux`**. A bootc container image does not store SELinux contexts in
its layers; `bootc install` applies them on the target from the policy shipped in
the image.

The dimension is therefore `NOT_COLLECTED` from both sides rather than an empty
set on both sides. Two empty sets compare equal, and reporting a match here would
claim a comparison that did not happen.

## Why the builders are not certified independent

```text
BLOCKED  local-fedora-wsl + hosted-ci-30566412012 — a local physical builder paired with hosted CI
    toolchain versions differ: toolchain.image-builder, toolchain.python3,
    toolchain.skopeo; a content difference could not be attributed to the
    environment
```

Everything else passed. The pairing is one of the five accepted ones, the two
administrator boundaries are distinct, and the shared inputs match:

```json
"sourceCommitEquality": true,
"baseDigestEquality": true,
"configurationEquality": true,
"toolchainEquality": false,
"environmentIndependence": true
```

`podman`, `syft`, `grype` and `tar` all match. The three that do not:

| Tool | local | hosted | In the path that writes the archive? |
| --- | --- | --- | --- |
| `image-builder` | present, unused | absent | No — archive-only mode never invokes it |
| `python3` | 3.14.3 | 3.13.14 | No — the host interpreter runs the wrapper scripts; `install-root.py` runs under the base image's own `/usr/bin/python3` |
| `skopeo` | 1.22.2 | 1.13.3 | No — `podman save` writes the archive |

**That analysis is not a reason to relax the check, and the check was not
relaxed.** It is conservative on purpose: "this tool probably does not matter" is
the reasoning that lets a real difference through. Pinning `skopeo` and the host
`python3`, and deciding explicitly how `image-builder`'s absence in archive-only
mode should be recorded, is the work that would let this pass honestly.

The earlier run is the argument for the conservatism: `podman` was in that list
one run ago, and it demonstrably did affect the artifact.

## What this establishes, and what it does not
## What this establishes, and what it does not

**Established.** Two builders under genuinely different administration — a local
Fedora machine and a GitHub-hosted Ubuntu runner — built the same commit against
the same base digest and produced images whose package set, kernel, units,
desktop entries, schemas, boot configuration, capabilities and initramfs are
identical. That is a real result and it had never been measured.

**Not established.** Byte-identical artifacts, and therefore not
`independent-builder` reproducibility. The candidate prerequisite stays
`BLOCKED`.

**Deliberately not claimed.** That the fifteen differing files are harmless. They
are all build-environment state by inspection, and inspection is not proof. The
comparison reports `NON_REPRODUCIBLE`, and this report does not argue that down
to something softer.

## What would move this to REPRODUCIBLE

In dependency order, each with a named cause:

1. **Pin `podman` across both builders.** Fedora 5.8.4 against Ubuntu 4.9.3 is
   the difference that produced `etc/hostname` and that blocks the independence
   verdict outright. Either install a pinned podman on the hosted runner, or run
   the hosted build inside a Fedora container.
2. **Stop shipping build-environment state.** `etc/hostname`, `etc/brlapi.key`
   and `var/lib/dnf/…/countme` have no business in the image and can be removed
   during the build. Three of the fifteen files, and the only tree, permission
   and ownership difference.
3. **Make the package databases reproducible.** `rpmdb.sqlite` and the libdnf5
   transaction history record install times. `SOURCE_DATE_EPOCH` is already
   passed to the build and rpm honours it only partially, so this needs
   investigation rather than a one-line fix. Five of the fifteen.
4. **Rebuild or drop the fontconfig caches.** Seven files, derived from fonts
   that already match. Regenerating them at first boot, or excluding them from
   the image, removes them.
5. **Provision `build/repositories/fedora-44-snapshot.repo`.** It does not exist
   — only an `.example` — so neither build could use `BUNNY_RELEASE_BUILD=1`.
   The package sets happened to match here; that is luck, not design.
6. **Mirror the base image.** The digest pinned since Phase 6 was garbage
   collected from quay.io before the hosted builder could pull it.

Items 2 to 4 account for all fifteen differing files. Item 1 is the one that also
unblocks the independence verdict.

## Method

Both sides were measured by one collector,
`scripts/reproducibility/collect_comparison_dimensions.py`, reading each
builder's own OCI archive with `tarfile` — no root, no podman, no mount. Layers
are applied in manifest order with OCI whiteout semantics, so the result is the
image's filesystem rather than the union of its layers.

A difference in this report is therefore a difference in the images, not a
difference in how they were measured.

Paths under `/var/log`, `/var/cache`, `/var/tmp`, `/tmp` and `/run`, and
`/etc/machine-id`, are excluded from the compared set as runtime state rather
than build output — 606 paths, listed in the collection record so the exclusion
is visible rather than silent. `etc/hostname` is **not** excluded, which is why
it appears above.

One exclusion was added during this comparison and is worth naming: the SPDX
document root. syft records the scanned archive itself as a package whose version
is the archive's own digest, so leaving it in made `packageInventory`
self-referential — it could match only when the archives were byte-identical,
which `rawArchive` already measures. Two builds with identical package sets would
have reported a package difference. It is excluded by `SPDXID` prefix; every real
package stays.

The committed comparison stores each dimension either verbatim or, when it
exceeds 256 KiB, as a SHA-256 over the whole collected value plus every differing
member name. Equality is preserved exactly: two dimensions compare equal there if
and only if they were equal in full. The full collections are 71 MB per builder
and are not committed.

## Evidence

| Artifact | Location |
| --- | --- |
| Comparison verdict | `build/out/qualification/reproducibility-comparison.json` |
| Comparison source | `operations/data/build-comparison.json` |
| Builder records and the declared pair | `operations/data/builders.json` |
| Import record | `build/out/qualification/hosted-builder-import.json` |
| Hosted run | [30564513627](https://github.com/COMRADEART/bunny-os/actions/runs/30564513627) |
| Hosted build details | `HOSTED_INDEPENDENT_BUILD_REPORT.md` |
| Import checks | `HOSTED_ARTIFACT_IMPORT_REPORT.md` |

## 2026-07-30 addendum — three passes, and what each one actually settled

This report described attempt 1: fifteen files differing out of 104,247 between a
local Fedora builder and a hosted runner. Three further passes followed, and the
useful record is what each one turned out to have got wrong.

| Pass | Claimed | Measured afterwards |
| --- | --- | --- |
| 1 | fifteen files differ, all build-environment state | correct |
| 2 | thirteen fixed; the two remaining differ by "sqlite page allocation or B-tree construction order" | **wrong.** Identical page counts, empty freelists, identical b-tree depths and cell offsets. Fifty rows of *content* differed. |
| 3 | — | the build clock was offset rather than frozen, and a second package transaction had no clock at all |
| 4 | — | every file matched and the layers still differed: wall-clock mtimes in a COPY layer, and inode numbers in an ldconfig cache |

Pass 2's inference is the one worth keeping. Two files of identical length
differing in the middle is what page-layout variance looks like from a distance,
and the fix it implied — a canonical re-encoding — would have made the bytes match
while erasing a real difference in recorded install times. The brief's
instruction not to assume page allocation until the structures were measured is
what changed the answer.

### Three defects in the evidence apparatus, not the build

Each would have made a favourable result mean less than it appeared to.

* **The input locks were untracked.** Every "fresh clone" comparison had run with
  the four pins hand-copied into each clone. A hosted builder has nothing but the
  commit.
* **Both builds shared a layer cache.** podman keys its build cache on the
  instruction and the context digest, so two fresh clones of one commit hit it.
  The second build could have been served the first one's layers wholesale — a
  comparison that can only pass.
* **Two classes of difference had nowhere to be reported.** Layer tars carry entry
  mtimes and contain the runtime-state paths the dimensions exclude, so a
  difference in either changed `ociLayers` and `rawArchive` while every content
  dimension matched. Both are now collected as named diagnostics.

### What is still not established

Independent-builder reproducibility. The retained base, the builder image and the
package snapshot exist on one machine, so no second builder can obtain them. That
is one token scope and it is named in `PACKAGE_INPUT_PUBLICATION_REPORT.md`.

Until then the strongest available claim is same-host determinism, which is a
different claim, and this project has now spent four passes learning how
different.
