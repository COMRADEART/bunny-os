<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Cold-pull input verification report

Date: 2026-07-30
Status: **BLOCKED — not run**
Workflow: `.github/workflows/verify-reproducible-inputs.yml`

## Result

```text
cold pull executed          NO
inputs retrievable          NOT ESTABLISHED
offline install from the
  published snapshot        NOT ATTEMPTED
```

The workflow exists and has never run, because there is nothing published to
pull. See `PACKAGE_INPUT_PUBLICATION_REPORT.md`: the GitHub token carries no
`write:packages` scope.

## The question this answers, and why it is not the same question

Verifying the retained inputs on the builder that holds them proves the retention
store is intact. It cannot prove availability, because the machine that would
fail the check is the machine that holds the only copy. Every check in
`make verify-published-inputs` passes today against local files and establishes
nothing about whether an independent party can obtain them.

The cold pull runs the same verification somewhere that starts with nothing.

## What the workflow does

A fresh `ubuntu-24.04` runner, and before anything else it makes itself cold:

```text
removes /var/lib/bunny-retention          asserts it is gone afterwards
removes /var/lib/containers/storage       an empty container store
removes /var/cache/dnf                    an empty package cache
blackholes six Fedora mirror hostnames    and checks the block took effect
```

The mirror block is a positive control rather than a formality. "This run did not
resolve a package from the network" is a claim about what a run happened to do; a
route that does not exist is a property of the environment. A step that quietly
fell back to a live repository fails instead of succeeding on packages nobody
pinned.

Then:

1. pull all three inputs by digest from `ghcr.io`
2. recompute each manifest digest from the bytes the registry returned, and
   refuse if the registry served a manifest other than the one pinned
3. recompute every blob's digest and size from the pulled layout — a manifest
   digest pins the manifest, and a registry that served the manifest and lost a
   layer would satisfy a digest check and fail somebody's build
4. unpack the snapshot and count the RPMs against the lock
5. re-derive every package checksum from the RPM itself, not from the lock's
   summary of itself
6. import the Fedora keys the snapshot ships and re-verify every RPM signature
   with `rpmkeys --checksig`
7. confirm `repomd.xml` is present, so the snapshot is a repository and not a
   pile of files
8. resolve and install a package from it inside the *published builder image*,
   with `--network=none` and `gpgcheck=1`

Step 8 is the strongest available evidence that the snapshot is usable rather
than merely present: a repository whose metadata does not match its packages
passes every checksum in steps 5 and 6 and fails the first `dnf install`. It runs
inside the published builder image because that exercises the builder
publication in the same run, and because the dnf doing the resolving should be
the pinned one rather than whatever the verifying host happens to have — an
Ubuntu runner has no dnf at all.

## What the workflow deliberately does not do

* **It does not build.** A candidate build here would conflate "can the inputs be
  fetched" with "does the build reproduce", and the first has to be answered
  before the second is worth asking. The workflow asserts no `.oci.tar` was
  produced.
* **It does not move a gate.** It re-asserts that the stable-release and
  qualification-candidate gates still exit 2 afterwards. If fetching some files
  made a release gate pass, something else is wrong.
* **It does not sign anything** and references no signing secret.

## Evidence it will produce

```text
build/out/qualification/cold-pull.json         per-input result, blob counts,
                                               package counts, signature counts
build/out/qualification/offline-install.json   the transaction, its exit code,
                                               and what was installed
```

Both are uploaded as workflow artifacts with 90-day retention.

## What a pass would and would not establish

**Would.** That the three inputs are retrievable by a party that did not already
have them, that their bytes are the bytes that were locked, that the RPMs still
carry valid Fedora signatures after a round trip through a registry, and that the
snapshot works as a repository with no network.

**Would not.** That the inputs are *durable*. Retention and deletion protection
are repository settings recorded as `unverified` in the publication lock, and a
successful pull today says nothing about whether a cleanup policy removes an
untagged version next month. Nor does it establish anything about the build:
that is the three-builder comparison.

## Gate position

```text
Retained inputs published      NO
Cold pull verified             NO
Independent builders           BLOCKED
```

Unchanged. The workflow is written and unrun, and this report says so rather
than describing a plan as a result.
