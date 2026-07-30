<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Image finalisation report

Date: 2026-07-30
Scripts: `build/scripts/finalise-image.sh`, `build/scripts/finalise-package-databases.sh`
Policy: `build/inputs/mutable-state-policy.json`

## What finalisation is for

Fifteen files differed between two builders of one commit. None was product code
and all fifteen were a function of the build environment or the build clock,
which is why they are addressed here rather than in the product.

Finalisation runs inside the build container after packages are installed and
before the archive is written. Every operation is written to converge —
remove-if-present, truncate-to-empty, set-to-epoch — rather than to transform,
because a second run must not change the artifact.

## Stages

```text
 3  remove package caches                /var/cache/dnf, libdnf5, PackageKit, yum
 4  remove DNF countme state             and write countme=0 into every repo file
 5  remove machine identity              hostname, machine-info, dbus machine-id,
                                         random seed, ssh host keys
                                         /etc/machine-id truncated to 0 bytes
 6  remove per-device secrets            /etc/brlapi.key
 7  canonicalise package databases       delegated; see below
 8  make font caches deterministic       directory mtimes pinned, caches rebuilt
 9  normalise approved timestamps        generated package-manager state
10  verify ownership and permissions
11  verify no unexpected mutable state remains
12  emit the finalisation manifest
```

Then, as a separate final layer after the build tree is deleted, every mtime the
build itself wrote is pinned to the epoch.

## Stage 7 was three lines and is now a contract

It used to be:

```bash
sqlite3 "${database}" "PRAGMA wal_checkpoint(TRUNCATE); VACUUM;"
```

which reported success while the two databases still differed. It is now
`finalise-package-databases.sh`, which:

1. verifies the expected input databases exist
2. records pre-finalisation digests
3. validates integrity, and refuses a database SQLite cannot even read
4. applies the selected canonicalisation, or nothing if already canonical
5. ensures no WAL, SHM or journal residue survives
6. validates integrity again
7. runs the package-manager functional checks ADR-028 requires
8. records post-finalisation digests
9. emits a machine-readable manifest
10. is idempotent

The central guarantee is step 4's companion check: the logical content — every
row, in every table, tagged by the SQLite storage class — is digested before and
after, and the build fails if it moved. That turns "VACUUM preserves content"
from a citation into a measurement, and it is what stops a canonicaliser from
normalising a real difference into a false equality.

Full detail: `RPM_DATABASE_FUNCTIONALITY_REPORT.md`.

### Idempotence needed fixing

`VACUUM` increments the file change counter on every run, so running the same
commands twice changed the bytes twice. The finaliser now recognises the
canonical state from the file — journal mode `delete`, page size 4096, no
auto-vacuum, empty freelist, no sidecar — and performs zero writes when it is
already in it. Measured: second run byte-identical.

## The mtime pass, and why it is a separate layer

`usr/share/bunny-os/finalisation.json` had identical content in two builds and
mtimes 203 seconds apart. The dimension collector does not compare mtimes, so
nothing reported it; the layer tar contains them, so `ociLayers` and `rawArchive`
differed and the difference was attributed to the two databases.

It has to be the last step and its own layer, because the step before it ends by
deleting `/tmp/bunny-os`, and that deletion updates `/tmp`'s own mtime after
finalisation has already run.

```bash
mapfile -t mounts < <(awk '$2 != "/" { print $2 }' /proc/self/mounts | sort -u)
# prune the mounts, touch everything newer than the epoch, then assert nothing
# newer than the epoch remains
```

Two things about that list are load-bearing:

* **Only mounts are excluded.** An earlier version also hard-coded
  `/proc /sys /dev /run`. Measured inside the retained base, `/run` is *not* a
  mount, is ordinary image content and can be touched; excluding it left exactly
  one entry in the artifact carrying a wall-clock mtime, 987 seconds past the
  epoch.
* **`/snapshot` must be excluded.** It is the retained package snapshot bind-
  mounted read-only, and touching it fails with `Read-only file system`. It is
  also not in the committed layer, which is the actual reason.

The assertion afterwards is what makes this a check rather than a sweep: a path
that cannot be pinned stops the build instead of shipping an artifact whose
archive digest nobody can explain.

## Mount points are not image content

Three paths are emptied rather than removed, because podman mounts them into the
build container and a mount cannot be removed from inside:

```text
rm: cannot remove '/etc/hostname': Device or resource busy
```

A mounted path is not in the committed layer — which is why the earlier
comparison found no `/etc/hostname` on the podman 5.8.4 side while the 4.9.3 side
had one. The finaliser truncates what it cannot remove, records that it did, and
does not pretend to have settled the question. Whether the path is in the
*artifact* is decided by the machine-identity audit, which reads the built
archive rather than the container that produced it.

## What is deliberately left alone

`usr/lib/sysimage/libdnf5/system.toml` carries an `rpmdb_cookie` derived from the
rpm database. It is not independent state: once the rpmdb is deterministic this
follows. It is left untouched so that if it ever *does not* follow, the
comparison reports a real divergence in the database rather than a file somebody
normalised away.

Font caches are regenerated rather than deleted. Deleting them costs the first
graphical login a full font scan, and this is an accessibility-first project: a
screen-reader user waiting on `fc-cache` is a real cost paid for a reproducibility
problem that has a better fix. Pinning the directory mtimes removes the
nondeterminism at its source.

The libdnf5 transaction history is kept. See
`LIBDNF_TRANSACTION_HISTORY_REPORT.md` for why an empty history was considered
and rejected.

## Failure behaviour

`finalise-image.sh` exits 2 when any per-device secret, machine identity or
countme counter remains, and names the paths. `finalise-package-databases.sh`
exits 2 on eleven distinct conditions, each with its own message, listed in
`RPM_DATABASE_FUNCTIONALITY_REPORT.md` and each covered by a test in
`tests/reproducibility/test_sqlite_determinism.py`.

## What this does not establish

That the finalised artifact reproduces. Finalisation makes the artifact
*capable* of reproducing; whether two builds agree is measured by the
repeatability comparison, and whether two independent builders agree is measured
by the three-builder comparison.
