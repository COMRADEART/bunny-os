<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SQLite physical layout report

Date: 2026-07-30
Tool: `scripts/reproducibility/compare_sqlite_pages.py`
Subjects: `usr/share/rpm/rpmdb.sqlite`, `usr/lib/sysimage/libdnf5/transaction_history.sqlite`
Method: page-by-page comparison of two hermetic builds, inside the pinned builder

## Why this exists

`cmp` says two files differ. A digest says two files differ. Neither says whether
the difference is a header counter, one table's leaf pages, an index built in a
different order, or an overflow chain — and those have different causes and
different fixes. A comparison that cannot answer "which page, and what is on it"
sends the next person back to `cmp` on a 53 MB database.

## Method

Each page is classified from its own bytes, using the B-tree page header layout
from SQLite's file format specification:

```text
offset 0   page type      0x02 interior index, 0x05 interior table,
                          0x0a leaf index,     0x0d leaf table
offset 1   first freeblock
offset 3   cell count
offset 5   start of the cell content area
offset 7   fragmented free bytes
offset 8   right-most child pointer (interior pages only)
```

Page 1 carries the 100-byte file header before its B-tree header, so every offset
on that page is shifted; getting that wrong would classify the schema root as an
unknown page type in every database ever inspected.

Pages are attributed to a named table or index through the `dbstat` virtual
table, which is SQLite's own page-to-object map. Walking root pages by hand was
the alternative; `dbstat` is compiled into the pinned library, is maintained
alongside the file format, and does not have to be re-verified whenever that
format changes. `ENABLE_DBSTAT_VTAB` is present in the builder's 53 compile
options, and its absence would be reported rather than worked around.

## Header fields

Every field the brief names, compared:

| Field | Build A | Build B | |
| --- | --- | --- | --- |
| page-size field | 4096 | 4096 | match |
| write version | 2 (wal) | 2 (wal) | match |
| read version | 2 (wal) | 2 (wal) | match |
| reserved bytes per page | 0 | 0 | match |
| file change counter | 9 / 3 | 9 / 3 | match |
| database size in pages | 12,959 / 56 | 12,959 / 56 | match |
| first freelist trunk page | 0 | 0 | match |
| freelist page count | 0 | 0 | match |
| schema cookie | 50 / 21 | 50 / 21 | match |
| schema format number | 4 | 4 | match |
| default page cache size | 0 | 0 | match |
| largest root b-tree page | 0 | 0 | match |
| text encoding | 1 (UTF-8) | 1 (UTF-8) | match |
| user version | 0 | 0 | match |
| incremental vacuum mode | 0 | 0 | match |
| application ID | 0 | 0 | match |
| version-valid-for | 9 / 3 | 9 / 3 | match |
| SQLite version number | 3.51.2 | 3.51.2 | match |

Values shown as `x / y` are rpmdb / transaction history.

**Every header field matches.** The change counter matching is worth its own
note: it is incremented on every write transaction, so two databases that had
been written a different number of times would differ here. They were not.

## Pages

```text
rpmdb.sqlite
    12,959 pages compared
    50 differ, 12,909 identical
    all 50 attributed to Packages
    b-tree depths: identical for all 21 tables and 29 indexes
    overflow pages: identical set
    freelist trunk pages: none on either side
    freelist leaf pages: none on either side
    pointer-map pages: none — auto_vacuum is 0, so the database has none

transaction_history.sqlite
    56 pages compared
    1 differs, 55 identical
    page 3, attributed to trans
    b-tree depths: identical for all 18 tables and 13 indexes
    overflow pages: identical set
```

## Classification of the differing pages

The classifier distinguishes five cases, in order:

```text
page-type                            the pages are different kinds of page
cell-count                           different number of cells
cell-order-only                      same cells, different offsets
cell-offsets-and-content             offsets moved and content changed
cell-payload-beyond-prefix-or-free-space
                                     offsets identical, cell prefixes identical,
                                     something deeper differs
cell-content                         offsets identical, a cell prefix differs
```

Measured:

```text
rpmdb.sqlite / Packages     50 × cell-payload-beyond-prefix-or-free-space
transaction_history / trans  1 × cell-content
```

Neither is a layout difference. `cell-order-only` is the signature of a different
insertion order, and it did not occur; `cell-count` and `page-type` are the
signatures of a different amount of data, and they did not occur. What occurred
is that the cells are in the same places, in the same order, at the same sizes,
holding different bytes.

### The differing pages, by number

```text
5610 5612 5615 5617 5621 6202 6212 6215 6217 6218 6221 6419 6431 6433 6435
6437 6441 6445 6450 6467 6486 6487 6491 6804 6807 6808 6810 6812 6814 6816
6822 6827 6829 6830 7302 7334 7341 7345 7349 7352 7710 7784 7816 8125 8127
8130 8651 8702 8956 9050
```

They are clustered, which is consistent with `Packages` rows being stored in
`hnum` order and the affected packages being contiguous in install order. They
are not evenly distributed, which rules out a per-page artefact.

## What the layout comparison establishes

1. The physical layout of both databases is already deterministic across two
   builds. Nothing needs canonicalising to make it so.
2. The difference is inside cell payloads, which means it is data.
3. Therefore any transformation that made the bytes match — `VACUUM INTO`, a
   canonical rebuild, a dump and restore — would have done so by rewriting or
   normalising real content, and would have removed the evidence of a build
   defect rather than the defect.

The tag-level decode that names the differing value is in
`RPM_DATABASE_DETERMINISM_REPORT.md`. It is `INSTALLTIME`, on fifty packages, and
nothing else.

## Limits of this report

* It compares two builds on one host. Two builders on different hosts could
  differ in ways this pair cannot show, including a different SQLite build
  laying identical rows out differently. That is why the SQLite identity is
  pinned in the builder lock and the finaliser refuses a mismatch.
* `dbstat` attributes a page to the object that owns it. A page owned by no
  object — a freelist page — is reported as unattributed; none occurred here
  because both freelists are empty.
* Cell payload comparison digests the first 64 bytes of each cell. A difference
  beyond that is detected (the page digest differs) but not localised within the
  cell; localising it is what `diff_rpm_headers.py` does for the rpm database,
  by decoding the payload as the RPM header it is.
