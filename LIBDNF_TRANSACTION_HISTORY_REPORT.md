<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# libdnf5 transaction history report

Date: 2026-07-30
Subject: `usr/lib/sysimage/libdnf5/transaction_history.sqlite`
Owner: libdnf5 5.4.1.0-1.fc44 (product image), 5.4.2.1-1.fc44 (builder image)

## Result

```text
difference found       1 of 2 rows in `trans`, in dt_begin and dt_end
cause                  the package-minimisation transaction ran outside the
                       frozen build clock
disposition            the history is retained, and the clock now covers both
                       transactions
deletion               considered and rejected
```

The history was never the problem. It recorded, accurately, that a `dnf remove`
happened at two different wall-clock times in two builds — because it did.

## What the database holds

Measured from the built artifact, identical in both builds:

```text
18 tables, 13 indexes, 0 triggers, 0 views, 56 pages, freelist 0

trans                2      one install, one minimisation
trans_item         475      what each transaction did to each item
item               475      the items themselves
rpm                475      their NEVRA
pkg_name           475
repo                 2      the snapshot, and @System
arch                 2
config               1
trans_state          3      the vocabulary tables
trans_item_state     3
trans_item_action    7
trans_item_reason    7
comps_*              0      no comps groups are used by this profile
item_replaced_by     0      composite primary key, empty
```

`item_replaced_by` is the only table in either database with a composite primary
key. It is empty, and the logical comparison still orders it by that key rather
than treating an empty table as trivially equal.

## The difference, exactly

`trans` row 2, in both builds:

```text
A   id=2  dt_begin=1785439455  dt_end=1785439455
B   id=2  dt_begin=1785439658  dt_end=1785439658

    both:  cmdline  "/usr/bin/dnf --assumeyes remove toolbox"
           state_id 2
           rpmdb_version_begin  eccc475d01712f1c53a3b6aa6e604e1646ca9f4ce8c4b00dfc004e3920ca5b73
           rpmdb_version_end    802b8367a2cbf6bda50099c4de5decc9f20e9f0c84736acfa0e50d169f2145a6
           releasever 44
```

Row 1 — the 474-package install — matched in both builds, because that
transaction ran under the frozen clock. Row 2 did not, because
`install-packages.py` ran the minimisation `dnf remove` with the un-overridden
environment:

```python
subprocess.run(
    ["/usr/bin/dnf", "--assumeyes", "remove", *removals],
    check=True,
    env=environment,          # not transaction_environment
)
```

203 seconds separate the two recorded times, which is how much longer build B
took to reach the minimisation step. Everything else in the row is identical,
including both rpmdb version cookies — so the two builds removed the same package
from the same database state and disagreed only about what time it was.

## Is the history required in the immutable image?

| Question | Answer |
| --- | --- |
| Required at boot? | No. Nothing in the boot path reads it. |
| Required for update? | No. dnf compares versions, not history. |
| Required for repair? | Yes, in practice. `dnf history` is the first thing an operator or a support engineer reaches for. |
| Expected to represent build-time transactions? | Yes, for an immutable image. The transactions that produced it are the only ones there have ever been. |
| Expected to begin empty on a device? | No. A device installed from this image inherits the build's history, which is a truthful record of how the image was made. |
| Reconstructable? | Partly. The package set is in the rpmdb and the SBOM; the *transaction structure* — what was installed together, in what order, with what reason — is only here. |
| Part of supported update and support workflows? | Yes. `dnf history list`, `dnf history info`, and rollback tooling all read it. |

## Approaches considered

| | Approach | Verdict |
| --- | --- | --- |
| A | deterministic canonical rebuild | unnecessary; the layout was already deterministic |
| B | retain only schema and current state | rejected — discards the transaction structure, which is the part that cannot be reconstructed |
| C | initialise an empty supported database | rejected — see below |
| D | move build-time history into build provenance | rejected as a replacement, adopted as a supplement |
| E | another libdnf5-supported method | none needed once the clock was fixed |

**C was the tempting one.** An empty history is trivially deterministic, and
`dnf` recreates the database on first use, so nothing breaks. It was rejected
because it answers a reproducibility question by destroying evidence: an
immutable image whose history says "nothing has ever happened here" is less
truthful than one that records the two transactions that made it, and the
difference would matter to exactly the person debugging a failed update at 3am.

The brief also forbids it directly — *do not delete transaction history without
documenting the operational effect* — and the operational effect of deleting it
is that `dnf history` on a shipped device returns nothing about how the device
got the packages it has.

**D is adopted as a supplement**, not a replacement. The same information is
independently recorded in the build provenance, the package manifest, the SBOM
and the package lock, so a device whose history is lost to a failed update or a
restored backup can still be reasoned about. That redundancy is worth having; it
is not a reason to remove the primary record.

## What was actually done

The minimisation transaction now runs under the same frozen clock as the install:

```python
subprocess.run(
    ["/usr/bin/dnf", "--assumeyes", "remove", *removals],
    check=True,
    env=transaction_environment,
)
```

The rpm queries either side of it still run with the real environment. ADR-028
scopes the override to the package transaction, and defect R7 in the previous
pass was exactly this boundary being drawn too wide; widening it again to make a
different problem easier would repeat that.

The finaliser additionally checkpoints the WAL into the database, removes the
`-wal` and `-shm` residue, and leaves the database in rollback-journal mode so
nothing recreates the sidecars on first read. No recorded transaction is lost:
the finaliser digests the logical content either side of the operation and
refuses if it moved, and a regression test stages a transaction that lives only
in the WAL and asserts it is in the database afterwards.

## Operational effect of what was changed

```text
dnf history list            still returns both transactions
dnf history info 1          still describes the 474-package install
dnf history info 2          still describes the minimisation
recorded times              now the declared build epoch rather than the
                            wall-clock time the build happened to run
```

Anyone reading `dt_begin` as "when this device installed these packages" will get
the commit timestamp. For an image built once and installed on many devices there
was never a correct per-device answer, and the value is written down, checked and
reviewable — the same consequence ADR-028 already accepted for `INSTALLTIME`.

## What this does not establish

That the history is byte-identical between two builders. That is measured by the
three-builder comparison. What is established here is what the file is for, why
it is kept, and that the difference found in it was a build defect rather than a
property of libdnf5.
