# Reproducible build report

Date: 2026-07-30  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Base image: `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`

**Result: three of four reproducibility claims are established. The fourth —
independent-builder reproducibility — is not, and cannot be on one machine.**

## The four claims, and why they are separate

| Claim | Means | Result |
|---|---|---|
| Same-host repeatability | One machine, two runs, same output | **PASS** |
| Filesystem-content reproducibility | Every file inside both images is byte-identical | **Established** |
| Archive-byte reproducibility | The archive files themselves are byte-identical | **Established** |
| Independent-builder reproducibility | Two builders differing in a strong dimension | **FAIL** |

Only the last satisfies the production gate. This report keeps them apart
because an earlier version of this document did not, and "the build is
deterministic" was read as "the build is reproducible" — which is a materially
stronger claim about a different threat.

## Method

Two isolated workspaces on the Fedora 44 WSL2 builder, `/var/tmp/bunny-builder-a`
and `/var/tmp/bunny-builder-b`, each a separate checkout with a separate output
tree. Same commit, same digest-pinned base, `SOURCE_DATE_EPOCH` pinned to the
commit timestamp. Profile: `beta`, with package minimisation applied.

Builder records captured by `scripts/reproducibility/collect-builder-record.sh`,
comparison by `scripts/reproducibility/compare-builds.py`.

## Result

```text
archive digests : MATCH
  b5c0c502e22b936aa170c58f2240b777235da4c15eb715a4309ee2b859bf87d8
  b5c0c502e22b936aa170c58f2240b777235da4c15eb715a4309ee2b859bf87d8
file contents   : 83 members, 0 differing
package manifest: MATCH (6076 vs 6076)
```

Both archives 1,852,006,400 bytes. Every one of the 83 archive members hashed
identically.

## Why independent-builder still fails

The two builder records differ in exactly one dimension:

| Dimension | builder-a | builder-b |
|---|---|---|
| `machineId` | `331981094da1acaa…` | `331981094da1acaa…` — **same** |
| `virtualisationInstance` | `wsl:FedoraLinux-44` | `wsl:FedoraLinux-44` — **same** |
| `cloudRunner` | null | null — **same** |
| `administrator` | `bd4c15ed4ff08f90…` | `bd4c15ed4ff08f90…` — **same** |
| `environmentId` | `13b4f73576c07c96…` | `0388bd8432f3cf17…` — differs |

`release/reproducibility.py` refuses the claim:

```text
the builders differ only in environmentId, which is environment separation on
one machine. Independent-builder reproducibility requires a different machine,
cloud runner or administrator; otherwise a defect in the shared kernel, storage
or clock reproduces in both builds and the comparison cannot detect it
```

That is the correct answer. Two workspaces share a kernel, a container store, a
clock and an operator. A compromise or a defect in any of them reproduces
identically in both builds, which is exactly what a second builder is supposed
to catch. Recording this as independent reproducibility would be the
`same-host builds marked independent` failure the adversarial tests exist to
prevent — and it is tested.

`make reproducibility-compare` exits 2.

## A measurement that looked like a failure and was not

The two SBOMs have different file digests. Investigated rather than assumed:

| Difference | Cause |
|---|---|
| `documentNamespace` | a fresh UUID per syft run |
| `creationInfo` | a creation timestamp |
| `name`, root `SPDXID` | named after the input file's **path** |
| one package entry | the document-root entry, whose name is the archive path — its content digest `sha256:7a58769c…` was **identical** in both |

6076 of 6077 package entries matched exactly, and the one that did not was
document identity rather than content.

The comparison now excludes the document-root entry and compares the package
manifest, which is the semantic content. A raw SBOM digest mismatch is recorded
as informational; a package manifest mismatch is fatal. Without that change, the
tool would have reported a reproducibility failure that does not exist.

## Previously fixed, and re-verified here

`podman save` stamps tar entry mtimes with the wall-clock time of archive
creation rather than honouring `SOURCE_DATE_EPOCH`. Two builds of one commit
previously produced different archive digests while every file inside was
byte-identical.

`build/scripts/normalise-oci-archive.sh` pins entry order, mtimes, ownership and
drops the atime/ctime pax headers. That fix holds: the two builds above produced
identical archives without any post-processing beyond the normalisation the
build already performs.

The regression tests in `tests/image/test_archive_normalisation.py` guard the
specific mistakes, including archiving a bare `.` — which skopeo tolerated and
**syft refused outright** as a path-traversal attempt, silently breaking SBOM
generation for every build.

## What is needed

A second machine, a cloud runner, or a second administrator. Nothing about this
is solvable locally, and no number of additional workspaces changes the answer.

The cheapest route is a cloud runner. `collect-builder-record.sh` already reads
`GITHUB_RUN_ID` and `CI_JOB_ID` into `cloudRunner`, so a CI-hosted build of the
same commit and base digest would differ in a strong dimension without anyone
acquiring hardware. That is the recommended next step and it is not blocked by
anything else in this phase.

## Evidence

- `operations/data/builders.json` — both comparisons, both builder records
- `evidence/reproducibility/builder-a-record.json`, `builder-b-record.json`
- `docs/INDEPENDENT_BUILDERS.md` — how to run a real two-builder comparison
- `tests/reproducibility/` — 29 tests, including the same-host-marked-independent case
