# Reproducible build report

Date: 2026-07-29. Result: **the image content is byte-for-byte deterministic. The OCI archive that wraps it is not, and the cause is identified.**

## Method

Two consecutive builds of the same commit on the same builder, with `SOURCE_DATE_EPOCH` pinned to the commit timestamp:

```text
bash scripts/wsl-build.sh reproducibility developer
```

Builder: Fedora 44 under WSL2, podman 5.8.4, image-builder 76.0.0 (osbuild 185). Each run produced `bunny-os.oci.tar`, which was copied aside and hashed.

## Result

```text
3df2a457432013eb244f0213a4da5f1e0389ca7d61bdca213ce4734460a4ce21  developer-run1.oci.tar
f5d1ded21a10c395ab122dba9b6078948f3feb7a207f99752da848faedf32438  developer-run2.oci.tar
```

Different digests. Identical byte length: 2,041,614,848 both times.

## Root cause

Unpacking both archives and hashing every file inside them:

```text
ALL FILE CONTENTS IDENTICAL — difference is tar metadata only
```

`index.json` is identical. Every content-addressed blob under `blobs/sha256/` has the same name, the same size and the same content in both runs. The file list is identical.

The difference is in the tar entry headers:

```text
run 1:  drwxr-xr-x 0/0  0  2026-07-29 22:16  blobs/
run 2:  drwxr-xr-x 0/0  0  2026-07-29 22:19  blobs/
```

**`podman save` stamps tar entry mtimes with the wall-clock time of archive creation rather than honouring `SOURCE_DATE_EPOCH`.** Nothing else varies.

## What this establishes and what it does not

**Establishes:** the container build itself is deterministic. Given the same commit and the same pinned inputs, every layer and every file is reproduced bit for bit. That is the property that actually matters for supply-chain verification, and it holds.

**Does not establish:** that a published artifact would have a stable digest. A verifier comparing `bunny-os.oci.tar` checksums between two builders would see a mismatch and correctly reject it, even though the images are identical.

Both statements were true when first measured. The second has since been fixed; see below.

## Fix applied and verified

Option 1 was implemented: `build/scripts/normalise-oci-archive.sh`, invoked from `build-image.sh` immediately after `podman save`. It repacks the archive with entry order sorted, mtimes pinned to `SOURCE_DATE_EPOCH`, ownership zeroed, and the atime/ctime pax headers dropped. The blobs are already content-addressed and are not touched.

Verified against the two divergent archives above:

```text
before   3df2a457432013eb244f0213a4da5f1e0389ca7d61bdca213ce4734460a4ce21  run1
         f5d1ded21a10c395ab122dba9b6078948f3feb7a207f99752da848faedf32438  run2

after    80ee93068bc7117702a95db3371085dd8fcf27113c1e5a4c9e959b15f26ea160  run1
         80ee93068bc7117702a95db3371085dd8fcf27113c1e5a4c9e959b15f26ea160  run2
```

Two builds of the same commit, previously differing, now produce byte-identical archives.

### A repack is not transparent, and assuming it was cost a round

The first attempt archived `.`, which prefixes every entry with `./`. skopeo tolerated it; **syft refused the archive outright** — "potential path traversal attack with entry: ./" — which would have silently broken SBOM generation for every build. `podman save` does not emit that prefix, so normalisation must not introduce it.

The script now names the top-level entries explicitly, and all three consumers were re-checked against a normalised archive rather than assumed:

| Consumer | Result |
|---|---|
| `skopeo inspect --raw` | manifest parses |
| `syft` | 6252 SPDX packages — identical to the pre-normalisation count |
| `grype` | 95 fixable matches — identical to the pre-normalisation count |

Matching counts confirm the contents are untouched and only the wrapper changed.

`tests/image/test_archive_normalisation.py` guards the specific mistakes: archiving a bare `.`, an unvalidated epoch, missing determinism flags, and undropped pax timestamps.

## Still not production reproducibility

This is two runs on **one host with one toolchain**. Reproducibility means two *independent* builders — different machines, ideally different operators — producing the same output. That has never been run and cannot be run here, because only one builder exists.

`make reproducible-build-check` continues to fail closed, and correctly: one host is not two.

The remaining longer-term improvement is to checksum and sign the **image manifest digest** rather than the archive file. That is what registries do, it is what `bootc switch` already pins, and it sidesteps the wrapper entirely.

## Evidence

`/root/bunny-evidence/reproducibility/developer-digests.txt`, both original archives, and both normalised archives retained for comparison.
