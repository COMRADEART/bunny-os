<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SQLite byte determinism report

Date: 2026-07-30
Tool: `scripts/reproducibility/evaluate_database_approaches.py`
Environment: pinned builder image `sha256:bf9f00d8…`, SQLite 3.51.2
Trials: three per approach, per database, from copies of one pre-finalisation state

## Result

```text
finalisation, three trials     rpmdb.sqlite               A == B == C
                               transaction_history.sqlite A == B == C
logical digests                identical across all three
schemas                        identical
page sizes                     4096, all trials
page counts                    12,959 and 56, all trials
freelist counts                0, all trials
package inventory              1,015, identical digest, all trials
package queries                all pass, all trials
transaction-history rows       identical, all trials
idempotence                    a second finalisation writes nothing
```

The finalisation is byte-deterministic. **That was never the open question**, and
this report says so rather than presenting it as the result.

## The control is the finding

`F-none` — copy the pre-finalisation database and do nothing to it — is
byte-stable across three trials. Trivially so. It is included because it is the
only row that tells you what the other rows are worth:

```text
F-none      a3f43a5124a3  a3f43a5124a3  a3f43a5124a3
C-vacuum    715dc88b6260  715dc88b6260  715dc88b6260
D-into      400f8686f63f  400f8686f63f  400f8686f63f
E-dump      10ba00404eca  10ba00404eca  10ba00404eca
```

Every approach is stable because the *input* is already deterministically
encoded. A three-trial determinism check on a fixed input measures whether the
transformation is a function, not whether the build reproduces. Reporting these
digests as evidence that the reproducibility problem is solved would be reporting
a tautology.

What the trials do establish, and it is worth having:

* the canonicalisation is a pure function of its input — no timestamp, no
  process id, no allocation order leaks into the file;
* it preserves content, checked by a logical digest rather than asserted;
* it leaves every rpm query working;
* it is idempotent, which it was not when first written.

## Per-database results

### `usr/share/rpm/rpmdb.sqlite`

```text
input digest             a3f43a5124a3cd4dd65624931bc8630e5beca225a5a0fd40acdc0f1c935317c7
input logical digest     0b25a26fd82eb025727a6bddb8fb93c4…

approach C, three trials
    file digest          715dc88b62602e763c52fa6980ff3cbc…   × 3
    logical digest       0b25a26fd82eb025727a6bddb8fb93c4…   × 3   (unchanged)
    page size            4096
    page count           12,959
    freelist             0
    journal mode         delete
    tables / indexes     21 / 29
    packages queryable   1,015
    inventory digest     identical across trials
```

### `usr/lib/sysimage/libdnf5/transaction_history.sqlite`

```text
input digest             21667510153271f3af8e6f04039238a399993458c41cbe5c09426c7d90344924
input logical digest     161e16dd727cf87a4992dda32e10b546…

approach C, three trials
    file digest          7523a2fe9d88329628455d1e8b80a6aa…   × 3
    logical digest       161e16dd727cf87a4992dda32e10b546…   × 3   (unchanged)
    page size            4096
    page count           56
    freelist             0
    journal mode         delete
    tables / indexes     18 / 13
    transactions         2, both interpretable
```

`A-rpm-rebuilddb` is recorded as not applicable to the libdnf5 history: pointed
at it, `rpm --rebuilddb` creates an empty rpm database beside it and takes the
directory with it. That is not an approach that failed; it is an approach that
has no meaning there, and the distinction is recorded rather than reported as an
error.

## Idempotence, and why it needed fixing

`VACUUM` increments the file change counter in the SQLite header on every run.
The first version of the finaliser ran the same commands every time, which is
repeatable and is not idempotent:

```text
first run    715dc88b62602e763c52fa6980ff3cbcd55259acc2b7c9d2a39f222b893e4ab0
second run   504d55b2253c445a78401b66c8e67e9dac5c24dd69d074a446b95ba72264175f
```

The finaliser now recognises the canonical state from the file itself — journal
mode `delete`, page size 4096, `auto_vacuum` 0, empty freelist, no `-wal`,
`-shm` or `-journal` beside it — and writes nothing when it is already in it:

```text
first run    715dc88b62602e763c52fa6980ff3cbcd55259acc2b7c9d2a39f222b893e4ab0
second run   715dc88b62602e763c52fa6980ff3cbcd55259acc2b7c9d2a39f222b893e4ab0
```

The recognition is sound in this build because rpm and libdnf5 both leave their
databases in WAL mode, so an unfinalised database cannot present as canonical and
be skipped.

## What is *not* claimed

**That two hermetic builds now produce byte-identical databases.** These trials
run one transformation three times on one input. Two builds produce two inputs,
and whether those inputs agree depends on the build clock, not on SQLite. That
measurement is `LOCAL_HERMETIC_REPEATABILITY_REPORT.md`.

**That two independent builders produce byte-identical databases.** Same-host
trials cannot show a difference that comes from the host. That is
`THREE_BUILDER_REPRODUCIBILITY_REPORT.md`.

**That byte determinism was the missing piece.** It was not. The two databases
differed in content — fifty `INSTALLTIME` values and one pair of libdnf5
timestamps — and a canonicalisation that made them match would have hidden a
build defect. The determinism established here is a property worth having and it
is not the fix.

## Reproducing

```text
make sqlite-determinism-check \
    BUNNY_RPMDB=<extracted rpmdb.sqlite> \
    BUNNY_HISTORY=<extracted transaction_history.sqlite>
```

Inside the pinned builder. `--trials` below three is refused: two runs can agree
by chance in a way three rarely do, and a determinism claim from two measurements
is a coin toss reported as a result.
