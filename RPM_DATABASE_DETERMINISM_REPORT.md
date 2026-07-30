<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# RPM database determinism report

Date: 2026-07-30
Decision under test: ADR-028, deterministic package-manager state
Subjects: `usr/share/rpm/rpmdb.sqlite`, `usr/lib/sysimage/libdnf5/transaction_history.sqlite`

ADR-028 closed with *"Not established. That the rpm database is now
byte-identical between two builders. This ADR records the mechanism and the
reasoning; whether it works is a measurement."*

This is that measurement, and it found the mechanism was not doing what the ADR
described.

## Result

```text
mechanism as implemented    a clock that started at the epoch and then ran
mechanism as designed       a clock frozen at the epoch
consequence                 INSTALLTIME spanned epoch+4 to epoch+18, and fifty
                            of 1,015 packages fell on a different second
                            between two builds
second defect               the minimisation transaction ran with no override
                            at all
both fixed                  yes
```

## What was measured

Two hermetic builds, same commit, same retained inputs, same host. The two
databases differed. Everything a layout explanation predicts was checked first
and none of it held (`docs/SQLITE_DETERMINISM_BASELINE.md`):

```text
page size, page count, freelist, b-tree depth, cell offsets    identical
differing pages     50 of 12,959, all in Packages
logical verdict     LOGICALLY_DIFFERENT — 50 of 1015 rows
```

Decoding the differing `Packages` blobs as the RPM headers they are
(`scripts/reproducibility/diff_rpm_headers.py`) gave a single answer:

```text
1015 vs 1015 headers, 50 differing, 965 identical
tags that differ, by how many packages carry the difference:
    INSTALLTIME              50
```

One tag. Not `INSTALLTID`, not `FILESTATES`, not the signature fields — and not
anything about page layout.

## The distribution is the diagnosis

`INSTALLTIME` across all 1,015 packages in build A:

```text
1785409474   epoch-28732   119 packages   from the retained base image
1785409475   epoch-28731   249
1785409476   epoch-28730   172
1785438206   epoch+0         1
1785438210   epoch+4        32   our transaction starts
1785438211   epoch+5        92
1785438212   epoch+6        50
1785438216   epoch+10       14
1785438217   epoch+11       63
1785438218   epoch+12       14
1785438219   epoch+13       72
1785438220   epoch+14       62
1785438221   epoch+15       38
1785438222   epoch+16       23
1785438223   epoch+17        9
1785438224   epoch+18        5
```

A frozen clock produces one value. This produces fourteen, spread across the
fourteen seconds the transaction took. The clock was **offset to the epoch and
then allowed to run**, so `INSTALLTIME` recorded elapsed build time with the
epoch as its zero. Build B took slightly longer to reach each package, and fifty
of them crossed a second boundary in one build and not the other.

`INSTALLTID` was identical in both builds — 1785438209 for all 474 installed
packages — which is why an inventory or transaction-id check would have passed.
That value is taken once, at transaction start; it agreed by luck, not by
design, and a build whose setup took one second longer would have moved it too.

## Cause 1 — the `@` prefix means the opposite of what the code said

`build/scripts/install-packages.py` set:

```python
transaction_environment["FAKETIME"] = f"@{frozen}"
```

with a comment stating *"libfaketime's `@` prefix means 'absolute, frozen'"*.

Measured on libfaketime-0.9.12-12.fc44, across a real 2.5-second sleep:

```text
FAKETIME="2026-07-30 19:03:26"     time() advanced 0.000 s     frozen
FAKETIME="@2026-07-30 19:03:26"    time() advanced 2.500 s     running
```

In libfaketime the `@` prefix selects `FT_START_AT` — begin at this instant and
then run in real time — and the **unprefixed** absolute date is the frozen mode.
The prefix was doing precisely the opposite of what it was there for.

A note on how not to check this: `date` in a child shell reports the same second
under both settings, because libfaketime makes `sleep` return immediately, so no
real time passes. The probe has to sleep for a real interval and then read the
clock. A test now asserts the prefix is absent, for exactly this reason.

## Cause 2 — the minimisation transaction had no clock at all

```python
subprocess.run(
    ["/usr/bin/dnf", "--assumeyes", "remove", *removals],
    check=True,
    env=environment,          # not transaction_environment
)
```

libdnf5 writes `dt_begin` and `dt_end` into `transaction_history.sqlite` from the
system clock. Measured:

```text
A   trans id=2   dt_begin = dt_end = 1785439455
B   trans id=2   dt_begin = dt_end = 1785439658
```

203 seconds apart, which is how much longer build B took to reach that step.
Everything else in the row — command line, state, both rpmdb version cookies —
was identical.

## What was changed

```python
transaction_environment["FAKETIME"] = frozen          # no prefix
...
subprocess.run([...remove...], env=transaction_environment)
```

The rpm queries either side of the transactions still run with the real
environment. ADR-028 scopes the override to the package transaction, and defect
R7 in the previous pass was this boundary being drawn too wide; widening it again
to make a different problem easier would repeat that.

## ADR-028's own verification list

| Check | Result |
| --- | --- |
| `rpm --verifydb` | passes |
| `rpm -qa \| wc -l` | 1,015, unchanged |
| `rpm -V <sample>` | runs; differences are the ones the build made on purpose |
| `dnf history list` | both transactions intact and queryable |
| `make rpmdb-determinism-check` | reported by the repeatability comparison |

Full functional evidence: `RPM_DATABASE_FUNCTIONALITY_REPORT.md`.

## What ADR-028 got right, and what it did not

**Right.** Option A was the correct mechanism, and the rejection of option B
(`rpm --rebuilddb`) was correct for a better reason than the ADR gave. The ADR
rejected it as "a fix that makes the symptom smaller and the diagnosis harder".
Measured, it is worse than that: `--rebuilddb` renumbers every header, moving 594
of 1,015 `Packages` rows and every index that references them, while leaving
`rpm -qa` identical. It is byte-deterministic, so a determinism check alone would
have accepted it.

**Not right.** The ADR described a frozen clock and the implementation delivered
an offset one, and nothing between the decision and the artifact checked which it
was. The lesson is not about libfaketime: a mechanism's *effect* has to be
measured in the artifact, because a decision document records what somebody
intended.

## Toolchain

The library that freezes the clock is now pinned in the builder image and
verified against the builder lock before it is preloaded. It was previously
located with `find /usr/lib64 /usr/lib` on the build host — so whichever
libfaketime the machine happened to carry entered the qualification path, for a
library whose semantics decide fifty package headers.

```text
libfaketime   0.9.12-12.fc44
              sha256:7877f29c417228f151dbcbe182741d0ca516635dae3afb03eac8f3ee6a42d745
              classified output-affecting
sqlite        3.51.2, 53 compile options, digest b0820ccb9a3b128e…
              classified output-affecting
```

## What this does not establish

That two builds now produce byte-identical databases; that is
`LOCAL_HERMETIC_REPEATABILITY_REPORT.md`. That two *independent builders* do;
that is `THREE_BUILDER_REPRODUCIBILITY_REPORT.md`. This report establishes what
the difference was and why, and that the mechanism ADR-028 chose now behaves as
ADR-028 described.
