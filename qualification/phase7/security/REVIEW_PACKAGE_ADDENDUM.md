# Phase 7 addendum to the security review package

Extends `qualification/phase6/security/REVIEW_PACKAGE.md` without modifying
it. The subject artifact is unchanged: `e906a48793d7`, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`.

## What Phase 6 left outstanding, now done: the Go High version analysis

Phase 6 stated: *"the per-advisory version-and-symbol analysis done for the
eight Criticals has not been done for the nineteen Go High findings"* and
predicted the analysis *"is likely to change several of those rows"*. It
does. The inventory carries **18** Go-module High findings (the 19 was an
estimate; the count here is from the matrix rows themselves).

**Method, reproducible from committed evidence:** the module versions come
from the Go buildinfo embedded in the subject artifact's own binaries —
extracted from the RC qcow2 (`497add9a…`), with the binaries identified by
resolving the ostree repo objects to deployed paths by hardlink inode
(`go-binaries-buildinfo.json`). Four Go binaries carry the findings:
`/usr/bin/podman`, `/usr/bin/skopeo`, `/usr/libexec/podman/quadlet`,
`/usr/libexec/podman/rootlessport`. The join is
`analyze_high_go.py` (deterministic; run it and diff), output
`high-go-version-analysis.json`.

## The result

| Position | Findings |
| --- | ---: |
| AFFECTED_BY_VERSION in at least one binary | 15 |
| UNDETERMINED — pseudo-versions only | 3 |
| Not embedded in any Go binary | 0 |

**The row-changing detail Phase 6 predicted:** in six advisories the two
main binaries answer differently —

| Advisory | Module | podman | skopeo |
| --- | --- | --- | --- |
| GHSA-q4h4-gmj2-qvw2 | `golang.org/x/crypto` | at/above fix (v0.52+) | **affected** (v0.46.0) |
| GHSA-w879-237q-wc7r | `golang.org/x/crypto` | at/above fix | **affected** |
| GHSA-cgrx-mc8f-2prm | `opencontainers/selinux` | at/above fix | **affected** (v1.12.0) |
| GO-2026-4918 | `golang.org/x/net` | at/above fix | **affected** (v0.48.0) |
| GO-2026-5026 | `golang.org/x/net` | at/above fix | **affected** |
| GO-2026-5942 | `golang.org/x/net` | **affected** | **affected** |

A reviewer dispositioning by the merged module row would have treated
`x/crypto` as one question; on this artifact it is two questions with two
answers, and the affected binary is the one (`skopeo`) that the disabled
update path would have been the main consumer of — see
`UPDATE_TRUST_ARCHITECTURE_DECISION.md` for what that does and does not
imply about reachability.

The three UNDETERMINED rows are podman's own advisories
(GHSA-65gg-3w2w-hr4h, GHSA-wp3j-xq48-xpjw) and `docker/docker`
(GHSA-x744-4wpc-v9h2): the embedded versions are Fedora snapshot
pseudo-versions (`v5.0.0-20260626…+dirty`, `v28.5.1+incompatible`) that
cannot be honestly ordered against a release number. Deciding them needs a
commit-level comparison against the Fedora dist-git build, which is exactly
the kind of determination the independent review exists to make.

## What this does not change

* **Symbols:** the shipped evidence names vulnerable symbols only for the
  eight Criticals. These 18 rows carry `symbols: not named in shipped
  evidence` — the version half is done, the symbol half is not claimed.
* **Dispositions:** all 80 findings remain `PENDING_REVIEW`. This analysis
  sharpens the questions; it answers none of them on its own authority.
* **The gate:** independent security review remains NOT_RUN and blocking.

One recorded wart: `go-binaries-buildinfo.json`'s `goVersion` field for
`/usr/bin/podman` reads `go1.9`, a spurious byte-pattern capture; the field
is informational and no conclusion rests on it. The module list, which
conclusions do rest on, comes from the structured `dep` records.
