<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Three-builder reproducibility report

Date: 2026-07-30
Status: **BLOCKED — no hosted build was dispatched**

## Result

```text
Local build L         available
Hosted build H1       NOT DISPATCHED
Hosted build H2       NOT DISPATCHED
L vs H1               NOT MEASURED
L vs H2               NOT MEASURED
H1 vs H2              NOT MEASURED

Reproducibility       NON_REPRODUCIBLE (unchanged)
```

Nothing was dispatched, and this report says so rather than describing the plan
as a result.

## Why nothing was dispatched

Two conditions gate a hosted dispatch, and both are enforced by
`create-reproducibility-target.py`, which refuses to create a qualification
target while either fails:

1. **The local repeatability gate.** Dispatching before it passes measures
   something the local builder has not settled. That has happened once in this
   project's history and it cost seven dispatches.
2. **The retained inputs are not published.** A hosted runner has the commit and
   nothing else. It cannot obtain the retained base, the pinned builder image or
   the 474-package snapshot, all of which exist in one directory on one machine.
   See `PACKAGE_INPUT_PUBLICATION_REPORT.md`: this is one token scope.

The second is the binding one. Even a passing local gate would not make a hosted
build possible today.

## What a three-builder comparison requires

Recorded here so the requirement is fixed before the evidence exists, rather than
described afterwards to fit whatever was produced.

### Three pairwise comparisons, not one

```text
L  vs H1
L  vs H2
H1 vs H2
```

All three. A single local-versus-hosted comparison cannot distinguish
reproducibility from one accidentally favourable hosted run, and this project has
already had two hosted runs an hour apart disagree with each other because GitHub
rotated a runner image between them. `H1 vs H2` is the comparison that catches
that, and it is the one a single-pair design omits.

### Builder independence

```text
distinct administrator boundaries    local Fedora builder vs GitHub-hosted
distinct workflow run IDs            H1 and H2 must be separate runs
same builder image digest            sha256:bf9f00d8…
same retained base digest            sha256:1f08084a…
same package snapshot digest         996a7a36…
same source commit                   Commit C
same build epoch                     from reproducibility-lock.json
same profile                         beta
same output-affecting toolchain      the 16 tools classified as such
```

The hosts must differ and the programs that touch the artifact must not. One
hosted run reused as both H1 and H2 is one measurement reported as two, and is
rejected.

### Every archive-stage dimension, in qualification mode

Sixteen collected dimensions plus the archive-stage SELinux subcheck. A dimension
that one builder collected and the other did not is `NOT_COLLECTED`, which makes
the comparison `INCONCLUSIVE` — not a pass weighted by the dimensions that
happened to be easy.

### Allowed conclusions

```text
REPRODUCIBLE
CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE
NON_REPRODUCIBLE
INCONCLUSIVE
```

The qualification prerequisite requires `REPRODUCIBLE`. A database byte
difference is not downgraded to semantic equivalence to reach it; ADR-029 records
that policy as a proposal and it is not approved.

## What the local work established, and what it did not

**Established.** Two clean local builds of one commit, from fresh clones with
separate container stores and no layer cache, produce identical package
databases — 0 of 12,959 pages differ — and identical content for every file in
the image. The causes of the previous differences were measured, not inferred:
an offset build clock, an unfrozen minimisation transaction, wall-clock mtimes in
a COPY layer, and inode numbers in an ldconfig cache.

**Not established.** Anything about a second builder. Both builds share a kernel,
a container store implementation, a clock, a filesystem and an operator. A defect
in any of them reproduces in both, and this comparison cannot see it. That is
determinism; reproducibility is the claim that survives changing the machine.

The `/var/cache/ldconfig/aux-cache` finding is a good illustration of why. Its
content came from inode allocation — a property of the filesystem the build ran
on. Two builds on one host got different inode numbers, which is why it was
visible at all; two builds on *different* hosts would have differed for the same
reason and for several more nobody has looked for yet.

## When this report can be completed

```text
1. gh auth refresh -h github.com -s write:packages,read:packages
2. make publish-retained-base publish-builder-image publish-package-snapshot
3. make verify-published-inputs
4. make cold-pull-input-test
5. make create-reproducibility-target        (refuses unless 1-4 and the local gate pass)
6. make dispatch-hosted-h1
7. make dispatch-hosted-h2                   (a separate run; the same run twice is rejected)
8. make import-three-builder-evidence
9. make compare-three-builds
10. make reproducibility-gate
```

Steps 6 and 7 must build **Commit C** and no other commit. After the target is
created, no build-affecting source may change: a later commit is a different
target and the hosted builds would be measuring something else.

## Gate position

```text
Source gate                  PASS
Retained inputs              BLOCKED
Local byte repeatability     see LOCAL_HERMETIC_REPEATABILITY_REPORT.md
Independent builders         BLOCKED
Reproducibility              NON_REPRODUCIBLE
Qualification candidate      BLOCKED — 2 of 14
Stable release               NO-GO
OEM / enterprise / sync      BLOCKED
```

Unchanged by this report. Nothing here moves an external evidence requirement,
and no hardware, review, signing or pilot work was begun.
