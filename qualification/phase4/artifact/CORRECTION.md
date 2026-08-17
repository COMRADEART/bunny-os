# Corrections to `ARTIFACT.md`

`ARTIFACT.md` is committed evidence and is not edited. Two of its lines are
wrong; both are defects of the recording script, not of the artifact. They are
corrected here, with the source that settles each.

## 1. "dirty: 1 file(s)" — the artifact was built from a clean tree

`ARTIFACT.md` reports:

    e906a48793d74544b39c14cc3e35e0654f5311e2
    dirty: 1 file(s)

Read literally that says the release candidate was built from a working tree
that did not match any commit, which under §14 would make its identity
ambiguous and the candidate unusable.

**It was not.** `rc-identity.sh` measures the tree when *it* runs, which was
after the build had finished. The build's own stage markers (`p4-build.log`,
retained beside this file) place it:

| Stage | Started | Duration |
| --- | --- | --- |
| beta payload | 17:05:45Z | 14m55s |
| live medium | 17:20:41Z | 15m46s |
| shell-test image | 17:36:31Z | 79m27s |

The log's last write is 18:56:00Z; `ARTIFACT.md` is stamped 18:57:00Z. So the
`dirty: 1` measurement is one minute *after* the last artifact was produced,
and one hour fifty minutes after the tree state that actually went into the
beta payload.

The authoritative measurement is the one the build took of itself, immediately
after `git reset --hard` and immediately before the first image was built
(`p4-build.log` lines 1–5):

    From /mnt/c/Users/allam/Documents/new/bunny-os
       cfecc6f2..e906a487  feature/bunny-companion-capsules-trust -> winsrc/…
    HEAD is now at e906a487 build(install): the one primitive must not write through a hardlink
    building at: e906a48793d74544b39c14cc3e35e0654f5311e2
    dirty: 0

The same script refuses to build at all if the fetched head is not the
expected commit (`FATAL: fetched head … is not the … candidate`), so
`building at:` is asserted, not merely reported.

What dirtied the one file between 18:56Z and 18:57Z is **not established**.
The builder's tree is clean at that commit now, and the modification did not
survive the next `git reset --hard`, so it cannot be recovered. Stating that
plainly is better than naming a plausible file: what is proved is that the
tree was clean when every artifact digest in `ARTIFACT.md` was produced, and
that a post-build measurement is not evidence about the build.

**The correct line is `dirty: 0`.**

## 2. The beta payload reference is doubled

`ARTIFACT.md` reports:

    localhost/bunny-os-beta:localhost/bunny-os-beta:e906a48793d7

which is not a pullable reference. `rc-identity.sh` prints a literal
`localhost/bunny-os-beta:` prefix in front of `{{index .RepoTags 0}}`, and
`RepoTags[0]` is already the fully-qualified tag.

**The correct reference is:**

    localhost/bunny-os-beta:e906a48793d7

The manifest digest on the following line, `sha256:c87a6616008ce34f9784…`, is
computed by `skopeo` from the same image and is unaffected — it is what a
reader should bind to in any case.

## Both defects are fixed at the source

`rc-identity.sh` now names the dirty files rather than counting them, takes
the build-time measurement from the build's own log rather than re-measuring
afterwards, and prints the repository tag once. A future artifact record
cannot repeat either of these.
