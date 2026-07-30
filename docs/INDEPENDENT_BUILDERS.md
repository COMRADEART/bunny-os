# Independent builders

How to run a two-builder reproducibility comparison, and what each of the four
claims it can establish actually means.

## The four claims, kept apart

This repository has previously conflated two very different results. The
distinction is now enforced in code.

| Claim | Means | Establishes |
|---|---|---|
| `same-host-repeatability` | One machine, two runs, same output | The build is deterministic |
| `filesystem-content` | Every file inside both images is byte-identical | Content reproducibility, independent of archive packing |
| `archive-byte` | The archive files themselves are byte-identical | A published checksum will match |
| `independent-builder` | Two builders differing in a **strong** dimension produced the same output | Supply-chain verification |

**Only `independent-builder` satisfies the production gate.**

## What counts as independent

`release/reproducibility.py` records five dimensions:

`machineId`, `virtualisationInstance`, `cloudRunner`, `administrator`,
`environmentId`.

Of these, three are **strong**: `machineId`, `cloudRunner`, `administrator`. At
least one strong dimension must differ.

A second VM, container or workspace on the same physical machine is *separate*
but not *independent*. It shares the kernel, the storage, the clock and the
operator, so a compromise or a defect in any of those reproduces identically in
both builds — which is exactly what the comparison exists to detect. The gate
refuses the claim with that reason:

```text
the builders differ only in environmentId, which is environment separation on
one machine. Independent-builder reproducibility requires a different machine,
cloud runner or administrator
```

`machineId` and `administrator` are salted hashes, not raw values. A raw
`/etc/machine-id` is a stable host identifier and does not belong in a committed
evidence file; a hash still compares equal or unequal, which is all the
comparison needs.

## Running a comparison

### 1. Both builders agree the inputs

```text
export BUNNY_BASE_IMAGE="quay.io/fedora/fedora-bootc:44@sha256:<digest>"
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
export BUNNY_BUILDER_ID=builder-a          # builder-b on the other machine
make independent-builder-prepare
```

`independent-builder-prepare` refuses to proceed unless `BUNNY_BASE_IMAGE` is
digest-pinned, and writes the exact source commit, base digest, profile and
steps the second builder must match. `shared_inputs()` later fails the
comparison if the commits, base digests or shared toolchain versions differ, so
a mismatch surfaces as a mismatch rather than as a reproducibility failure.

### 2. Each builder builds in an isolated workspace

```text
git checkout <sourceCommit>
bash build/scripts/build-image.sh beta
bash scripts/reproducibility/collect-builder-record.sh "$BUNNY_BUILDER_ID" > builder-x-record.json
syft "oci-archive:build/out/beta/bunny-os.oci.tar" -o spdx-json=builder-x.spdx.json
```

Isolated means a separate checkout and a separate output directory. Reusing one
workspace makes `environmentId` identical and removes the only thing the record
would have distinguished.

### 3. Compare

```text
python scripts/reproducibility/compare-builds.py \
  --first-record builder-a-record.json  --second-record builder-b-record.json \
  --first-archive builder-a.oci.tar     --second-archive builder-b.oci.tar \
  --first-sbom builder-a.spdx.json      --second-sbom builder-b.spdx.json \
  --claim independent-builder \
  --out operations/data/builders.json

make reproducibility-compare
```

The comparison is done at four levels separately, because they fail separately
and knowing *which* level diverged is the diagnostic. That distinction is not
theoretical here: an earlier round found byte-identical file contents inside
archives with different digests, because `podman save` stamped tar mtimes with
wall-clock time. Reporting only "not reproducible" would have hidden the cause.

## Two things that look like failures and are not

### SBOM file digests always differ

Syft stamps every document with a fresh UUID namespace, a creation timestamp,
and a root entry named after the input file's *path*. Two scans of byte-identical
archives at different paths never produce identical bytes.

Measured: 6077 packages each, of which 6076 matched exactly. The one that did
not was the document-root entry, whose name is the archive's file path and whose
content digest was identical in both.

So the comparison treats a raw SBOM digest mismatch as informational and
compares the **package manifest** — with the document-root entry excluded —
which is the semantic content. A package manifest mismatch is fatal.

### The archive contains an ostree object store

Findings and packages are located at `/sysroot/ostree/repo/objects/…`, not at
`/usr/bin/…`. That is a property of the `fedora-bootc` base, and it means a
package removed with `dnf` still appears in the SBOM. See
`docs/PACKAGE_MINIMISATION.md`.

## Current result

Two isolated workspaces on one machine, `/var/tmp/bunny-builder-a` and
`/var/tmp/bunny-builder-b`, same commit, same pinned base digest:

```text
archive digests : MATCH   b5c0c502e22b936aa170c58f2240b777235da4c15eb715a4309ee2b859bf87d8
file contents   : 83 members, 0 differing
package manifest: MATCH   6076 vs 6076
```

| Claim | Result |
|---|---|
| `same-host-repeatability` | **PASS** |
| `filesystem-content` | **established** |
| `archive-byte` | **established** |
| `independent-builder` | **FAIL** — only `environmentId` differed |

`make reproducibility-compare` exits 2, and correctly. One machine is not two.

## What is needed

A second machine, a cloud runner, or a second administrator. Nothing about this
is solvable on one host, and no amount of additional local builds changes the
answer.

The cheapest real option is a cloud runner: `collect-builder-record.sh` already
reads `GITHUB_RUN_ID` and `CI_JOB_ID` into `cloudRunner`, so a CI-hosted build
would differ in a strong dimension without anyone acquiring hardware.
