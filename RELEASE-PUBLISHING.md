# Publishing an OS build to a GitHub release

`build/scripts/publish_media_release.py` turns a qualified media tree — what
`make build-live-image` leaves in `build/out/live/`, or an archived copy of it —
into a GitHub release carrying the OS build. It is fail-closed: every claim the
release page makes was verified against the tree's own build-time evidence
immediately before upload.

## What gets published

| Asset | What it is |
|---|---|
| `bunny-os-<version>-<arch>.iso` | The medium, whole (≤ 2 GiB) or as `.part-NN` byte ranges |
| `BUNNY-MANIFEST.json` | sha256 of every published file; `critical` marks medium + provenance |
| `provenance.json` | Source commit, base image, tool versions, builder machine |
| `boot-artifacts.json` | The boot verdict: the assembled ISO read back as firmware will |
| `iso-digest.txt`, `SHA256SUMS`, logs | Build-time digests and build logs |
| `RELEASE-SHA256SUMS` | sha256 of every asset on the release itself |

The git tag points at the manifest's `sourceCommit` — a release resolves to a
commit, not to whatever HEAD was when someone ran this.

Parts are never written to scratch: each `.part-NN` asset names a byte range of
the medium and streams straight off it during upload. Publishing costs no
scratch space worth naming, on any host.

## Refusals (exit 2)

The publisher refuses to run when any anchor fails: a file whose digest drifted
from the manifest, a second unmanifested medium in the tree, provenance from a
different commit than the manifest's, a `boot-artifacts.json` verdict that is
not PASS, an `iso-digest.txt` that does not record this medium, a tree carrying
its own `RELEASE-SHA256SUMS`, a tag already owned by another commit, or a source
commit that is not on origin. Exit codes:
2 refused · 3 no token · 4 GitHub refused · 5 uploaded assets failed verification.
A verification failure always leaves the release a draft — never a public page
that half-matches the tree.

An already-published release is never rewritten in place: an identical rerun
re-verifies it read-only, and a divergent one is refused before anything is
deleted — delete the release or pick another `--tag`.

## Running it

Anywhere that can read the tree and reach GitHub — the builder that made the
medium, or a Windows host reading it over `\\wsl$`:

```sh
# look first: validates, plans the parts, renders the notes; touches nothing
python3 build/scripts/publish_media_release.py --tree /root/fa-archive/<run> --dry-run

# publish (draft during upload, published after every asset verifies)
GH_TOKEN=<token with contents:write> make publish-release TREE=/root/fa-archive/<run>
```

Useful flags: `--tag X` (default: the manifest's `imageVersion`),
`--stay-draft` (inspect on GitHub before publishing by hand), `--part-mib N`
(default 1900; hard cap 2048).

## Resuming

Ranges are arithmetic and uploads are reconciled against what is already on the
release: identical assets are skipped, changed ones replaced, and assets from an
earlier attempt that this plan no longer contains are deleted, so the finished
page carries exactly what `RELEASE-SHA256SUMS` describes. Drafts are invisible
to GitHub's by-tag lookup, so the publisher also scans the release list — a
rerun adopts the interrupted draft instead of minting a duplicate. Rerun the
same command after an interrupted upload; it continues where it stopped. A run
that dies mid-upload leaves a draft release with partial assets — rerun to
complete, or delete the release if it should not exist.

## Downloading (for users)

```sh
sha256sum -c RELEASE-SHA256SUMS          # verify everything downloaded
cat 'bunny-os-….iso.part-00' '…part-01' … > 'bunny-os-….iso'   # only when split
```

The expected medium digest is printed in the release notes.
