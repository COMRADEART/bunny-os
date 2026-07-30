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

**Also does not establish** what the production gate asks for. This is two runs on **one host with one toolchain**. Reproducibility means two *independent* builders — different machines, ideally different operators — producing the same output. That comparison has never been run and cannot be run here, because only one builder exists.

`make reproducible-build-check` continues to fail closed, and correctly: one host is not two.

## Recommended fix

Normalise the archive wrapper. Options, cheapest first:

1. Repack the tar deterministically after `podman save` — sorted entries, mtimes set to `SOURCE_DATE_EPOCH`, uid/gid zeroed. A dozen lines in `build/scripts/build-image.sh`.
2. Publish `oci-dir` layout rather than a tar, and checksum each blob. The blobs are already content-addressed and already reproducible.
3. Checksum and sign the **image manifest digest** rather than the archive file. This is what registries do and it sidesteps the wrapper entirely.

Option 3 is probably right long-term, because the manifest digest is what `bootc switch` already pins.

## Evidence

`/root/bunny-evidence/reproducibility/developer-digests.txt`, plus both archives retained for comparison. Recorded in `operations/data/dev-qualification.json` as not-run rather than passing, because a differing digest is not a pass however well understood the cause is.
