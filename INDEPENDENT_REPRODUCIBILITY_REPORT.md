<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent reproducibility report

Date: 2026-07-30
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`
Base image: `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`

## Result

```text
outcome: INCONCLUSIVE
  MATCH          1: rawArchive
  NOT_COLLECTED  16: bootConfiguration, desktopEntries, extendedAttributes,
                     fileDigests, filesystemTree, initramfs, kernel,
                     normalisedArchive, ociLayers, ownership, packageInventory,
                     permissions, sbom, schemas, selinuxLabels, systemdUnits

independent builders: no
satisfies production gate: no
```

Machine-readable: `build/out/qualification/reproducibility-comparison.json`.

**This looks worse than the previous report and is more accurate.** The previous
comparison asked three questions and answered them well. This one asks seventeen.

## Why the result moved

`REPRODUCIBLE_BUILD_REPORT.md` recorded three of four claims established:
same-host repeatability, filesystem-content, and archive-byte. Those measurements
were real:

```text
archive digests : MATCH  b5c0c502e22b936a… (both)
file contents   : 83 members, 0 differing
package manifest: MATCH (6076 vs 6076)
```

They are retained in `operations/data/build-comparison.json` under
`priorMeasurements` and are not disputed.

What changed is that a comparison now has to say **which respects it looked at**.
Every dimension has three states, not two:

| State | Meaning |
|---|---|
| `MATCH` | collected from both builders and identical |
| `DIFFER` | collected from both builders and not identical |
| `NOT_COLLECTED` | not gathered from at least one builder |

`NOT_COLLECTED` is the load-bearing state. A dimension nobody measured cannot
contribute to a `REPRODUCIBLE` verdict, so an incomplete comparison reports
`INCONCLUSIVE` rather than passing on the strength of the dimensions that happened
to be easy.

Sixteen of the seventeen were never collected. Of the three the previous phase did
measure, only `rawArchive` has full per-builder values committed; `fileDigests`
and `packageInventory` were committed as a five-entry sample plus a summary, and a
summary compared against itself establishes nothing. They are therefore
`NOT_COLLECTED` here, with the summaries retained as informational.

## The seventeen dimensions

| Dimension | Kind | State |
|---|---|---|
| `filesystemTree` | semantic | NOT_COLLECTED |
| `fileDigests` | semantic | NOT_COLLECTED — sample and summary only |
| `permissions` | semantic | NOT_COLLECTED |
| `ownership` | semantic | NOT_COLLECTED |
| `extendedAttributes` | semantic | NOT_COLLECTED |
| `selinuxLabels` | semantic | NOT_COLLECTED |
| `packageInventory` | semantic | NOT_COLLECTED — sample and summary only |
| `sbom` | semantic | NOT_COLLECTED |
| `bootConfiguration` | semantic | NOT_COLLECTED |
| `systemdUnits` | semantic | NOT_COLLECTED |
| `desktopEntries` | semantic | NOT_COLLECTED |
| `schemas` | semantic | NOT_COLLECTED |
| `kernel` | semantic | NOT_COLLECTED |
| `initramfs` | semantic | NOT_COLLECTED |
| `ociLayers` | semantic | NOT_COLLECTED |
| `rawArchive` | archive-raw | **MATCH** — `b5c0c502e22b936a…`, both 1,852,006,400 bytes |
| `normalisedArchive` | archive-normalised | NOT_COLLECTED |

A `semantic` difference means the two builds are not the same image.
An `archive-raw` difference is a packing difference, tolerable only when explained
*and* when the normalised archive matches. An `archive-normalised` difference means
the difference survived normalisation and is semantic after all.

## The four allowed outcomes

| Outcome | When | Satisfies the production gate |
|---|---|---|
| `REPRODUCIBLE` | every dimension collected and matching | **yes**, and only between independent builders |
| `CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE` | contents match, raw archives differ, difference explained | no |
| `NON_REPRODUCIBLE` | a semantic dimension differs, or a difference survives normalisation | no |
| `INCONCLUSIVE` | a dimension was not collected, or a raw difference is unexplained | no |

A normalised match does **not** excuse an unexplained raw-content difference:
without a `rawVarianceExplanation` the outcome is `INCONCLUSIVE`, not
`CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE`. Tested both ways.

## Why the builders are still not independent

No schema-2 builder record exists at all.

`operations/data/builders.json` carries `builderRecords: []` and
`independencePairs: []`. The two builders in the legacy `comparisons` block were
collected with the schema-1 shell collector and never recorded a build start or
completion time, so upgrading them would mean inventing two timestamps. They are
left as they were measured.

```text
$ python scripts/release.py verify-builder-independence
builder records: 0 (none)
  no independence pair has been declared

Accepted pairings:
  - a local physical builder paired with hosted CI
  - a physical builder paired with hosted CI
  - two separately administered physical builders
  - two independent cloud providers
  - hosted CI paired with a separately administered self-hosted runner

BLOCKED: no verified independent builder pair. A second workspace, container, or
consecutive run on one host is separation, not independence.
```

### The identity model changed from an identifier to a boundary

Schema 1's strongest available dimension was `environmentId`, a hash of the
workspace path. That was enough to *refuse* a same-host claim and not enough to
*support* an independent one, because a second directory is not a trust boundary.

Schema 2 records `administratorBoundary` — who can change the builder — and
`builderType`. Independence is then a property of a **pair**: two records are
independent when they form one of four accepted pairings and satisfy that
pairing's extra condition.

**Schema 2 has no `workspace` field.** The absence is deliberate: a schema with a
field for the workspace invites a comparison that treats two directories as two
builders.

### What is refused, and tested

| Refusal | Reason given |
|---|---|
| two workspaces on one host | share `administratorBoundary`; a defect in the shared kernel, storage or clock reproduces in both builds |
| two containers under one daemon | same |
| a copied builder record | identical in every field except `builderId` |
| the same `builderId` twice | one builder is not two builders |
| two records citing one workflow run | two jobs in one run share the checkout, cache and administrator |
| two consecutive builds by one runner | repeatability, not independence |
| a hosted record with no `workflowRunId` | refused at parse time — without a run identifier the record is an assertion |
| a mutable base tag | two builders pulling `:44` can get different bases |
| a short SHA or a branch name | does not pin a build |
| two cloud VMs at one provider | share a hypervisor and an operator |
| two `local-machine` builders | not an accepted pairing; the model will not infer a boundary from two desktops |
| differing `sourceCommit` or `baseImageDigest` | the builders did not build the same thing |
| differing shared toolchain versions | a content difference could not be attributed to the environment |

## Artifact normalisation

`release/normalisation.py` produces a normalised **copy** and reports both
digests. `build/scripts/normalise-oci-archive.sh` still normalises in place at
build time; the two do different jobs. A comparison that only ever sees normalised
bytes cannot tell "same image, packed differently" from "different images", so both
digests are always emitted.

**Normalisable** (8): tar entry order, entry timestamps, ownership metadata, group
metadata, owner names, PAX timestamp headers, gzip timestamp, filesystem traversal
order.

**Protected** (7, enforced not documented): binary contents, package contents,
generated configuration, signatures, manifests, source commit metadata, image
filesystem differences. `assert_normalisation_scope` raises on any request naming
one, so a future caller cannot widen the scope by passing a longer list.

### A bug the tests found

`gzip.GzipFile` infers the stored original filename from `fileobj.name` and writes
it into the gzip header, so two normalised copies written to different paths
differed in their headers — a normaliser introducing variance of its own. Caught by
normalising one archive to two destinations and comparing. Fixed with an explicit
`filename=""`.

## CI artifact verification

`release/provenance.py` exists to prevent one failure: *trusting an artifact
because it came from GitHub Actions*. A downloaded bundle is a tarball someone
uploaded, carrying whatever its uploader put in it.

Nothing in a provenance record is believed on its own:

| Claim | How it is checked |
|---|---|
| artifact digests | recomputed from the downloaded bytes |
| source commit | compared with the commit being qualified |
| base image digest | compared with the pinned digest, and must be pinned |
| repository and workflow path | compared with the expected values |
| run identity | must be present, and must not already have been accepted |
| freshness | an `expiresAt` in the past is rejected; an absent one is rejected too |
| verification environment | must differ from the environment that built the artifact |

The last row matters most. Verifying a bundle inside the job that produced it
proves nothing: the same runner would write both the artifact and the verdict. The
workflow's `verify` job therefore runs on a fresh runner.

## What is needed

**A hosted CI run.** `.github/workflows/independent-builder.yml` is committed and
has never been dispatched. It checks out an exact SHA, pins the base digest, pins
syft and grype, disables the pip cache, asserts an empty output tree, records
eleven environment facts, emits a schema-2 builder record with a real
`workflowRunId`, emits provenance with a 90-day expiry, and uploads the archive,
SBOM, package inventory, manifests and logs.

One change must be exercised on the Fedora builder first: `BUNNY_ARCHIVE_ONLY=1`,
added to `build/scripts/build-image.sh` so a hosted Ubuntu runner can build without
`image-builder`. An archive-only build produces no qcow2 or raw image and must
never be recorded as a candidate build.

Once a hosted record and a local record exist and the pair is declared, the
comparison needs the sixteen uncollected dimensions gathered from both builders.
That is one build on each side, not more analysis.

## Evidence

- `operations/data/build-comparison.json` — the seventeen dimensions
- `operations/data/builders.json` — legacy comparisons, and the empty schema-2 arrays
- `build/out/qualification/reproducibility-comparison.json`
- `build/out/qualification/builder-independence.json`
- `tests/reproducibility/` — 90 tests, including all four mandated adversarial cases
- `docs/INDEPENDENT_BUILDERS.md` — how to run a real two-builder comparison
