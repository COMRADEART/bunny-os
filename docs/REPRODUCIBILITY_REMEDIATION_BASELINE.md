<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Reproducibility remediation baseline

The measured position before any remediation work, captured so that the next
comparison is judged against a recorded starting point rather than against
memory. Every number here was read from a file or a registry, not carried over
from a previous document.

| Field | Value |
| --- | --- |
| Captured | 2026-07-30 |
| Branch | `feature/reproducible-build-remediation` |
| Branched from | `e7600b08236806f1c9c656d79b074924c40dfb19` |
| Working tree at capture | clean |
| Qualification target commit (Commit A) | `9ea5459bdaf122f8c5999683b2c8961555826954` |
| Evidence import commit (Commit B) | `e7600b08236806f1c9c656d79b074924c40dfb19` |
| Profile | `beta`, `BUNNY_ARCHIVE_ONLY=1` on both builders |
| Architecture | `x86_64` only |

Commit B references Commit A as the candidate and does not promote itself. That
property is preserved by this branch: the remediation produces a **new**
qualification target (Commit C) because the build inputs change, and a **new**
evidence import (Commit D) that references it.

## 1. Base image

| Field | Value |
| --- | --- |
| Pinned reference | `quay.io/fedora/fedora-bootc:44@sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b` |
| What that digest is | an **OCI image index**, not a single-architecture manifest |
| Upstream version label | `44.20260730.0` |
| Upstream created | `2026-07-30T11:05:54Z` |
| `ostree.linux` | `7.1.5-201.fc44.x86_64` |
| amd64 manifest digest | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| amd64 layers | 65 |
| amd64 compressed size | 1,088,162,578 bytes (1.013 GiB) |

### Are the upstream blobs still available?

Measured against the registry on 2026-07-30, not inferred:

| Digest | Pinned since | Resolves upstream? |
| --- | --- | --- |
| `sha256:c466de53…` | this qualification target | **yes** — index and all four architecture manifests resolve |
| `sha256:fb71f099…` | Phase 6 | **no** — `manifest unknown` |

```text
$ skopeo inspect docker://quay.io/fedora/fedora-bootc@sha256:fb71f099…
FATA reading manifest sha256:fb71f099… in quay.io/fedora/fedora-bootc: manifest unknown
```

The Phase 6 digest survives **only** in the local builder's podman store. It is
listed by `podman images --digests` and cannot be fetched by any other machine.

That distinction is the whole reason for Workstream 1. A digest-pinned reference
records *which* base was used; it does not make that base obtainable. The local
builder went on building against a base no independent party could have
obtained, and nothing in the build reported it, because the machine that has the
layers cached cannot see the absence.

**Continuity is not claimed for `fb71f099`.** The cached copy has not been
exported, hashed and verified against independent evidence, so this baseline
does not assert that the cached blobs are the blobs Fedora published. The
remediation mirrors `c466de53`, which is still retrievable from upstream and is
the base both halves of the current comparison actually used.

The four architectures published under the index:

| Architecture | Manifest digest | Manifest size |
| --- | --- | --- |
| amd64 | `sha256:1f08084a9a854…` | 19,921 |
| arm64 | `sha256:58dc26498744f…` | 19,881 |
| ppc64le | `sha256:db1a2ef5111f8…` | 19,891 |
| s390x | `sha256:bee1951a6df15…` | 19,639 |

## 2. Toolchains

| Tool | local `local-fedora-wsl` | hosted `hosted-ci-30566412012` | equal? |
| --- | --- | --- | --- |
| operating system | fedora-44 | ubuntu-24.04 | no (permitted) |
| kernel | 6.18.33.2-microsoft-standard-WSL2 | 6.17.0-1020-azure | no (permitted) |
| podman | 5.8.4 | 5.8.4 | **yes** |
| OCI runtime | crun (Fedora default) | runc 1.3.4-0ubuntu1~24.04.1 | **no — not currently compared** |
| storage driver | overlay | overlay | yes |
| skopeo | 1.22.2 | 1.13.3 | **no** |
| python3 | 3.14.3 | 3.13.14 | **no** |
| image-builder | present, unused | absent | **no** |
| syft | 1.50.0 | 1.50.0 | yes |
| grype | 0.116.1 | 0.116.1 | yes |
| tar | GNU tar 1.35 | GNU tar 1.35 | yes |
| CPUs | 22 | 2 | no (permitted) |

Three tool differences block the independence verdict: `skopeo`, `python3`,
`image-builder`. A fourth — the **OCI runtime** — differs and is not in the
recorded toolchain at all, so it is not currently compared. It is recorded in
`runner-environment.txt` but never reaches `evaluate_independence`. That is a
gap in the check rather than a passing result.

### The run that proves the check is not a formality

An earlier hosted run of the same commit against the same base, one hour
earlier, produced a **worse** result:

| | run 30564513627 | run 30566412012 |
| --- | --- | --- |
| runner name | GitHub Actions 1000000607 | GitHub Actions 1000000615 |
| podman | **4.9.3** | **5.8.4** |
| matching dimensions | 8 of 17 | 11 of 17 |
| `filesystemTree` | DIFFER (`etc/hostname`) | MATCH |
| `permissions`, `ownership` | DIFFER (`etc/hostname`) | MATCH |
| differing files | 16 | 15 |

GitHub rotated the `ubuntu-24.04` runner image between the two runs. Ubuntu's
podman 4.9.3 writes `/etc/hostname` into the build container; 5.8.4 does not. A
reproducibility result that changes because the runner image was updated is not
yet a reproducibility result — and `ubuntu-24.04` is a *label*, not a pinned
environment.

## 3. Repository inputs

| Input | State |
| --- | --- |
| `build/Containerfile` | `d5e66f6dd8c8216f8fc89175373ed09b0abeb0cba85749a805ec604098c9dbb8` |
| Package lists | 9 files, 210 lines total; beta uses `common` + `desktop` + `shell` + `applications` (96 named packages) |
| `build/profiles/beta.json` | `removePackages: ["toolbox"]`, `rootFilesystem: ext4` |
| `SOURCE_DATE_EPOCH` | passed as a build arg, derived from `git show -s --format=%ct HEAD` |
| Build epoch, declared | **none** — each builder derives its own from its own checkout |
| `BUNNY_RELEASE_BUILD` | `0` on both builders |

### Package snapshot status: absent

`build/repositories/` contains exactly two files:

```text
README.md
fedora-44-snapshot.repo.example
```

There is no `fedora-44-snapshot.repo`, so `BUNNY_RELEASE_BUILD=1` cannot be
used, so **both builders resolved their package sets against live Fedora
repositories**, roughly one hour apart.

The two builds happened to resolve the same 6,076 packages. That is luck and is
recorded as luck: Fedora publishes continuously, and an earlier recorded build
of this project installed kernel `7.1.5-200.fc44.x86_64` where these two
installed `7.1.5-201.fc44.x86_64`.

## 4. The fifteen differing files

Read from the two committed dimension collections, not from a summary:

```text
etc/brlapi.key
usr/lib/fontconfig/cache/123d59b33ddb0e7c76bb24004bd5cfac-le64.cache-9
usr/lib/fontconfig/cache/18f520a508f13854f77176faf7889ae9-le64.cache-9
usr/lib/fontconfig/cache/3830d5c3ddfd5cd38a049b759396e72e-le64.cache-9
usr/lib/fontconfig/cache/6cdba951d5a16891afaaf2fee13e80e7-le64.cache-9
usr/lib/fontconfig/cache/6ee3103884cce7b2fe6f32eba9089175-le64.cache-9
usr/lib/fontconfig/cache/d63f98f14a274bd69a5425fc33aaac6b-le64.cache-9
usr/lib/fontconfig/cache/feeafda3627faad7596d025cfacea73f-le64.cache-9
usr/lib/sysimage/libdnf5/system.toml
usr/lib/sysimage/libdnf5/transaction_history.sqlite
usr/lib/sysimage/libdnf5/transaction_history.sqlite-shm
usr/lib/sysimage/libdnf5/transaction_history.sqlite-wal
usr/share/rpm/rpmdb.sqlite
var/lib/dnf/repos/fedora-cff72538bc9825a4/countme
var/lib/dnf/repos/updates-3cc07c89a20302f2/countme
```

Out of 104,247 compared files, in images sharing 164,356 identical paths,
identical permissions, identical ownership, an identical 6,076-package
inventory and an identical kernel.

### Each one, with its measured generator

| Path | Mode / owner | Generator, measured | Why it differs |
| --- | --- | --- | --- |
| `etc/brlapi.key` | `0640` `root:brlapi` (0:969) | `brlapi-0.8.7-8.fc44` `%post`: `mcookie > /etc/brlapi.key`. RPM marks the path `%ghost` — the package ships no content | a fresh 128-bit random value per build |
| 7 × `usr/lib/fontconfig/cache/*.cache-9` | `0644` `root:root` | fontconfig 2.17.0 `transfiletriggerin` running `HOME=/root /usr/bin/fc-cache -s`. **Owned by no package** | each cache embeds the indexed directory's **mtime**, and font-directory mtimes are wall-clock install times |
| `usr/lib/sysimage/libdnf5/system.toml` | `0644` `root:root` | libdnf5 | contains `rpmdb_cookie`, a digest **derived from the rpmdb** — it differs only because the rpmdb differs |
| `usr/lib/sysimage/libdnf5/transaction_history.sqlite` + `-wal` + `-shm` | `0644` `root:root` | libdnf5 | records transaction timestamps and an unflushed WAL |
| `usr/share/rpm/rpmdb.sqlite` | `0644` `root:root` | rpm | `INSTALLTIME` per header, plus sqlite page churn |
| 2 × `var/lib/dnf/repos/*/countme` | `0644` `root:root` | dnf | Fedora's per-installation usage counter, contents `0 0 345600 2` |

Measured evidence for the fontconfig claim, from the local builder's image:

```text
cache 3830d5c3ddfd5cd38a049b759396e72e-le64.cache-9
  = md5("/usr/share/fonts")                       ← the cache is keyed by directory path
  header checksum field = 1785427077
/usr/share/fonts/urw-base35   mtime = 1785427077  ← exactly the cache's checksum
/usr/share/fonts             mtime = 1785427093   (2026-07-30 15:58:13)
/usr/share/fonts/adwaita-mono-fonts mtime = 1785426895.247618581
/usr/share/fonts/adwaita-sans-fonts mtime = 1785426895.122728545
```

The nanosecond components are non-zero and differ per directory. The caches are
not merely "environment state": they are a **deterministic function of a
non-deterministic input**, and the input is the build clock.

### What is *not* in the image, and is worth recording

| Path | Present? | Note |
| --- | --- | --- |
| `etc/hostname` | **no** (under podman 5.8.4) | present under podman 4.9.3; the only tree/permission/ownership difference in the earlier run |
| `etc/machine-id` | **yes, and empty (0 bytes)** | correct systemd first-boot semantics — but it is **excluded from comparison as volatile**, so a build that wrote a real machine-id would not be detected |
| SSH host keys | no | — |
| `var/lib/systemd/random-seed` | no | — |
| DHCP leases, NetworkManager connections | no | the directories exist and are empty |

`etc/machine-id` being invisible to the comparison is a finding of this
baseline, not a pre-existing conclusion. The volatile-path exclusion is
justified for `/var/log` and `/run`; applying it to a machine identity means the
comparison cannot see the exact failure the mandatory principles forbid.

## 5. All seventeen dimensions, as measured

| # | Dimension | Kind | State | Detail |
| --- | --- | --- | --- | --- |
| 1 | `filesystemTree` | semantic | **MATCH** | 164,356 paths |
| 2 | `fileDigests` | semantic | **DIFFER** | 15 of 104,247 |
| 3 | `permissions` | semantic | **MATCH** | including every setuid bit |
| 4 | `ownership` | semantic | **MATCH** | — |
| 5 | `extendedAttributes` | semantic | **MATCH** | 9 `security.capability` entries |
| 6 | `selinuxLabels` | semantic | **NOT_COLLECTED** | 0 of 164,962 entries carry `security.selinux` |
| 7 | `packageInventory` | semantic | **MATCH** | 6,076 packages |
| 8 | `sbom` | semantic | **DIFFER** | 7 of 6,076 entries — brlapi, glibc, libdnf5 |
| 9 | `bootConfiguration` | semantic | **MATCH** | 20 entries |
| 10 | `systemdUnits` | semantic | **MATCH** | 1,100 entries |
| 11 | `desktopEntries` | semantic | **MATCH** | 106 entries |
| 12 | `schemas` | semantic | **MATCH** | 138 entries |
| 13 | `kernel` | semantic | **MATCH** | `7.1.5-201.fc44.x86_64` |
| 14 | `initramfs` | semantic | **MATCH** | not built into the container image |
| 15 | `ociLayers` | semantic | **DIFFER** | 28 of 79 layer digests |
| 16 | `rawArchive` | archive-raw | **DIFFER** | `745c7a5e…` vs `6effd086…` |
| 17 | `normalisedArchive` | archive-normalised | **DIFFER** | `298013d2…` vs `0c99bcd8…` |

The normalised archives differ, which is the measurement that matters: the
difference **survives** entry-order, mtime, ownership and gzip-timestamp
normalisation. It is not a packing artefact.

## 6. Security implications of each proposed normalisation

Every normalisation removes information. This table states what each one removes
and what would be lost if it were done carelessly, so that a later reviewer can
see the trade was considered rather than assumed.

| Proposed change | What it removes | Security implication | Mitigation adopted |
| --- | --- | --- | --- |
| Move `brlapi.key` generation to first boot | a per-installation secret from the image | **Improvement, and the largest one here.** Today every device installed from one image shares one BrlAPI authorisation key; anyone with the image has it. A shipped secret is a shipped secret regardless of how weak the thing it guards is | generate on the installed device from `/dev/urandom` via `mcookie`; never a deterministic value; enforce `0640 root:brlapi`; recover if missing; keep BRLTTY working, because this path is accessibility-critical |
| Normalise font-directory mtimes, then regenerate caches | wall-clock install times of font directories | **Neutral.** A directory mtime is not a security property. It is *evidence* of when a build ran, which is preserved in provenance rather than in the artifact | set mtimes to the declared build epoch only under `/usr/share/fonts` and the other fontconfig-scanned roots; do not touch file mtimes that RPM sets from package headers |
| Remove `countme` counters | Fedora's per-installation usage counter | **Improvement.** `countme` is a telemetry counter. Removing it, and disabling the behaviour, matches the project's stated no-telemetry position; it must not be replaced by any other reporting | `countme=0` in every repository definition used by a qualification build; delete `var/lib/dnf/repos/*/countme`; a test fails when one is present |
| Canonicalise the rpm database | per-package `INSTALLTIME` and sqlite page layout | **Requires care.** The rpmdb is what `rpm -V` verifies against and what a security auditor queries. Losing signature or header integrity to gain a matching digest would be a bad trade | run the transaction under a declared build clock so `INSTALLTIME` is deterministic; **do not** hex-edit or rebuild the database by hand; verify with `rpm --verifydb` and a full `rpm -qa` comparison after the change |
| Canonicalise libdnf5 state | transaction timestamps, WAL/SHM residue | **Requires care.** `transaction_history.sqlite` is the record of what was installed and when — it supports repair and audit. `system.toml`'s `rpmdb_cookie` is derived and follows the rpmdb automatically | checkpoint the WAL so `-wal`/`-shm` are absent rather than nondeterministic; keep the history table; document every file removed |
| Exclude `etc/machine-id` from comparison | nothing, today — it is already 0 bytes | **A latent hole.** The exclusion is currently harmless *and* would hide a real leak | stop relying on the volatile exclusion for identity: add an explicit machine-identity gate that asserts the file exists and is empty |
| Separate product SBOM from artifact attestation | the scanned archive's own digest from the product document | **Neutral if done precisely.** Removing a *meaningful* package or file difference to make SBOMs match would be falsification | drop only the SPDX document-root pseudo-package and document identity; keep every real package and every file digest; keep the artifact's true digest in a separate attestation |
| Pin the builder toolchain by digest | the hosted runner's freedom to ship whatever it likes | **Improvement.** It also narrows the trust base to one image that must itself be provenanced and scanned | build the builder image from a digest-pinned base, record its own SBOM and provenance, verify it before use, refuse a mutable tag |
| Use an offline package snapshot | live dependency resolution | **Improvement**, provided signatures are preserved. A snapshot that dropped Fedora's RPM signatures would trade reproducibility for supply-chain integrity, which is the wrong direction | keep every RPM byte-identical with its original Fedora signature; verify each signature and checksum at materialisation *and* at build time; sign the snapshot manifest additionally, not instead |
| Apply `SOURCE_DATE_EPOCH` to the package transaction | real wall-clock time inside the transaction | **Dangerous if over-applied.** A faked clock must never reach certificate validity, signature freshness, advisory dates or metadata expiry | scope the clock override to the transaction only, use local signed snapshot repositories so no TLS handshake depends on it, and record the mechanism; never apply it to evidence timestamps |

## 7. Current decisions, unchanged by this baseline

```text
Source CI:                   PASS — 22 jobs across 3 workflows
Hosted independent build:    PASS — run 30566412012
Builder independence:        BLOCKED — toolchain versions differ
Reproducibility:             NON_REPRODUCIBLE
Qualification candidate:     BLOCKED — 2 of 14 prerequisites
Stable release:              NO-GO
OEM pilot:                   BLOCKED
Enterprise pilot:            BLOCKED
Encrypted-sync pilot:        BLOCKED
```

Nothing in this remediation may move any row other than reproducibility,
builder independence and the three new supply-chain rows it introduces.

## 8. Preserved attempt-1 evidence

Retained under `/var/lib/bunny-retention/evidence/attempt-1/` on the Fedora
builder, and **not** overwritten by anything this branch produces.

| Source | Contents | Verified |
| --- | --- | --- |
| `local-fedora-wsl/` | OCI archive, SBOM, package inventory, builder record, provenance, logs, full dimension collection | archive SHA-256 `745c7a5ea330e510…` — matches the recorded `rawDigest` |
| `hosted-30566412012/` | the same bundle downloaded from the run, plus the verification record and the full dimension collection | archive SHA-256 `6effd086f601a27e…` — matches the recorded `rawDigest` |
| `hosted-30564513627/` | the earlier run's evidence bundle — the one built by a **different runner image** with podman 4.9.3 | retained as the demonstration that a hosted runner label is not a pinned environment |

Both archives were re-downloaded from GitHub and hashed here; the digests were
not copied from the previous report. GitHub's artifact retention is 30 days and
is now not the only copy, which is what Workstream 32 requires.

## 9. What this baseline commits the remediation to

1. The base image must be retrievable by an independent party after upstream
   garbage-collects it. Today it is not.
2. Both builders must run the same output-affecting tools. Today four differ,
   and one of the four is not even compared.
3. Packages must come from one immutable, signed, verified snapshot. Today both
   builders resolve against live repositories and agreeing was luck.
4. Fourteen of the fifteen differing files are a function of the build clock or
   the build environment. One — `brlapi.key` — is a secret that must not be in
   an image at all.
5. `selinuxLabels` must stop being a single dimension that an archive-only build
   can never satisfy, without reducing the total evidence required.
6. Nothing above justifies weakening the reproducibility definition, and this
   branch does not weaken it.
