# Eight Criticals became one, and the reason is in the advisory database

**Subject.** `localhost/bunny-os-beta:e906a48793d7`, image ID
`6f3bbb9af38dae1636ff5c02dc79b07d3b09774bcacddc15308ae8e80bf3c8b2` — the frozen
Phase 4 Alpha release candidate, at candidate commit `e906a48793d7`. Nothing
here rebuilds it, replaces it, or edits Phase 4 evidence.

**Scanner.** grype 0.116.1 throughout — the same binary Phase 4 used. The only
version that differs is the vulnerability database: Phase 4 scanned against a
late-July build, everything here against v6.1.9, built 2026-08-17T06:19:33Z.

> **A note on this document's own history.** Its first version blamed the
> *route* — `grype dir:` against `grype oci-archive:` — because at the time the
> archive scan had not been run and the two available routes disagreed. The
> archive scan has since run. It agrees with `dir:` exactly, advisory for
> advisory, so the route was never the variable. That version is corrected
> below rather than quietly rewritten, because "the instrument I could reach
> disagreed with the one I could not, so the one I could not must be the
> difference" is a mistake worth leaving visible.

---

## 1. What changed, in one table

Distinct advisories, `--only-fixed`, the scope `build/scripts/security-scan.sh`
uses. Four scans, one candidate (except the first, which is the beta image
Phase 4 measured):

| scan | route | database | distinct | Critical | High | Medium | Low | Unknown |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Phase 4 | `oci-archive:` | July | 114 | **8** | 39 | 61 | 5 | 1 |
| Phase 5 | `oci-archive:` | 2026-08-17 | 56 | **1** | 31 | 19 | 5 | 0 |
| Phase 5 | `dir:` (mounted overlay) | 2026-08-17 | 56 | **1** | 31 | 19 | 5 | 0 |
| Phase 5 | `sbom:` (its own SPDX) | 2026-08-17 | 80 | **8** | 36 | 29 | 6 | 1 |

**The two routes that read the binaries agree exactly** — 56 advisories, zero
in either direction. The route is not the variable.

The SBOM route reports **24 advisories the other two do not**, none the other
way. All 24 are Go modules; seven of them are the Critical
`golang.org/x/crypto` findings that make Phase 4's count.

---

## 2. The mechanism, named

### 2.1 The package is still in the image

grype JSON lists only artifacts it *matched*, so it cannot distinguish "absent"
from "unmatched". The SPDX SBOM lists everything catalogued
(`sha256:f915a1c2bc55f7a84cf42753f9ef63be6d91c5715c849fad91f601baf02b2072`,
6451 packages):

```
golang.org/x/crypto v0.46.0  /usr/bin/skopeo
golang.org/x/crypto v0.53.0  /usr/bin/podman
```

The vulnerable version is present, in `skopeo`, in the candidate.

### 2.2 The advisories still apply

`grype db search --vuln <id>`, the row whose ecosystem is Go:

```
GHSA-5cgq-3rg8-m6cv  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-89gr-r52h-f8rx  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-f5wc-c3c7-36mc  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-jppx-rxg9-jmrx  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-rm3j-f69w-wqmq  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-vgwf-h737-ff37  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-x527-x647-q7gg  github  critical  golang.org/x/crypto  <0.52.0  fix 0.52.0
GHSA-p77j-4mvh-x3m3  github  critical  google.golang.org/grpc <1.79.3 fix 1.79.3
```

`v0.46.0 < 0.52.0`. Nothing was withdrawn, re-scored or re-ranged.

*(The first run of this query was made as `bunny`, found no database at
`/root/.cache/grype`, and printed "NO ROWS" for every advisory — an instrument
answering "I could not look" in the words it uses for "there is nothing there".
It checks its exit status now. Fourth time this phase.)*

### 2.3 The matcher is not at fault

`route/crypto-control.py` lifts the `x/crypto` and `grpc` package records
**verbatim** out of the candidate's own SBOM into a minimal SPDX document and
scans that: 36 matches, all seven Criticals among them, each against
`golang.org/x/crypto@v0.46.0` with `fix=['0.52.0']`.

### 2.4 The database now carries the vulnerable symbols

This is the finding. The Go row of each advisory carries a
`qualifiers.go_imports` list naming the package path and the functions:

```json
{"package": {"name": "golang.org/x/crypto", "ecosystem": "go-module"},
 "detail": {"cves": ["CVE-2026-42508"],
            "qualifiers": {"go_imports": [
               {"path": "golang.org/x/crypto/ssh/knownhosts",
                "symbols": ["hostKeyDB.IsRevoked"]}]},
            "ranges": [{"version": {"type": "go", "constraint": "<0.52.0"},
                        "fix": {"version": "0.52.0", "state": "fixed"}}]}}
```

All seven name symbols under `golang.org/x/crypto/ssh`,
`.../ssh/agent` or `.../ssh/knownhosts` — the SSH stack.
`route/advisory-symbol-qualifiers.txt` has all eight in full.

### 2.5 And the binaries do not carry them

`route/binary-symbol-probe.txt`, against the candidate's own
`/usr/bin/skopeo` and `/usr/bin/podman`:

```
/usr/bin/skopeo
  'golang.org/x/crypto/ssh/knownhosts' does not appear
  hostKeyDB.IsRevoked: absent
  x/crypto packages present: cast5, chacha20, chacha20poly1305, cryptobyte, …
/usr/bin/podman
  'golang.org/x/crypto/ssh/knownhosts' does not appear
  hostKeyDB.IsRevoked: absent
  x/crypto packages present: argon2, blake2b, blowfish, cast5, chacha20, …
```

Both link `x/crypto` for its ciphers and none of its SSH packages. The one
Critical that **is** still reported — `GHSA-p77j-4mvh-x3m3` against
`google.golang.org/grpc` — names `Server.Serve`, `Server.ServeHTTP`,
`Server.handleStream`, and podman does run a gRPC server. The exclusions are
not indiscriminate.

### 2.6 So the granularity depends on what the scanner can read

| grype is given | can it read Go symbols? | granularity | Criticals |
|---|---|---|---:|
| the image (`oci-archive:`, `dir:`) | yes | function | 1 |
| an SBOM without symbol capture | no | module | 8 |

grype says so itself, on the SBOM run's stderr and nowhere else:

> `WARN go binary packages were found but none carry function symbols; go
> vulnerability matching falls back to module granularity and may report false
> positives. if scanning an SBOM, regenerate it with symbol capture enabled for
> more precise results.`

Isolated to one file — same scanner, same database, same minute
(`route/symbol-probe.sh`):

| | distinct | Critical |
|---|---:|---:|
| `grype file:/usr/bin/skopeo` | 12 | **0** |
| `grype sbom:` of a syft catalogue of that same file | 37 | **7** |

**Phase 4's 8 and Phase 5's 1 are both correct, and they are answers to
different questions.** In July the database had no symbol qualifiers for these
advisories, so even the binary-reading route had nothing to narrow on and
reported at module granularity. Nothing about the image changed.

---

## 3. The same database change explains the RPM findings

`evidence/vulnerability/beta-grype.json` — Phase 4's retained scan, 143
matches — breaks down as 74 `linux-kernel` and 40 `go-module`, and **zero rpm**.

The identical `oci-archive:` route, against the current database, returns:

| artifact type | distinct advisories |
|---|---:|
| `rpm` | 26 |
| `go-module` | 21 |
| `python` | 7 |
| `linux-kernel` | 2 |

So the archive route can see `/usr/share/rpm/rpmdb.sqlite` perfectly well — a
61 MB file that is really in the image, with `/usr/lib/sysimage/rpm` a symlink
to it. **The July database simply had no Fedora 44 advisory data**, and the
kernel's 74 generic `linux-kernel` findings have largely been replaced by RPM
advisories against `kernel`, `kernel-core` and `kernel-modules`.

This corrects the first version of this document, which read the zero as an
instrument that could not see RPMs. It could. There was nothing to see yet.

The consequence for Phase 4's record is unchanged in substance and better
stated: **"59 fixable findings, all inherited from the base image" was measured
when the advisory feed had no coverage of the distribution's own packages.** It
was an accurate reading of the data available; it was not a full picture of the
image, and it has not been a full picture at any point since.

---

## 4. Raw match counts measure the deployment layout

`/usr/bin/podman` and `/sysroot/ostree/repo/objects/8c/c9b024….file` are inode
95288 with a link count of 2 — the same file. A filesystem scan catalogues every
Go binary twice: **44 of the 183 `dir:` matches arrived through an ostree object
path.** The archive route, walking layers, reports 141 raw for the same 56
advisories.

Distinct advisories is the only figure that survives the layout. Every count in
this document is distinct advisories.

---

## 5. What this does *not* change

**The blocking position is 8 Critical and the release gate stays blocked.**

`release/vulnerability.py` permits a Critical to reach a non-blocking
disposition only through a completed, independent review reference. A scanner's
symbol analysis is a measurement, not a review; grype's own warning frames the
module-granularity result as the conservative one; and a release gate is the
place to be conservative. The disposition matrix
(`candidate-disposition-matrix.json`) is therefore built from the SBOM route.

Nothing here is a waiver, a downgrade, or a finding marked resolved.

**What it changes is the question for the independent reviewer.** §18's review
would have been handed 24 bundles asserting `installed-not-executed` on the
strength of an argument. It can now be handed a specific, checkable claim:

> *These seven advisories are scoped by their own upstream data to functions in
> `golang.org/x/crypto/ssh`, `.../ssh/agent` and `.../ssh/knownhosts`.
> `/usr/bin/skopeo` and `/usr/bin/podman` link `x/crypto` for its cipher
> packages and do not contain those SSH packages. Confirm or refute.*

That is a far better question than the one the review package currently asks,
and it is the strongest material this project has had for the disposition
Phase 4 wanted and could not justify.

**It leaves a gate defect.** Two runs of the same gate, same image, same
scanner, differ by seven Critical findings depending on what the database
carries and whether the scanner could read symbols — and neither `grype.json`
nor `vulnerability-report.md` records either fact. A result that does not say
how it was measured is not interpretable. No change is made to
`build/scripts/security-scan.sh` here; the recommendation is recorded in
`../gates/RELEASE_GATES.md`.

---

## 6. Reproducing

Everything reads existing artifacts or re-scans an image already in the
builder's store.

| what | how |
|---|---|
| the candidate's package inventory | the SPDX SBOM, digest in `../sbom/retention-manifest.json` |
| the advisory ranges and symbol qualifiers | `route/advisory-delta.sh`, `route/range-report.py`, `route/qualifier-report.py` |
| the go row in full, for one advisory | `route/GHSA-5cgq-3rg8-m6cv-go-row.json` |
| the matcher is not at fault | `route/crypto-control.py` → `route/crypto-control.spdx.json` |
| granularity, isolated to one binary | `route/symbol-probe.sh` → `route/skopeo-{binary,sbom}-scan.json` |
| the four-route comparison | `route/archive-breakdown.py` |
| the gate's own route, current database | `route/oci-archive-scan.sh` → `scan/candidate-archive-fixed.json` |
| the SBOM route | `route/sbom-scan.sh` → `scan/candidate-sbom-fixed.json` |
| are the named symbols in the binaries? | `route/symbol-qualifiers.sh` → `route/binary-symbol-probe.txt` |
| the hardlink and the rpm database | `route/rpm-visibility.sh` |

The two stderr files are kept deliberately:
`scan/candidate-filesystem-fixed.err` and `scan/candidate-archive-fixed.err`
carry no symbol warning; `scan/candidate-sbom-fixed.err` does. That one line is
the whole difference.
