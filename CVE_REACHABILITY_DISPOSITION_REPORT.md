<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CVE reachability disposition report

Date: 2026-07-30
Scope: 24 unique Critical and High fixable findings, none of which has an available
fix.

## Result

```text
$ python scripts/release.py cve-disposition
per-CVE analyses: 24 of 24 Critical/High advisories
  Unknown                    24
BLOCKED: 24 advisory(ies) block a stable release
```

**All 24 remain `Unknown`, and `Unknown` is blocking.**

Machine-readable: `build/out/qualification/cve-reachability-disposition.json`.

## The five proof classes

| Class | Blocks | Required evidence |
|---|---|---|
| `Not present` | no | exact source **and** binary version; build configuration; symbol or source mapping; reviewer |
| `Present but unreachable` | no | activation analysis; privilege analysis; invocation graph; system configuration; sandbox or MAC control; reviewer |
| `Reachable but mitigated` | **yes** | exact mitigation; bypass analysis; residual impact; reviewer |
| `Reachable and blocking` | **yes** | — |
| `Unknown` | **yes** | — |

Each class's requirements are enforced at parse time, not checked at report time. A
record claiming `Present but unreachable` with five of the six required fields is
rejected; the test suite removes each field in turn and asserts the refusal.

`Reachable but mitigated` blocks deliberately. A mitigation is not a fix. It
becomes non-blocking only through explicit acceptance by a release approver, which
is recorded separately and is not a property of the analysis.

## Why all 24 are Unknown

Nine of the ten bounded reachability questions were answered with measured evidence
in the previous phase and are unchanged:

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Is the vulnerable binary installed? | **yes** | `/usr/sbin/podman` 45,220,848 B; `skopeo` 26,035,008 B; `bootc` 17,397,824 B |
| 2 | Does it run by default? | **no** | no enabled symlink under `/etc/systemd`; no preset enables either |
| 3 | Does it listen on a socket? | **no** | `podman.socket` is a unix socket, absent from `sockets.target.wants` |
| 4 | Can an unprivileged user invoke it? | **yes** | mode 0755 root:root, no setuid |
| 5 | Can Bunny or a plugin invoke it? | **no** | typed fixed broker backends, no generic exec path |
| 6 | Does sandboxing limit exposure? | **yes** | `selinux-policy-targeted` enforcing |
| 7 | **Is the vulnerable code path compiled in and active?** | **unknown** | **not determined** |
| 8 | Can the package be removed? | **no** | `bootc` requires podman and skopeo; `rpm-ostree` requires skopeo |
| 9 | Can the functionality be isolated? | **no** | bootc uses the same libraries in-process to fetch and stage updates |
| 10 | Does a systemd or SELinux control reduce exposure? | **yes** | no enabled unit reaches the code automatically |

Question 7 needs the binary, its debuginfo, and the advisory's own description of
the vulnerable function. None of the three is available on the machine that runs
these gates. See `CVE_BINARY_ANALYSIS_REPORT.md`.

**An unanswered question is not a negative answer.** Guessing here would clear
8 Critical findings on the strength of an assumption.

## The 24 advisories

| Severity | Advisory | Module | Installed | Fixed in | Class |
|---|---|---|---|---|---|
| Critical | GHSA-5cgq-3rg8-m6cv | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-89gr-r52h-f8rx | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-f5wc-c3c7-36mc | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-jppx-rxg9-jmrx | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-rm3j-f69w-wqmq | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-vgwf-h737-ff37 | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-x527-x647-q7gg | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| Critical | GHSA-p77j-4mvh-x3m3 | `google.golang.org/grpc` | v1.72.2 | 1.79.3 | Unknown |
| High | GHSA-65gg-3w2w-hr4h | `github.com/containers/podman/v5` | v5.0.0-2026… | 5.5.2 | Unknown |
| High | GHSA-wp3j-xq48-xpjw | `github.com/containers/podman/v5` | v5.0.0-2026… | 5.6.1 | Unknown |
| High | GHSA-x744-4wpc-v9h2 | `github.com/docker/docker` | v28.5.1 | 29.3.1 | Unknown |
| High | GHSA-4c29-8rgm-jvjj | `github.com/moby/buildkit` | v0.25.1 | 0.28.1 | Unknown |
| High | GHSA-4vrq-3vrq-g6gg | `github.com/moby/buildkit` | v0.25.1 | 0.28.1 | Unknown |
| High | GHSA-cgrx-mc8f-2prm | `github.com/opencontainers/selinux` | v1.12.0 | 1.13.0 | Unknown |
| High | GHSA-f5mr-q85p-6hh6 | `github.com/sigstore/fulcio` | v1.7.1 | 1.8.6 | Unknown |
| High | GHSA-f83f-xpx7-ffpw | `github.com/sigstore/fulcio` | v1.7.1 | 1.8.3 | Unknown |
| High | GHSA-mh2q-q3fh-2475 | `go.opentelemetry.io/otel` | v1.36.0 | 1.41.0 | Unknown |
| High | GHSA-q4h4-gmj2-qvw2 | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| High | GHSA-w879-237q-wc7r | `golang.org/x/crypto` | v0.46.0 | 0.52.0 | Unknown |
| High | GO-2026-5026 | `golang.org/x/net` | v0.48.0 | 0.55.0 | Unknown |
| High | GO-2026-5942 | `golang.org/x/net` | v0.48.0 | 0.56.0 | Unknown |
| High | GO-2026-5970 | `golang.org/x/text` | v0.21.0 | 0.39.0 | Unknown |
| High | GHSA-hrxh-6v49-42gf | `google.golang.org/grpc` | v1.72.2 | 1.82.1 | Unknown |
| High | CVE-2020-27815 | `linux-kernel` | 7.1.5-200.fc44 | 4.9.249 | Unknown |

## The vulnerability gate's rule

The gate may pass only when every Critical and High finding is:

- `Remediated`, or
- `Not present` — independently reviewed, or
- `Present but unreachable` — independently reviewed, or
- `Reachable but mitigated` — independently reviewed **and** explicitly accepted.

The following remain blocking, each enforced in code:

| Blocking condition | Where refused |
|---|---|
| `Unknown` | `NON_BLOCKING_CLASSES` excludes it |
| `Reachable and blocking` | same |
| Review pending | a Critical needs a *completed* review reference |
| Evidence stale | the candidate-commit binding |
| Wrong binary version | `match_installed` in `release/acquisition.py` |
| Wrong source version | `_versions_correspond` in `release/cve.py` |
| Self-reviewed Critical disposition | the reviewer must appear in the delivered-review set |
| An advisory with no analysis at all | `uncoveredAdvisories` blocks |

**A numeric scanner score cannot replace a per-finding disposition.** There is no
field in the model that accepts one, and a test asserts the word "score" appears
nowhere in the aggregate output.

## The two ways a Critical could become non-blocking, and only two

1. **An independent security review** determines per CVE that the finding is not
   reachable. `parse_analysis` requires both a completed review reference *and* a
   reviewer drawn from the delivered-review set: a reference to somebody else's
   review does not make this analysis independent.
2. **Fedora rebuilds** podman, skopeo and bootc against patched Go modules, which
   makes the question moot.

Neither has happened. `dnf check-update podman skopeo` returns nothing, and the
base was rebuilt on 2026-07-29 — a genuinely new digest — without the counts
moving. See `docs/adr/ADR-027-base-image-security-decision.md` for the precise
waiting condition.

## The one finding that is probably a scanner artefact

`CVE-2020-27815` is reported against `linux-kernel 7.1.5-200.fc44.x86_64` with a
stated fixed version of `4.9.249` — a 2020 JFS bug whose "fix" is in a stable
series six major versions behind what is installed.

Recorded as `Unknown` rather than `Remediated`, because the remediation path is
"confirm against the Fedora kernel changelog" and nobody has. Being almost
certainly fine is not evidence.

## Review bundles

One bundle per unresolved advisory, 24 × 9 files, under
`security/reachability/packages/<ADVISORY>/`:

```text
summary.md              what is established, what is not
finding.json            the 29-field analysis record
installed-package.json  carrier objects, candidate carriers, how to confirm
source-package.json     source/debuginfo references and the vendoring note
binary-analysis.json    build ID, stripped state, symbols, and the discipline
activation-analysis.json units, sockets, D-Bus, desktop, invocation paths
sandbox-analysis.json   SELinux, the broker model, residual exposure, limits
evidence-manifest.json  8 evidence files with digests recomputed from disk
review-questions.md     6 questions, in order of what matters to the release
```

Each is self-contained: a reviewer needs the bundle and the repository at the named
commit, and no access to undocumented local state. The evidence manifest's digests
are recomputed at generation time, so a reviewer can verify the bundle describes
the repository it claims to.

## Standing conclusion

No waiver was created. No severity was reduced. No `Unknown` was converted to
anything.

`gate-stable-release` reports `NO-GO` on `vulnerability-position`, and the
`vulnerability-gate` candidate prerequisite reports `PENDING_EXTERNAL_REVIEW` with
the blocker *"24 Critical/High advisories remain Unknown"* and the dependency
*"independent security review"*.

The value of this phase's work on the vulnerability blocker is not that it cleared
anything. It is that 24 questions became four binaries, one of which may not be
installed at all, and the whole set is now packaged for the one party who can
answer it.
