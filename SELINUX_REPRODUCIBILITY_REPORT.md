<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SELinux reproducibility report

Date: 2026-07-30
Tool: `scripts/reproducibility/collect_intended_selinux.py`
Stage: archive. The installed-system half is not qualified and is not claimed.

## The dimension is one question asked at two stages

A bootc container image carries **no** `security.selinux` xattrs in its layers.
Measured on this project's artifact: 165,005 entries, nine with
`security.capability`, zero with `security.selinux`. `bootc install` applies
contexts on the target from the policy the image ships.

So an archive comparison cannot observe an applied label at all. Two builders
would both collect the empty set, the sets would compare equal, and the report
would claim a comparison that did not happen. That is why the dimension was
`NOT_COLLECTED` in the previous pass — for a reason no archive build could ever
fix.

What an archive *can* answer is the other half: given the policy this image ships
and the paths this image contains, what context is each path *supposed* to
receive? That is a deterministic function of two things both builders have.

```text
intendedSelinuxContexts   archive stage             collectable now
appliedSelinuxContexts    installed-system stage    needs a booted device
```

The composite is `MATCH` only when every subcheck **required at the current
stage** is `MATCH`. A subcheck owned by a later stage is reported as outstanding
and is never counted as satisfied.

## Method

Contexts are resolved through the policy's own matcher, `matchpathcon -f`,
against the file-context specification extracted from the image itself — not
through a reimplementation of the matching rules. Regular-expression precedence,
stem optimisation and the `<<none>>` sentinel are subtle, and a hand-rolled
matcher that got any of them wrong would produce a manifest that agreed with
itself on both builders and with the policy on neither.

File type is passed explicitly with `-m`, because the paths are inside an archive
rather than on a filesystem and the policy distinguishes a directory from a
regular file at the same path.

`matchpathcon` exits non-zero when any path has no match, which is normal — the
policy does not label every path. Unmatched paths are recorded as `<<none>>`
rather than dropped: a silently missing path is indistinguishable from a path the
policy declined to label, and only one of those is interesting.

The tool refuses rather than degrades. If `matchpathcon` is absent it exits 2
with a message saying so, because reporting the dimension as not collected while
a tool was simply missing would file an environment defect as an evidence gap.
The same applies if the image ships no file-context specification: an image that
cannot label a target system is a defect, not a measurement problem.

## Result, build A2

```text
entries resolved     165,005
labelled             164,380
unlabelled            (<<none>>)   625
specification        etc/selinux/targeted/contexts/files/file_contexts
```

The paired result and the manifest comparison are in
`LOCAL_HERMETIC_REPEATABILITY_REPORT.md`, which is the document that reports
whether two builds agree. This one describes what is measured and what the
measurement is worth.

## What changed in this pass

The manifest was previously not generated at all — the collector was invoked
without it, and the dimension came out `NOT_COLLECTED` in a summary line. Two
things now prevent that:

1. `local-hermetic-repeatability.sh` generates it for both builds as part of
   collecting evidence, rather than leaving it to whoever remembers.
2. `build_comparison_document.py` refuses a qualification join without a manifest
   from both sides, and says why: without it the dimension is `NOT_COLLECTED`,
   which makes the comparison `INCONCLUSIVE` no matter what else matched.

A third change fixed a defect the tests found. The dimension was being left as
the two nulls the archives honestly report, so a *complete* archive comparison
still came out `NOT_COLLECTED` on it and therefore `INCONCLUSIVE` — a verdict no
archive build could ever escape. The dimension now carries the archive-stage
subcheck, which is a real comparison of a real manifest, while the composite
keeps `appliedSelinuxContexts` outstanding. Satisfying one never reports the
other as done.

## What is still outstanding

```text
appliedSelinuxContexts       BLOCKED — installed-system qualification
```

This is not a gap in the archive comparison; it is a different stage's evidence.
An archive comparison can reach `REPRODUCIBLE` while
`satisfiesInstalledSystemSelinux` stays `false`, and the comparison record says
both. Installation qualification has not begun, and nothing here moves it.

## Limits

* An intended-context manifest establishes what the policy says, not what
  `bootc install` does. A defect in the installer's labelling pass would not
  appear here.
* Two builders shipping the same policy and the same paths must produce the same
  manifest. That is the property being checked. It does not establish that the
  policy is *correct*, only that it is the same.
* The specification is taken from the image, so a build that shipped a different
  policy would produce a different manifest — which is the intended behaviour,
  and would be reported as a difference rather than absorbed.
