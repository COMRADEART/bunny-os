# Hosted attempt 3 — the first three artifacts, and the difference they caught

Target: `f60408d53017767cd33e00992cca17ba606ee86b` (Commit C, attempt 3).
Runs: H1 `30675747695`, H2 `30675748511`, both `workflow_dispatch` on
`ubuntu-24.04`, plus the local builder's bundle of the same commit.

These are the first hosted hermetic builds to complete. Every earlier attempt
died in the environment, one layer at a time: `sudo command` (Fedora ships
`/usr/sbin/command`, Ubuntu does not), a signing key that lived only in the
operator's home directory, an apt podman that predates `--source-date-epoch`,
and an apt crun that refuses the OCI spec the pinned podman writes. Each fix is
its own commit on this branch.

## What the three comparisons said

```text
REPRODUCIBLE       H1 vs H2   17 of 17, byte-identical archives
NON_REPRODUCIBLE   L  vs H1   fileDigests, ociLayers, rawArchive, normalisedArchive
NON_REPRODUCIBLE   L  vs H2   the same four
```

Two runners under one administrator boundary but on separate machines produced
byte-identical archives: `0319b5fd…` raw, `58c46e5d…` normalised. The local
builder produced `a98e6a16…` / `7a434c55…`.

## The whole difference is one hardlink group

Four files under `usr/share/icewm/themes/` ship with identical content at two
paths, hardlinked by the package. The layer tar stores one path as the real
entry and the other as a link entry, and which is which follows the order the
storage driver walked the directory — readdir order, a property of the build
host's filesystem:

```text
local   REG  clearlooks/taskbar/linux.xpm        LNK  clearlooks-2px/taskbar/linux.xpm
hosted  LNK  clearlooks/taskbar/linux.xpm        REG  clearlooks-2px/taskbar/linux.xpm
```

Every extracted byte matches — `filesystemTree`, `ownership`, `permissions`,
`packageInventory` and `sbom` all MATCH — but the tar members differ, so the
content dimension that reads digests out of the archive attributes the files
differently, and every archive-level digest moves.

The install layer carries 1,337 hardlink entries, mostly identical `.pyc`
files. This attempt flipped four of them; nothing prevents the rest from
flipping on the next pair of hosts. The fix — `finalise-image.sh` step 9a —
rewrites every multi-link file installed by the build's own transaction as an
independent copy with identical bytes and metadata, scoped by
`INSTALLTIME == epoch` so the base image's layers, which ship by digest and
are already identical for every builder, are not copied up.

This attempt is superseded by the target minted after that fix. It is retained
because it is the measurement that found the defect: the first time a second
administrator's machine built this commit, it disagreed with the first by
exactly one filesystem property nobody had controlled.
