# Security disposition matrix

§17 asks for a per-finding disposition, and adds two rules that decide most of
it before any judgement is applied:

> Do not attempt to dismiss them as "inherited."
> Do not mark security findings resolved without evidence.

**Every row is `PENDING_REVIEW`, and that is the correct answer rather than an
evasion.** The reason is worth stating precisely, because "pending review" can
be a way of not doing work and here it is not.

---

## 1. Why nothing can be dispositioned yet

`release/cve.py` and `release/vulnerability.py` **reject at parse time** any
non-blocking disposition of a Critical finding that does not reference a
*completed independent review*. No independent review has been completed —
`operations/data/independent-reviews.json` holds no record.

So `ACCEPT` and `NOT_APPLICABLE` are not statuses a person could choose to
write here. They are refused by the code that reads the file. That refusal is
the project's existing implementation of §17's second rule, and Phase 5 did not
weaken it.

`FIX` is equally unavailable, and for a different reason that is worth reading:

> The packages are in the base image, not in `build/packages/`, so they cannot
> be updated or removed from this repository: `bootc` requires `podman` and
> `skopeo`, and `rpm-ostree` requires `skopeo`.

An upstream fixed version exists for these findings. The project cannot apply
it. That is not the same as "inherited, therefore not our problem" — §17
forbids that move and this document does not make it. It is a statement about
which party can act, and the answer is Fedora. A base rebuild was observed on
2026-07-29 without the counts moving, so "wait for Fedora" is not a plan with a
date on it (`docs/adr/ADR-027-base-image-security-decision.md`).

**The disposition function cannot return ACCEPT or NOT_APPLICABLE while no
review exists.** Not by discipline — `build_disposition_matrix.py` has no code
path that produces them. A function that could and merely does not is one
refactor from doing so.

---

## 2. The candidate, scanned

The first attempt at this matrix was built from the 2026-07-29 record, which is
a scan of `localhost/bunny-os-beta:79bb99ddb39d` — **not the candidate**. A
re-scan of `e906a48793d7` failed on its first try, was diagnosed as "no disk",
and that diagnosis was wrong twice over: the failure was against **/tmp, which
is tmpfs — RAM**, and "the host volume has 7.9 GB free" conflated Windows C:
with the ext4 volume this builder writes to. Measured since: 20 GiB written
inside WSL grows the VHDX by zero bytes. The disk was never the problem.

It then succeeded three ways, and **the three ways disagree by seven Critical
findings**. `SCAN_ROUTE_DISCREPANCY.md` is the full chain; this section states
the result and what the matrix is built from.

| | |
| --- | --- |
| Image | `localhost/bunny-os-beta:e906a48793d7` |
| Image ID | `6f3bbb9af38dae1636ff5c02dc79b07d3b09774bcacddc15308ae8e80bf3c8b2` |
| Candidate commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Scanner | grype 0.116.1, database built 2026-08-17T06:19:33Z, `valid` |
| Scope | `--only-fixed`, the same scope as `build/scripts/security-scan.sh` |

### The route decides the answer

| route | granularity | distinct | Critical | High | Medium | Low | Unknown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mounted filesystem (`grype dir:`) | function | 56 | 1 | 31 | 19 | 5 | 0 |
| **the candidate's own SBOM (`grype sbom:`)** | **module** | **80** | **8** | **36** | **29** | **6** | **1** |

Given a Go binary it can read, grype matches at **function** granularity and
excludes advisories whose vulnerable functions are not linked in. Given an SBOM
without symbols it matches at **module** granularity and reports them all,
warning on stderr that this "may report false positives" — which is to say it
is the conservative answer.

**This matrix is built from the module-granularity result**, because that is
the granularity the release gate has always used, the granularity Phase 4's
number is in, and the conservative one. Building it from the function-level
result would have silently disposed of seven Critical findings on a scanner's
say-so, which is exactly what §17 forbids and what `release/vulnerability.py`
rejects at parse time.

### The counting, because it is where a reader will go wrong

The SBOM scan reports **238 matches**. That is **not 238 vulnerabilities**, and
the inflation has two separate causes:

* one advisory is counted once per affected package — `FEDORA-2026-c53019ed4f`
  alone accounts for 15, all from the same `rpmdb.sqlite`;
* the image carries an ostree repository whose objects are **hardlinks** to the
  files in `/usr` — `/usr/bin/podman` and
  `/sysroot/ostree/repo/objects/8c/c9b024….file` are inode 95288 with a link
  count of 2 — so every Go binary is catalogued twice.

| | |
| --- | ---: |
| Raw matches (SBOM route) | 238 |
| Distinct advisories | **80** |
| Raw matches (filesystem route) | 183 |
| — of which arrived via an ostree object path | 44 |

**Every figure below counts distinct advisories**, because that is the unit an
independent reviewer dispositions.

### Result

| Severity | Distinct advisories |
| --- | ---: |
| **Critical** | **8** |
| High | 36 |
| Medium | 29 |
| Low | 6 |
| Unknown | 1 |
| **Total** | **80** |

The eight Criticals are seven advisories against `golang.org/x/crypto v0.46.0`
in `/usr/bin/skopeo` and one against `google.golang.org/grpc v1.72.2` in
`/usr/bin/podman` — Go modules linked into base-image binaries, which is the
same class as every other finding here.

### Against Phase 4's figure

Phase 4 reports **"59 fixable findings (8 Critical, 28 High)"** from an
`oci-archive:` scan of the beta image.

Like for like — module granularity, Go modules only, nineteen days apart, the
only comparison in which nothing but time varies:

| | distinct | Critical | High | Medium |
| --- | ---: | ---: | ---: | ---: |
| Phase 4 (beta, `oci-archive`) | 40 | 8 | 17 | 14 |
| Phase 5 (candidate, SBOM) | 45 | 8 | 18 | 17 |

**The Critical count is unchanged at 8.** The earlier Phase 5 figure of 1 was a
function-granularity measurement compared against a module-granularity
baseline; it is withdrawn as a statement about the candidate's position.

### What Phase 4's instrument could not see

`evidence/vulnerability/beta-grype.json` — retained, 143 matches — is 74
`linux-kernel` and 40 `go-module` findings, and **zero rpm**. So are
`base-grype.json` and `beta-minimised-grype.json`.

Both Phase 5 routes find **26 distinct RPM advisories (15 High, 8 Medium, 3
Low)** and 7 Python ones, sourced from `/usr/share/rpm/rpmdb.sqlite`, a 61 MB
file that is really present in the image.

So the position Phase 4 recorded was measured by an instrument with no
visibility into a single distribution package. Stated as measured: **why** the
archive route catalogued no RPM is not established here, and the `oci-archive:`
scan of this candidate that would settle it is queued behind the Phase 5 build.

### One thing the scan does settle

The filesystem-route scan of a **different** Bunny build,
`localhost/bunny-os-beta:376acf0e076f` — different image ID, different commit —
returns **identical counts**: 183 raw, 2 Critical, 106 High, 70 Medium, 5 Low.

Two independently built images with the same vulnerability surface is exactly
what "every finding comes from the base image" predicts, and it is here
**demonstrated rather than asserted**. Nothing Bunny builds adds to this
surface. The conclusion survives the route correction, because it compares one
route against itself.

---

## 3. The matrix

| | Count |
| --- | ---: |
| Distinct advisories | 56 |
| **Status `PENDING_REVIEW`** | **56** |

Every row, without exception, for the reasons in §1.

### The Bunny impact column

The candidate matrix records it as **not determined**, and that is deliberate.
The measured reachability evidence — which binaries carry the module, whether
any enabled unit reaches them, file modes, SELinux state — was derived for the
2026-07-29 advisory set and covers 24 of those advisories with a bounded
question package each. It has **not** been re-derived for these 56.

Carrying it across would have been the easy thing and the wrong one: an
advisory that did not exist when that evidence was gathered would inherit a
reachability answer nobody measured for it. The older matrix
(`disposition-matrix.json`) keeps its evidence and its scope; this one says
what it does not know.

### The owner column

Unchanged and unchangeable: *"unassigned — the project has one principal and
the review must be independent of them"*.

---

## 4. What would move these rows

One thing, and it is already prepared.

`reviews/security/REQUEST.md` and `INDEPENDENT_SECURITY_REVIEW_REQUEST.md`
specify a per-CVE reachability determination for the Critical and High
findings: 24 bundles of 9 files each, the raw scan, four evidence files, six
design documents, a threat model with 5 adversaries and 2 exclusions, and an
instruction to the reviewer **not to downgrade for base-image origin**. Nine of
each advisory's ten bounded questions already carry measured answers; the tenth
— is the vulnerable code path compiled into the installed binary, and active or
invocable — is the one that needs a specialist with the binaries in front of
them.

**The request is prepared and not sent. No reviewer has been identified and no
completion date exists.** Phase 5 did not change that, and could not: it is the
one gate whose definition excludes the people working on it.

### One thing Phase 5 should change and has not

The request is bound to evidence baseline `80df25b09f65`. Intake **rejects a
scope commit other than the candidate commit**, and the candidate is
`e906a487`. Sending it as written would produce a review whose record intake
then refuses.

It also predates App Capsules and the Trust prompt, so its six in-scope items do
not include the two boundaries a reviewer of *this* product would most want to
look at.

Rebinding needs the re-scan, which needs the disk. Recorded here as the next
action rather than performed, and it is a small one once the storage is back.
