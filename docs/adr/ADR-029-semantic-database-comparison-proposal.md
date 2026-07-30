<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ADR-029 — Semantic comparison of package databases (proposal, not approved)

| | |
| --- | --- |
| Status | **Proposed — not approved, not in effect** |
| Date | 2026-07-30 |
| Supersedes | — |
| Related | ADR-028 deterministic package-manager state; `docs/SQLITE_DETERMINISM_BASELINE.md` |

## What this document is

A prepared proposal, written so that it exists before it is needed rather than
under the pressure of a release. It changes the definition of a reproducible
build and **it has not been approved**. Nothing in the repository reads it,
`release/comparison.py` still compares database bytes, and the reproducibility
gate does not consult it.

The task that produced it was explicit: *if no supported byte-deterministic
SQLite process can be produced, retain `NON_REPRODUCIBLE`, create a separate
unapproved semantic-comparison policy proposal, and stop.* That condition did not
occur — the databases turned out to differ in content, the causes were build
defects, and they were fixed. The proposal is retained anyway, because the next
person to hit a database difference will be tempted by exactly this, and the
argument against it should be written down before there is a deadline attached to
it.

## The change it would make

From:

```text
the artifact reproduces when every compared file's bytes match
```

to:

```text
the artifact reproduces when every compared file's bytes match, except for
package-manager databases, which reproduce when their logical contents match
```

## Why it is tempting

A SQLite file is a database, not a document. Its bytes encode page allocation,
b-tree fill order, freelist state and a change counter, none of which are
content. Two databases holding identical rows can differ in all of them for
reasons that have nothing to do with what was built. Comparing bytes therefore
looks like comparing an implementation detail, and semantic comparison looks like
comparing the thing that matters.

## Why it was not adopted

**The one time it would have been used, it would have been wrong.** On
2026-07-30 two builds produced `rpmdb.sqlite` files that a byte comparison
rejected. The tempting reading was page allocation. Measured
(`docs/SQLITE_DETERMINISM_BASELINE.md`): identical page count, identical page
size, empty freelist on both sides, identical b-tree depths, identical cell
offsets — and fifty rows of `Packages` holding different `INSTALLTIME` values,
because the build clock was not frozen.

A semantic comparison that ignored physical encoding would still have caught
that one, because the rows differed. But the *class* of the mistake is the point:
the difference was assumed to be encoding, and it was content. A policy written
on that assumption weakens the gate exactly where the assumption fails, and the
failure is silent.

## What an approval would require

A decision to adopt this must contain, and this proposal does not:

### Security analysis

* Which differences become invisible. At minimum: page-level content that no
  SQL query returns, including free space, deleted-row remnants in unallocated
  page regions, and anything in the file outside a b-tree.
* Whether a database can be constructed that is logically identical to a
  legitimate one and physically carries additional data. It can: SQLite's free
  space and unused page regions are not read by any query, and a comparison that
  reads only rows would not see them.
* Whether that matters for an image that is signed and verified as a whole. It
  may not — but "the outer signature covers it" is an argument that has to be
  made, checked against how the artifact is actually verified at each stage, and
  written down.

### Supply-chain implications

* A verifier who rebuilds this image and compares it against the published
  artifact would need this same logic, or would get a different answer than the
  project does. A reproducibility definition that only the producer can evaluate
  is a weaker claim than it appears.
* Which comparison tool is authoritative, and what happens when two
  implementations of "logical equality" disagree.

### Update implications

* Whether an update transaction reads anything the comparison stopped covering.
* Whether a rollback that restores a database compares equal to the one it
  replaced under this definition but not under bytes.

### Forensic implications

* An incident responder asking "is this device's rpm database the one we
  shipped" would get "logically, yes" and would want to know what that excludes.
* Whether the excluded regions can be independently attested.

### Release-policy implications

* Which gates change, in which direction, and what the new failure modes are.
* Whether `REPRODUCIBLE` continues to mean what the existing evidence says it
  means, or whether prior results have to be re-labelled.

### External review requirement

This is a change to what the project claims when it says a build is
reproducible. It should not be approved by the same party that wants a build to
pass, and this proposal is written by the party that was trying to make one pass.

## The narrower alternative

If a genuine, irreducible physical-encoding difference is ever found — measured,
not inferred, with the structural evidence in
`SQLITE_PHYSICAL_LAYOUT_REPORT.md` form — the smaller change is to name the
specific field and normalise it in the *finaliser*, so the artifact is
byte-identical rather than the comparison being loosened. The file change
counter would be an example: it is a header field with no content meaning, and
zeroing it in a finalised database is a defensible transformation of the
artifact. That keeps the gate at bytes.

Loosening the comparison is the last resort, not the first, because every
loosening applies to every future build and to every difference nobody has
looked at yet.

## Status, restated

Proposed. Not approved. Not in effect. The reproducibility gate compares bytes.
