<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Base image retention report

Date: 2026-07-30
Upstream: `quay.io/fedora/fedora-bootc:44@sha256:c466de53…` (an OCI image index)
Selected manifest: `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` (amd64)
Retained at: `/var/lib/bunny-retention/base-images/sha256-c466de53…`

## Result

```text
blobs retained        67
bytes                 1,088,182,499
digests recomputed    every one, and matched
provenance checked    the retained manifest is one the pinned index references
published             NO — see PACKAGE_INPUT_PUBLICATION_REPORT.md
```

## Why retention rather than pinning

Pinning a digest records which base was used. It does not make that base
obtainable, and this project's pinned base became unobtainable within days.

Measured against the registry, not inferred: `c466de53` still resolves upstream;
the Phase 6 digest `fb71f099` returns `manifest unknown`. `fedora-bootc:44` is
rebuilt daily and old digests are garbage collected.

The local builder kept building successfully against the dead digest **because it
had the layers cached**. That is the failure mode worth naming: a build that
appears to reproduce may only be reachable from one machine's cache, and the
machine that would notice is the one that cannot.

## What was verified

* Every one of the 67 blobs was re-hashed after the copy and matched. A mirror
  that changed a digest re-encoded the image, and the lock refuses that.
* The retained manifest was confirmed to be one the pinned index actually
  references, so the lock cannot claim a provenance it never checked.
* The build verifies the pulled image's own manifest digest against the lock
  before it starts, and refuses on a mismatch with both digests named.

`skopeo` refuses `name:tag@sha256:…` — *"Docker references with both a tag and
digest are currently not supported"* — which is exactly the form this project
pins. The tag is stripped for the registry call and kept in the lock, because
rewriting the recorded reference would make the evidence disagree with itself.

## Continuity with the Phase 6 base is not claimed

`fb71f099` survives only in one machine's podman store. It has not been
independently exported and verified against other evidence, so no claim is made
that the retained base is a continuation of it. Evidence produced against
`fb71f099` and evidence produced against `1f08084a` are evidence about two
different bases, and conflating them would be the kind of continuity nobody
checked.

## Architecture

The upstream reference is a four-architecture index. The mirror holds the amd64
manifest and its blobs, and records the other three by digest without their
blobs.

An `aarch64` build would fail at verification rather than silently pull from
upstream. That is the correct behaviour and it also means this project can
currently qualify one architecture.

## What retention does not establish

**That anyone else can obtain it.** The mirror is a directory on the Fedora
builder. Until it is published by digest and pulled from a machine that does not
already have it, the retained base has exactly the property the pinned base had:
it works here.

That is the defect this whole remediation exists to remove, and it is not yet
removed. See `PACKAGE_INPUT_PUBLICATION_REPORT.md`; it is blocked on one token
scope.
