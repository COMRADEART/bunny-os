<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# RPM database functionality report

Date: 2026-07-30
Subject: `usr/share/rpm/rpmdb.sqlite` after deterministic finalisation
Measured with: rpm 6.0.2-1.fc44, SQLite 3.51.2, inside the pinned builder image

ADR-028 is explicit that a passing determinism check without a passing
`rpm --verifydb` is a worse outcome than the difference it replaced. This is the
second half.

## Result

```text
finalisation applied      approach C: wal_checkpoint(TRUNCATE), journal_mode=DELETE,
                          page_size=4096, auto_vacuum=NONE, VACUUM
package inventory         1,015 before, 1,015 after, identical digest
logical content digest    unchanged across finalisation
every required query      passes
idempotent                second run writes nothing
```

## The queries ADR-028 requires

Run against the finalised database with `rpm --dbpath`, in the builder image, on
a copy so a failure costs nothing.

| Query | Result | Note |
| --- | --- | --- |
| `rpm -qa` | 1,015 packages | the inventory digest is compared before and after |
| `rpm -q <package>` | pass | |
| `rpm -ql <package>` | pass | file list readable |
| `rpm -qf /usr/bin/rpm` | pass | reverse path lookup uses Basenames and Dirnames |
| `rpm -V <package>` | runs | a non-zero exit means files differ from their headers, which a built image expects; the check is that rpm can read the database at all |
| `rpm --verifydb` | pass | structural check through rpm's own code path |
| `rpm -qi <package>` | pass | includes INSTALLTIME, which is now the build epoch |
| `rpm -q --whatrequires <package>` | pass | exits 1 when nothing requires it, which is an answer |
| `rpm -q --qf '%{INSTALLTIME}'` | pass | reads the frozen value |
| `rpm -q --qf '%{SIGPGP:pgpsig}'` | pass | signature information preserved |

The finaliser runs these itself and refuses if any of them fails, so a database
that canonicalises perfectly and can no longer be queried fails the build rather
than shipping. The list is in
`scripts/reproducibility/finalise_package_databases.py`.

## What finalisation preserves, measured rather than argued

The finaliser digests the logical content — every row, in every table, with each
value tagged by the storage class SQLite reports — before and after the
canonicalisation, and refuses to continue if it moved. That turns "VACUUM is
defined to preserve content" from a citation into a check.

```text
logical content digest before    equal
logical content digest after     equal
row counts, every table          equal
set of tables                    equal
ownership and permissions        equal
```

A `NULL` that became an empty string would move the digest, because the storage
class is part of what is digested. So would a blob whose bytes changed by one.

## Approaches measured, and why the others were rejected

Three trials each, from copies of one pre-finalisation database, in the pinned
builder. Full record: `build/out/reproducibility/database-approaches.json`.

| Approach | Bytes stable | Content preserved | Queries | Verdict |
| --- | --- | --- | --- | --- |
| A `rpm --rebuilddb` | yes | **no** | pass | rejected |
| B canonical header replay | not trialled | — | — | rejected on principle |
| C controlled `VACUUM` | yes | yes | pass | **selected** |
| D `VACUUM INTO` | yes | yes | pass | usable, not selected |
| E dump and restore | yes | yes | pass | usable, not selected |
| F no transformation | yes | yes | pass | the control |

### A — `rpm --rebuilddb` changes content

It is rpm's own supported maintenance operation and it is byte-deterministic
across three trials, so it would have passed a determinism check. It does not
preserve the database:

```text
Packages         594 of 1015 rows differ
Name             594 of 1015
Sha1header       594 of 1015
Basenames     52,769 of 107,216
Requirename   11,367 of 19,989
Dirnames      14,298 of 26,905
Providename    4,159 of 45,600
sqlite_stat1      25 of 27
rowid order differs in Basenames, Dirnames, Group, Name, Packages,
                       Providename, Recommendname, Requirename, Sha1header
```

The package inventory is unchanged — `rpm -qa` returns the same 1,015 names — so
an inventory check alone would have passed it. What changes is the internal
numbering: `--rebuilddb` reassigns header numbers and every index that references
them. Nothing is lost and the database is correct, and it is not the same
database, which is exactly the property a reproducibility comparison depends on.

This is also why the finaliser's content check matters. Without it, A would look
like the safest option available: rpm's own tool, used as documented.

### B — canonical header replay, not trialled

Replaying package headers into a fresh rpm database means owning rpm's on-disk
format outside rpm's own code path. ADR-028 rejected it on the grounds that a
reconstruction which subtly diverged would produce a database that queries
correctly and verifies wrongly, and the brief's prohibition on arbitrarily
rewriting the RPM database is aimed at this class. No measurement changes that:
an approach can be byte-perfect and still be one nobody upstream supports.

Recorded here rather than omitted, so the evaluation is complete rather than
quietly narrower than the brief asked for.

### D and E — usable, not selected

Both are byte-deterministic and content-preserving. Both build a *new* file that
then replaces the original, which means this project owns the construction of a
database rpm did not write. C goes through SQLite's own in-place maintenance
path and leaves the file rpm produced. With three usable options and no
measurable difference between their outputs' correctness, the one that
constructs the least is preferred.

### F — the control, and the load-bearing row

Copying an already-finalised database three times produces identical bytes. That
is trivially true, and it is the row that matters: it says the databases were
*already* deterministically encoded, so C's byte stability demonstrates nothing
about the defect. The canonicalisation is retained as a guard against future
layout variance — a freelist left by a package removal, a WAL that was not
checkpointed — and it is not the fix for what was found.

## Idempotence

`VACUUM` increments the file change counter in the database header on every run.
Measured: a second finalisation of an already-vacuumed database changed the bytes
again.

```text
first run    715dc88b62602e763c52fa6980ff3cbcd55259acc2b7c9d2a39f222b893e4ab0
second run   504d55b2253c445a78401b66c8e67e9dac5c24dd69d074a446b95ba72264175f   (before the fix)
second run   715dc88b62602e763c52fa6980ff3cbcd55259acc2b7c9d2a39f222b893e4ab0   (after)
```

"Run the same commands twice" is not idempotence when one of the commands has a
side effect on a counter. The finaliser now recognises the canonical state from
the file itself — rollback-journal mode, page size 4096, no auto-vacuum, empty
freelist, no sidecar residue — and performs zero writes when it is already in it.
Zero writes is the only number of writes that leaves the bytes alone.

The recognition is sound in this build because rpm and libdnf5 both leave their
databases in WAL mode, so an unfinalised database cannot present as canonical.

## Fail-closed conditions, each verified by its own exit code

| Condition | Verified | Message |
| --- | --- | --- |
| SQLite version differs from the lock | exit 2 | names both versions |
| database is corrupt (unreadable) | exit 2 | "cannot be read by SQLite: database disk image is malformed" |
| database fails `integrity_check` | exit 2 | reports the check output |
| required table missing | exit 2 | names the table |
| virtual table present | exit 2 | explains that VACUUM does not move its content |
| transaction history absent | exit 2 | refuses rather than finalising half |
| non-empty WAL after checkpoint | exit 2 | refuses to discard a transaction |
| logical content changed | exit 2 | reports both digests |
| row counts changed | exit 2 | names the tables |
| ownership or permissions changed | exit 2 | reports both |
| any rpm query fails | exit 2 | names the failing queries |

Tests: `tests/reproducibility/test_sqlite_determinism.py`, 24 cases.

## What this does not establish

* That the databases are byte-identical between two *independent* builders. That
  is measured by the three-builder comparison and reported separately.
* That `rpm -V` reports no differences. It does not, and should not: a built
  image rewrites configuration files, and every difference `rpm -V` reports is
  one the build made on purpose. What is checked is that verification runs.
* Anything about the installed system. These queries run against a database in an
  archive; an installed device's rpm database is qualified at installation, which
  has not begun.
