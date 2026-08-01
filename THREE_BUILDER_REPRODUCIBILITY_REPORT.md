<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Three-builder reproducibility report

Date: 2026-08-01
Status: **REPRODUCIBLE — three builders, two administrator boundaries, one archive**

## Result

```text
Qualification target  225a5e1cbbba5765f83579d48842f7be05a25571 (Commit C, attempt 5)
Local build L         local-fedora-wsl        Fedora WSL, podman 5.8.4, crun
Hosted build H1       hosted-H1-30684077591   ubuntu-24.04, run 30684077591
Hosted build H2       hosted-H2-30684078309   ubuntu-24.04, run 30684078309

Raw archive           9439e7816f3effe5661549e50a350c614894eb26b64a4cfb036bf6fb4eb01abd
                      identical from all three builders
Normalised archive    165e57fc958b82656bfa2994cdd1acc545ac8c60450f7da7045cfb7c1a6705aa
                      identical from all three builders

H1 vs H2              REPRODUCIBLE, 17 of 17 dimensions
L  vs H1              REPRODUCIBLE, 17 of 17 dimensions
L  vs H2              REPRODUCIBLE, 17 of 17 dimensions
Builder independence  PASS for L+H1 and L+H2, from real environment evidence
Reproducibility gate  REPRODUCIBLE, independent, satisfies the production gate
```

Every builder fetched the three published inputs by digest — base, builder
image and 474-package snapshot — verified them against the locks it cloned,
built under the epoch the reproducibility lock pins, and presented the same
bytes. The two hosted runs are separate workflow runs on separate runners; the
local builder is a different machine, kernel, filesystem and administrator.

All three pairwise comparisons were required, and each earned its place:
`H1 vs H2` is the pair that caught a runner-image rotation once before, and
`L vs H` is the pair that caught everything below — two hosted runs agreed
with each other through defects the local leg exposed.

The SELinux dimension is satisfied at the archive stage: intended contexts
match from all three builders, and applied contexts are `NOT_COLLECTED`
because they belong to installed-system qualification, which an archive-only
build cannot satisfy and does not claim.

## What it took: every defect the second builder surfaced

The local repeatability gate passed for weeks while every one of these
waited. Each was invisible to same-host comparison — both local builds shared
the property that carried it — and each is fixed at its cause on this branch:

1. **`sudo command podman`** — Fedora ships `/usr/sbin/command`, Ubuntu does
   not. The first hosted attempt died at the first podman call (`f5985f6`).
2. **A signing key in the operator's home directory** — snapshot verification
   read the system trust store and `~/.bunny-dev-keys`. The snapshot now
   ships its keys and verification builds its keyring from them (`f4bb8f9`).
3. **An unimportable evidence bundle** — the workflow never uploaded half of
   what `release/hosted.py` requires, so a successful build would have been
   refused at import. It now produces the complete bundle (`086fa45`).
4. **Ubuntu's podman 4.9** — predates `--source-date-epoch` and
   `--rewrite-timestamp`. The runner installs the static 5.8.4 the builder
   lock pins, digest-checked, and refuses a version the lock does not name
   (`99b6ac2`); crun is then named by path, after podman resolved Ubuntu's
   1.14 ahead of the pinned bundle's (`734ded8`).
5. **Hardlink direction follows readdir order** — the install layer carries
   1,337 hardlink entries, and which member of a group becomes the layer
   tar's real entry is a property of the build host's filesystem. Four icewm
   theme files flipped between `clearlooks/` and `clearlooks-2px/` while
   every extracted byte matched, moving four dimensions. Finalisation step
   9a rewrites every multi-link file the build's own transaction installed
   as an independent copy with identical bytes and metadata (`16dd9a5`).
   The one defect that was in the artifact rather than around it.
6. **Native vs naive overlay diff** — Ubuntu boots overlayfs with
   `redirect_dir=Y`, and containers/storage answers that with its naive diff
   walker: an independent whiteout per deleted path where native emits the
   upperdir's opaque marker and hardlinked whiteouts, and flat byte-sorted
   member order where native walks the tree. Diagnosed from the layer
   inventory the workflow now uploads (`6718a68`); the runner turns the
   module parameter to the Fedora default before any store exists
   (`1c1f903`).
7. **Toolchain records compared banners, not versions** — Fedora's skopeo
   banner carries a git commit Ubuntu's build of the same release cannot
   share, and syft's record was literally `Application: syft`. Records now
   carry parsed versions (`48fd0a3`); the independence evaluator adjudicates
   differences through the builder lock's per-tool classifications, where
   `unknown` still blocks (`10600aa`); and the runner runs the locked
   python 3.14.3 and skopeo 1.22.2 rather than Ubuntu's (`dd564b3`).

Attempt 4 (`e7ce522`, runs 30680015881 and 30680016612) produced the first
byte-identical three-builder result and was refused at independence for
reason 7; its records are retained in the history at `7e7476e`. Attempt 3's
hardlink-flip evidence is retained in
`evidence/reproducibility/hosted-attempt-3/`.

## What this establishes, and what it does not

**Established.** The commit, the three published inputs and the pinned
toolchain determine the archive to the byte, across two kernels, two
filesystems, two container hosts and two administrator boundaries. A builder
anyone can rent reproduces the artifact from the published digests alone, and
the evidence bundle it must present is defined, cross-checked and imported by
script.

**Not established.** Anything an archive does not carry. Applied SELinux
contexts, installation, boot, update, rollback, recovery and hardware
behaviour belong to installed-system qualification and are untouched by this
result. The two hosted builders share one cloud provider and one runner
image; a defect in that image reproduces in both hosted builds, which is why
the local leg — a different OS on different hardware under a different
administrator — is one of the three, and why all three pairs are required
rather than the hosted pair alone.

## Where the evidence lives

```text
evidence/reproducibility/three-builder/   the three pairwise comparison
                                          documents, the three-builder verdict,
                                          the independence verdict, the gate
                                          record and each builder's
                                          normalisation record
operations/data/builders.json             builder records and declared pairs
operations/data/build-comparison.json     the gate's comparison document (L vs H1)
```

## Gate position

```text
Source gate                  PASS
Retained inputs              PASS — published by digest, cold-pull verified
Local byte repeatability     PASS — run 12, 17 of 17, commit 7e7476e
Independent builders         PASS — L+H1 and L+H2, classification-adjudicated
Reproducibility              REPRODUCIBLE — archive stage, three builders
Qualification candidate      still BLOCKED — archive-only; installed-system
                             evidence, reviews, signing and pilots unchanged
Stable release               NO-GO, unchanged
```

Reproducibility was the prerequisite this report owns, and it is the only
line this report moves. Everything an installed system must prove is still
owed, and no line above claims otherwise.
