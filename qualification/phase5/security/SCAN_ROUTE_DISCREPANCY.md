# The vulnerability scan disagrees with itself, and the disagreement is the finding

**Subject.** `localhost/bunny-os-beta:e906a48793d7`, image ID
`6f3bbb9af38dae1636ff5c02dc79b07d3b09774bcacddc15308ae8e80bf3c8b2` — the frozen
Phase 4 Alpha release candidate, at candidate commit `e906a48793d7`. Nothing in
this document rebuilds it, replaces it, or edits Phase 4 evidence.

**Scanner.** grype 0.116.1 throughout — the same binary Phase 4 used.
Vulnerability database v6.1.9, built 2026-08-17T06:19:33Z. Phase 4's scans ran
against the same grype against a database from late July.

---

## 1. What Phase 5 recorded first, and why it was not the good news it looked like

The first Phase 5 re-scan mounted the candidate's overlay in place and scanned
the mounted directory. It reported **183 raw matches, 56 distinct advisories, 1
Critical**, against Phase 4's recorded position of **59 fixable findings, 8
Critical, 28 High**.

That was recorded at the time as *a discrepancy to resolve, not a correction* —
deliberately, because three things differed at once (database, method, counting)
and none of them had been held still. Resolving it turned out to matter a great
deal more than expected.

**Nothing about the product improved. Seven Critical findings stopped being
reported, and the reason is the instrument.**

---

## 2. The chain, one measurement at a time

### 2.1 The package is still there

Phase 4's eight Criticals are seven advisories against `golang.org/x/crypto
v0.46.0` and one against `google.golang.org/grpc v1.72.2`.

A grype JSON only lists artifacts it *matched*, so it cannot say whether an
unmatched package is absent or merely unmatched. The SPDX SBOM lists everything
catalogued. Asked of the candidate's own SBOM
(`sha256:f915a1c2bc55f7a84cf42753f9ef63be6d91c5715c849fad91f601baf02b2072`,
6451 packages):

```
golang.org/x/crypto v0.46.0  acquired from go module information: /usr/bin/skopeo
golang.org/x/crypto v0.46.0  acquired from go module information: /sysroot/ostree/repo/objects/8f/bfb473…file
golang.org/x/crypto v0.53.0  acquired from go module information: /usr/bin/podman
golang.org/x/crypto v0.53.0  acquired from go module information: /sysroot/ostree/repo/objects/8c/c9b024…file
```

The vulnerable version is present, in `skopeo`, in the candidate.

### 2.2 The advisories are still there, still Critical, still applicable

`grype db search --vuln <id>`, filtered to the row whose ecosystem is Go
(`route/range-report.py`, output in §6):

```
GHSA-5cgq-3rg8-m6cv  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-89gr-r52h-f8rx  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-f5wc-c3c7-36mc  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-jppx-rxg9-jmrx  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-rm3j-f69w-wqmq  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-vgwf-h737-ff37  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-x527-x647-q7gg  provider=github  severity=critical  golang.org/x/crypto  constraint '<0.52.0'  fix 0.52.0
GHSA-p77j-4mvh-x3m3  provider=github  severity=critical  google.golang.org/grpc constraint '<1.79.3' fix 1.79.3
```

`v0.46.0 < 0.52.0`. Every one of the seven applies to the version in the image.
None was withdrawn, re-scored, or re-ranged.

*(The first run of this query was made as `bunny`, found no database at
`/root/.cache/grype`, and printed "NO ROWS" for every advisory — an instrument
answering "I could not look" in the same words it uses for "there is nothing
there". The script now checks the exit status before summarising. It is the
fourth time this phase that a check has had to be taught the difference.)*

### 2.3 The matcher is not the problem

`route/crypto-control.py` lifts the four `x/crypto` and four `grpc` package
records **verbatim** out of the candidate's own SBOM, writes them into a minimal
SPDX document, and scans that. Result: 36 matches, including all seven
Criticals, each against `golang.org/x/crypto@v0.46.0` with `fix=['0.52.0']`.

So the database has the data, the package is in the image, and the matcher
matches it.

### 2.4 Isolated to one binary

`route/symbol-probe.sh` scans `/usr/bin/skopeo` two ways. Same grype, same
database, same file, same minute:

| route | distinct advisories | Critical |
|---|---:|---:|
| `grype file:/usr/bin/skopeo` | 12 | **0** |
| `grype sbom:<syft json of that same file>` | 37 | **7** |

And grype says why, on stderr of the second run only:

> `WARN go binary packages were found but none carry function symbols; go
> vulnerability matching falls back to module granularity and may report false
> positives. if scanning an SBOM, regenerate it with symbol capture enabled for
> more precise results.`

**The mechanism.** When grype can read the Go binary it matches at *function*
granularity and excludes advisories whose vulnerable functions are not linked
into that binary. Handed an SBOM without symbols it matches at *module*
granularity and reports every advisory against the module. The filesystem route
took the first path; the SBOM route and Phase 4's archive route took the second.

The two routes are not two attempts at the same measurement. They answer
different questions, and only one of them is the question the release gate has
been asking.

---

## 3. What the candidate's position actually is

Distinct advisories, `--only-fixed`, the same scope
`build/scripts/security-scan.sh` uses.

| route | granularity | distinct | Critical | High | Medium | Low | Unknown |
|---|---|---:|---:|---:|---:|---:|---:|
| Phase 4, `oci-archive`, beta `79bb99dd` | module | 114 | 8 | 39 | 61 | 5 | 1 |
| Phase 5, mounted filesystem, candidate | **function** | 56 | 1 | 31 | 19 | 5 | 0 |
| Phase 5, SBOM, candidate | module | 80 | **8** | 36 | 29 | 6 | 1 |

The disagreement between the two Phase 5 routes is strictly one-directional:
**24 advisories reported by the SBOM route only, 0 by the filesystem route
only.** All 24 are Go modules; 12 are Critical or High:

```
Critical  GHSA-5cgq-3rg8-m6cv   golang.org/x/crypto@v0.46.0
Critical  GHSA-89gr-r52h-f8rx   golang.org/x/crypto@v0.46.0
Critical  GHSA-f5wc-c3c7-36mc   golang.org/x/crypto@v0.46.0
Critical  GHSA-jppx-rxg9-jmrx   golang.org/x/crypto@v0.46.0
Critical  GHSA-rm3j-f69w-wqmq   golang.org/x/crypto@v0.46.0
Critical  GHSA-vgwf-h737-ff37   golang.org/x/crypto@v0.46.0
Critical  GHSA-x527-x647-q7gg   golang.org/x/crypto@v0.46.0
High      GHSA-q4h4-gmj2-qvw2   golang.org/x/crypto@v0.46.0
High      GHSA-w879-237q-wc7r   golang.org/x/crypto@v0.46.0
High      GO-2026-4918          golang.org/x/net@v0.48.0
High      GO-2026-6179          golang.org/x/mod@v0.20.0, v0.36.0
High      GO-2026-6180          golang.org/x/mod@v0.20.0, v0.36.0
```

**The Critical count is 8, unchanged from Phase 4.** The seven `x/crypto`
findings are neither fixed nor withdrawn. They are excluded by a scanner-side
reachability determination that the release gate never asked for and has no
record of.

### The like-for-like comparison

Module granularity, Go modules only, nineteen days apart — the only comparison
where nothing but time varies:

| | distinct | Critical | High | Medium | Low | Unknown |
|---|---:|---:|---:|---:|---:|---:|
| Phase 4 (beta, `oci-archive`) | 40 | 8 | 17 | 14 | 0 | 1 |
| Phase 5 (candidate, SBOM) | 45 | 8 | 18 | 17 | 1 | 1 |

Five new advisories in nineteen days, Criticals unchanged. That is the honest
statement of drift, and it is the one §17 asked for.

---

## 4. A second finding: Phase 4's scan never looked at an RPM

`evidence/vulnerability/beta-grype.json` — retained, 143 matches — breaks down
by artifact type as:

```
linux-kernel   74 distinct
go-module      40 distinct
```

and nothing else. **Zero RPM packages.** The same is true of
`base-grype.json` and `beta-minimised-grype.json`.

The Phase 5 scans of the candidate find, at both granularities, **26 distinct
RPM advisories (15 High, 8 Medium, 3 Low)** and 7 Python ones, sourced from
`/usr/share/rpm/rpmdb.sqlite` — a 61 MB database that is a real file in the
image, with `/usr/lib/sysimage/rpm` a symlink pointing at it
(`route/rpm-visibility.sh`).

So the release gate's stated position — "59 fixable findings, 8 Critical, 28
High, all inherited from the base image" — was measured by an instrument that
could not see a single distribution package: not glibc, not openssl, not
systemd. Whatever that number meant, it did not mean "the vulnerability position
of the image".

This is stated as measured, not diagnosed. Why the `oci-archive` route
catalogued no RPM is not established here; §7 records the scan that would
settle it.

---

## 5. A third finding: raw match counts are inflated by the deployment layout

The image carries an ostree repository, and its objects are hardlinks to the
files in `/usr`:

```
/usr/bin/podman                                      inode=95288 links=2 size=45220848
/sysroot/ostree/repo/objects/8c/c9b024….file         inode=95288 links=2 size=45220848
```

Same inode. So a filesystem scan catalogues every Go binary twice and reports
every finding against it twice: **44 of the 183 raw matches came in through an
ostree object path**. The SBOM route duplicates the same content for the same
reason — 238 raw matches over 80 distinct advisories.

Raw match counts are therefore not a measure of anything about this image.
Every count in this document is distinct advisories, and the summariser
(`route/scan-summary.py`) reports both so the gap stays visible.

---

## 6. What this does *not* change

**The blocking position is unchanged: 8 Critical, and the release gate stays
blocked.**

`release/vulnerability.py` permits a Critical to reach a non-blocking
disposition only through a completed, independent review reference. A scanner's
symbol analysis is a measurement, not an independent review, and §17 of the
Phase 5 brief is explicit: *do not mark security findings resolved without
evidence*. Grype's own warning frames the module-granularity result as the one
that "may report false positives" — which is to say the conservative one — and a
release gate is the place to be conservative.

Nothing here is a waiver, a downgrade, or a reduction in count. The Critical
findings stand exactly where Phase 4 left them.

**What it does change is the question for the independent reviewer.** §18 asks
for an external review of reachability, and until now the material handed over
would have been 24 reachability bundles asserting `installed-not-executed` on
the strength of an argument. There is now a measurement to put in front of them:
*grype's function-level analysis reports that the vulnerable symbols of these
seven advisories are not linked into `/usr/bin/skopeo`; confirm or refute.* That
is a far better question than the one the review package currently asks, and it
is the strongest argument yet available for the disposition Phase 4 wanted and
could not justify.

---

## 7. What is still open

1. **The `oci-archive` scan of this candidate**, by the release gate's own
   route, against the current database. It is the one measurement that puts
   Phase 4's method, Phase 5's database and Phase 5's artifact together, and it
   is the only way to say whether the missing RPM coverage is a property of the
   route or of that particular archive. The export is done — 2.96 GB at
   `sha256:6fd358bf06b7ecc13e4657bdab41c03d5fb46948bb9f2a6684b4284bef7d0cfc` —
   and the scan is queued behind the Phase 5 build.

2. **Which route the release gate should use.** `build/scripts/security-scan.sh`
   scans `oci-archive:` with `--only-fixed`, and if that route is the reason
   for the missing RPM coverage then the gate has been under-reporting since it
   was written. No change is proposed here on the strength of one archive; item
   1 decides it.

3. **Recording granularity in the gate's own output.** Two runs of the same
   gate, on the same image, with the same tool, can now legitimately differ by
   seven Critical findings depending on what they were pointed at. A result that
   does not say which granularity produced it is not interpretable, and neither
   `grype.json` nor `vulnerability-report.md` currently says.

---

## 8. Reproducing this

Everything below reads existing artifacts. None of it rebuilds the candidate.

| what | how |
|---|---|
| the candidate's package inventory | the SPDX SBOM, digest in `../sbom/retention-manifest.json` |
| the advisory ranges | `route/range-report.py` over `grype db search --vuln <id> -o json` |
| the matcher is not at fault | `route/crypto-control.py` → `route/crypto-control.spdx.json` |
| the mechanism, on one binary | `route/symbol-probe.sh` → `route/skopeo-{binary,sbom}-scan.json` |
| the candidate through its SBOM | `route/sbom-scan.sh` → `scan/candidate-sbom-fixed.json` |
| every count in this document | `route/final-numbers.py`, `route/type-breakdown.py` |
| the hardlink and the rpm database | `route/rpm-visibility.sh` |

The two stderr files are kept deliberately:
`scan/candidate-filesystem-fixed.err` has no symbol warning,
`scan/candidate-sbom-fixed.err` has it. That one-line difference is the whole
finding.
