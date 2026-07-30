<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SQLite determinism baseline

Date: 2026-07-30
Branch: `feature/reproducible-build-remediation`
Subjects: the two files that still differed after the previous remediation pass
Measured from: the retained OCI archives of hermetic builds A and B
Measured with: SQLite 3.51.2, inside the pinned builder image, read-only

This records what the two databases *are*, before anything was changed about
them. It exists because the previous pass concluded that "the remaining byte
variance appears to come from SQLite page allocation or B-tree construction
order", and that conclusion was an inference from a byte difference rather than a
measurement of one.

**It is wrong.** The measurements below are the evidence.

## Result

```text
page size, page count, freelist count, freelist trunk, schema cookie,
user version, application ID, encoding, auto-vacuum, change counter,
version-valid-for, b-tree depths, overflow pages, cell offsets,
schema digest, table/index/trigger/view counts            ALL IDENTICAL

rpmdb.sqlite               50 of 12,959 pages differ, all in Packages
transaction_history.sqlite  1 of 56 pages differ, in trans

logical comparison         LOGICALLY_DIFFERENT, both databases
```

The physical layout is already deterministic. The content is not. Every
"deterministic encoding" approach — `VACUUM INTO`, canonical rebuild, dump and
restore — would have produced matching bytes by normalising away a real
difference in what the databases recorded, and a semantic-comparison policy
would have declared them equal. The byte gate is what caught this.

The cause is reported in `RPM_DATABASE_DETERMINISM_REPORT.md`; it is the build
clock, in two places, and it is not a SQLite property at all.

## Both databases, field by field

Identical values are given once. A field that differed would be marked, and none
did except where stated.

| | `usr/share/rpm/rpmdb.sqlite` | `usr/lib/sysimage/libdnf5/transaction_history.sqlite` |
| --- | --- | --- |
| package-manager owner | rpm 6.0.2-1.fc44 | libdnf5 5.4.1.0-1.fc44 |
| runtime path after installation | `/usr/share/rpm/rpmdb.sqlite` | `/usr/lib/sysimage/libdnf5/transaction_history.sqlite` |
| file size | 53,080,064 bytes (both builds) | 229,376 bytes (both builds) |
| digest, build A | `a3f43a5124a3cd4dd65624931bc8630e5beca225a5a0fd40acdc0f1c935317c7` | `21667510153271f3af8e6f04039238a399993458c41cbe5c09426c7d90344924` |
| digest, build B | `71dc0d5b164b552a3de394ba3eb08b7fcf35f0a1624b16897a2ffa8b51673fd1` | `30bd0ee3d8109c3c2c1a26dc563b9a2107a7e2dfbf758d803cdd9ebc638098a6` |
| SQLite version (inspecting) | 3.51.2 | 3.51.2 |
| SQLite version that last wrote | 3.51.2 | 3.51.2 |
| compile options | 53, digest `b0820ccb9a3b128e…` | same library, same 53 |
| page size | 4096 | 4096 |
| page count | 12,959 | 56 |
| freelist count | **0** | **0** |
| first freelist trunk page | 0 | 0 |
| schema version / cookie | 50 | 21 |
| user version | 0 | 0 |
| application ID | 0 | 0 |
| file change counter | 9 | 3 |
| version-valid-for | 9 | 3 |
| journal mode | wal | wal |
| synchronous | 2 (FULL) | 2 (FULL) |
| auto-vacuum | 0 (NONE) | 0 (NONE) |
| encoding | UTF-8 | UTF-8 |
| tables | 21 | 18 |
| indexes | 29 | 13 |
| triggers | 0 | 0 |
| views | 0 | 0 |
| virtual tables | none | none |
| WITHOUT ROWID tables | none | none |
| composite primary keys | none | `item_replaced_by` |
| BLOB columns | `Packages.blob`, `Installtid.key`, `Sigmd5.key` | none |
| generated columns | none | none |
| collations in schema | none declared | none declared |
| schema digest | `b9feeacf657afe77553e3d61ba869d10…` | `1b9732e30e1510d91801e64ae80da30f…` |
| `PRAGMA integrity_check` | ok | ok |
| `PRAGMA quick_check` | ok | ok |
| logical content digest, A | `1465dfdb7a2e560d2e225695d2609b22…` | `8ff422287e0971d99dba45a83d8b8c66…` |
| logical content digest, B | `ae1708a9f451149860c91766b2e5ded5…` | `e9472a9652beaa55f5b978f8109057c2…` |

The digests are the only fields that differ. Everything a page-allocation
explanation would predict — a different page count, a non-empty freelist, a
different b-tree depth, a different cell layout — is identical.

### A measurement artefact, recorded rather than hidden

The inspector reports `-wal` and `-shm` present for both databases. They are not
in the image: they are created by opening a WAL-mode database, including
read-only, and the inspection created them. What the image ships is a database
whose *persistent journal mode* is `wal`, with no residue beside it. The
finaliser now moves it to `delete`, so nothing recreates the sidecars on an
installed system's first read.

## Row counts

Identical in both builds, for every table in both databases.

`rpmdb.sqlite`:

```text
Basenames 107216   Conflictname 161   Dirnames 26905   Enhancename 0
Filetriggername 4  Group 1015         Installtid 1015  Name 1015
Obsoletename 377   Packages 1015      Providename 45600
Recommendname 244  Requirename 19989  Sha1header 1015  Sigmd5 1014
Suggestname 26     Supplementname 5   Transfiletriggername 57
Triggername 20     sqlite_sequence 1  sqlite_stat1 27
```

`transaction_history.sqlite`:

```text
arch 2      comps_environment 0        comps_environment_group 0
config 1    comps_group 0              comps_group_package 0
item 475    item_replaced_by 0         pkg_name 475   repo 2
rpm 475     sqlite_sequence 2          trans 2        trans_item 475
trans_item_action 7  trans_item_reason 7  trans_item_state 3  trans_state 3
```

## Which pages differ

`scripts/reproducibility/compare_sqlite_pages.py`, page by page, attributing
each page to a schema object through SQLite's own `dbstat` virtual table.

```text
rpmdb.sqlite                12,959 pages   50 differ   12,909 identical
    all 50 in Packages
    classification: cell-payload-beyond-prefix-or-free-space
    page numbers: 5610 5612 5615 5617 5621 6202 6212 6215 6217 6218 6221
                  6419 6431 6433 6435 6437 6441 6445 6450 6467 6486 6487
                  6491 6804 6807 6808 6810 6812 6814 6816 6822 6827 6829
                  6830 7302 7334 7341 7345 7349 7352 7710 7784 7816 8125
                  8127 8130 8651 8702 8956 9050
    header fields match, b-tree depths match, overflow pages match

transaction_history.sqlite      56 pages    1 differs      55 identical
    page 3, in trans
    classification: cell-content
```

`cell-payload-beyond-prefix-or-free-space` is the classifier saying the cell
count, the cell offsets and the first 64 bytes of every cell all match, and
something deeper in a payload does not. That is a content difference wearing a
page difference's clothes, and it is the opposite of what page-allocation
variance looks like — which would move offsets and leave payloads alone.

## Logical comparison

`scripts/reproducibility/compare_sqlite_logical.py`, comparing every row with
its SQLite storage class preserved, ordered by declared primary key where one
exists and as a canonical multiset otherwise.

```text
rpmdb.sqlite                LOGICALLY_DIFFERENT
    schema         identical
    indexes        identical
    triggers       identical (none)
    differing      Packages — 50 of 1015 rows
    inconclusive   none
    rowid order    identical in every table, including Packages

transaction_history.sqlite  LOGICALLY_DIFFERENT
    schema         identical
    differing      trans — 1 of 2 rows
    inconclusive   none
    rowid order    identical in every table
```

No table was inconclusive. Every table in both databases has either a declared
primary key or a usable rowid, so canonical ordering was established everywhere
and nothing was compared as an unordered guess.

**Rowid order is identical.** Insertion order is therefore not the variable
either: the rows went in in the same order in both builds, and fifty of them
carry different values.

## Current difference classification

```text
classification            CONTENT_DIFFERENCE
not                       page allocation
not                       b-tree construction order
not                       freelist state
not                       insertion order
not                       WAL or SHM residue
not                       SQLite version or compile options
not                       page size, encoding, or auto-vacuum mode
```

Both databases hold different content from two builds of one commit against one
set of retained inputs. That is a build defect, and canonicalising the encoding
would have hidden it.

## What was not assumed

The brief's instruction was *"do not assume page allocation is the cause until
the database structures are measured."* Following it changed the answer. The
inference was reasonable — two files of identical length differing in the middle
is what page-layout variance looks like from a distance — and it was wrong, and
the fix it implied would have been worse than the defect.

## Reproducing this baseline

```text
python scripts/reproducibility/extract_archive_paths.py \
    --archive <build>/build/out/beta/bunny-os.oci.tar \
    --path usr/share/rpm/rpmdb.sqlite \
    --path usr/lib/sysimage/libdnf5/transaction_history.sqlite \
    --destination out/<side> --require-all

make inspect-sqlite-databases      BUNNY_RPMDB=… BUNNY_HISTORY=…
make compare-sqlite-pages          BUNNY_FIRST=… BUNNY_SECOND=…
make compare-sqlite-logical        BUNNY_FIRST=… BUNNY_SECOND=…
make compare-rpm-headers           BUNNY_FIRST=… BUNNY_SECOND=…
```

Every one of them runs inside the pinned builder image. A structural report taken
with a different SQLite describes a different on-disk format contract, and
`inspect_sqlite.py --require-sqlite-version` refuses to produce one silently.
