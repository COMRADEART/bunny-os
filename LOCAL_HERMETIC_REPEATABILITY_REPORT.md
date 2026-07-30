<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Local hermetic repeatability report

Date: 2026-07-30
Branch: `feature/reproducible-build-remediation`
Builder: `local-fedora-wsl`, Fedora Linux 44 under WSL2

Two clean hermetic builds, each from a fresh clone into an empty workspace,
against the retained base, the retained package snapshot and the declared build
epoch.

## Result

**Thirteen of the fifteen differing files are fixed. Two remain, and they are
not the thing that was remediated.**

```text
compared files      104,252 vs 104,252
differing files     2   (was 15)

MATCH          bootConfiguration, desktopEntries, extendedAttributes,
               filesystemTree, initramfs, kernel, ownership, permissions,
               schemas, systemdUnits
DIFFER         fileDigests, ociLayers, rawArchive
NOT_COLLECTED  normalisedArchive, packageInventory, sbom, selinuxLabels
```

This is **same-host repeatability**, not reproducibility. Two builds on one
machine share a kernel, a container store, a clock and an operator; a defect in
any of them reproduces in both and this comparison cannot see it. It is the gate
the remediation brief requires before dispatching anything hosted, and it is
what that gate says.

## The fifteen, one by one

| File | Remediation | Result |
| --- | --- | --- |
| `etc/brlapi.key` | removed from the image; generated per device by `bunny-brlapi-key.service` | **fixed** |
| 7 × `usr/lib/fontconfig/cache/*.cache-9` | font-directory mtimes pinned to the build epoch, caches regenerated | **fixed** |
| `usr/lib/sysimage/libdnf5/system.toml` | left untouched deliberately — it carries an rpmdb-derived cookie | **fixed** |
| `transaction_history.sqlite-wal` | checkpointed into the database | **fixed** |
| `transaction_history.sqlite-shm` | removed after checkpointing | **fixed** |
| 2 × `var/lib/dnf/repos/*/countme` | deleted, and `countme=0` written into every repository definition | **fixed** |
| `usr/share/rpm/rpmdb.sqlite` | frozen transaction clock (ADR-028) | **still differs** |
| `usr/lib/sysimage/libdnf5/transaction_history.sqlite` | frozen transaction clock, then checkpoint and vacuum | **still differs** |

## What the remaining two actually establish

The interesting result is not that two files differ. It is **which** file stopped
differing.

`usr/lib/sysimage/libdnf5/system.toml` now matches. Its only content is
`rpmdb_cookie`, a digest derived from the rpm database:

```text
version = "1.0"
system = {rpmdb_cookie = "6948c2a8ea7c2be68f10aef811dcad51607e5275b8e501651c1ca430b7da3a5d"}
```

A digest over the rpm database matching, while the database *file* does not, says
the databases hold the same content and are encoded differently. The frozen
transaction clock did its job: `INSTALLTIME` is no longer the variable. What
remains is sqlite's own file layout — page allocation, freelist state, B-tree
fill order — which depends on the order and timing of writes rather than on what
was written.

That is a different defect with a different fix, and it was hidden underneath the
timestamp difference until the timestamps were removed. Recording it as "the rpm
database still differs" without that distinction would lose the finding.

`rawArchive` and `ociLayers` differ **because** these two files do. They are not
independent failures; twenty-eight layers contained one of the fifteen files
before, and the layers containing these two contain them still.

## Four dimensions were not collected, and that is this run's limitation

`normalisedArchive`, `packageInventory`, `sbom` and `selinuxLabels` report
`NOT_COLLECTED` because the collector was invoked without `--sbom` and
`--normalisation`, and because the intended-SELinux manifest was not generated
for either side.

**This is a defect in how the comparison was run, not a property of the builds.**
It is recorded rather than quietly omitted: a comparison missing four of
seventeen dimensions cannot support a reproducibility claim, and this report does
not make one. A complete run requires the SBOM, the normalisation record and
`collect_intended_selinux.py` on both sides.

## Method

```text
build A   /var/tmp/bunny-hermetic-a   fresh clone, empty output tree
build B   /var/tmp/bunny-hermetic-b   fresh clone, empty output tree
base      retained mirror, digest verified against the lock before each build
packages  snapshot fedora-44-beta-20260730, 474 packages, verified before each build
epoch     1785438206, from build/inputs/reproducibility-lock.json
mode      BUNNY_HERMETIC_BUILD=1 BUNNY_ARCHIVE_ONLY=1
```

Both builds reported the same install accounting:

```text
474 packages installed, all 474 locked packages accounted for;
1 signing key(s) imported, each of which signed packages in this snapshot
```

Archive digests:

```text
A  b8ad6a51943acddfe4c71996b19e5afd835c1048285e942a53c20e13c33aaf98
B  914e66b75d34be727fb9b6d1f985dd4097c3243737043848adb1a34cc2030f3b
```

## Verdict against the brief's requirement

The brief requires, before dispatching a hosted build:

```text
raw archive digest: identical                    NOT MET
normalized archive digest: identical             NOT COLLECTED
all archive comparison dimensions: MATCH         NOT MET (3 differ, 4 not collected)
intended SELinux context manifest: MATCH         NOT COLLECTED
```

**The local repeatability gate does not pass.** No hosted build should be
dispatched against this tree, and no new qualification target should be created
from it.

## What would close it

1. Make sqlite output deterministic for the two remaining databases. The content
   is already deterministic; the encoding is not. Options not yet evaluated:
   a deterministic `VACUUM INTO` on a fixed page size, exporting and reimporting
   through rpm's own tooling, or accepting that a sqlite file is not
   byte-reproducible and comparing the databases semantically — which would be a
   change to the reproducibility definition and therefore needs a separate
   reviewed decision, not an implementation choice.
2. Re-run the comparison with the SBOM, the normalisation record and the
   intended-SELinux manifest on both sides, so all seventeen dimensions are
   collected.

Only then does a hosted dispatch measure anything the local builder has not
already settled.
