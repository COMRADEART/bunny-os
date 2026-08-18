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
re-scan of `e906a48793d7` failed for want of disk: `grype podman:` hands the
image to stereoscope, which writes every layer out as a tarball and needs tens
of gigabytes against a 7.8 GB tmpfs and 7.9 GB free on the host volume.

It succeeded on the second attempt by a different route. `podman create` +
`podman mount` assembles the image's overlay **in place** and hands back a
merged directory; `grype dir:` then reads the RPM database and the filesystem
directly. Measured free space before, during and after: unchanged. **No copy,
no tarball, no disk.**

| | |
| --- | --- |
| Image | `localhost/bunny-os-beta:e906a48793d7` |
| Image ID | `6f3bbb9af38dae1636ff5c02dc79b07d3b09774bcacddc15308ae8e80bf3c8b2` |
| Candidate commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Scanner database | built 2026-08-17T06:19:33Z, `valid` |
| Scope | `--only-fixed`, the same scope as `build/scripts/security-scan.sh` |

Evidence: `scan/candidate-fixed.json`, `scan/image-id.txt`,
`scan/grype-version.txt`. Matrix: `candidate-disposition-matrix.json`,
regenerable with `build_candidate_matrix.py`.

### The counting, because it is where a reader will go wrong

The scan reports **183 matches**. That is **not 183 vulnerabilities.**

It is **56 distinct advisories**, each counted once per affected package.
`FEDORA-2026-c53019ed4f` alone accounts for **15** of them, all from the same
`rpmdb.sqlite` and all the same advisory. Five advisories account for 43
matches between them.

| | |
| --- | ---: |
| Raw matches | 183 |
| Distinct advisories | **56** |
| Distinct (advisory, package) pairs | 119 |

By artifact type the raw matches split 89 `rpm`, 85 `go-module`, 7 `python`,
2 `linux-kernel`.

**Every figure below counts distinct advisories**, because that is the unit an
independent reviewer dispositions. Quoting 183 would inflate the number more
than threefold, and 183 is the first number anyone re-running the scan will
see.

### Result

| Severity | Distinct advisories |
| --- | ---: |
| **Critical** | **1** |
| High | 31 |
| Medium | 19 |
| Low | 5 |
| **Total** | **56** |

The single Critical is `GHSA-p77j-4mvh-x3m3` in `google.golang.org/grpc
v1.72.2`, fixed upstream in 1.79.3 — a Go module linked into base-image
binaries, which is the same class as every other finding here.

### Against Phase 4's figure — a discrepancy, not a correction

Phase 4 reports **"59 fixable findings (8 Critical, 28 High)"**.

| | Total | Critical | High |
| --- | ---: | ---: | ---: |
| Phase 4 | 59 | 8 | 28 |
| Measured here | 56 | **1** | 31 |

The totals are close. **The Critical counts are not: 8 against 1.**

**This is recorded as a discrepancy to resolve, not as a correction of Phase
4.** Three things differ at once — the scanner database, the cataloguing method
(`dir:` against `oci-archive:`), and possibly what Phase 4 counted — and with
three variables moving, attributing the difference to any one of them would be
a guess. Resolving it takes a single `oci-archive:` scan of this image, which
takes disk this host does not have.

It matters more than an ordinary counting question, because **Critical is the
severity that cannot be dispositioned without an independent review**. Whether
the candidate carries eight of them or one changes what that review costs.

### One thing the scan does settle

The identical scan of a **different** Bunny build,
`localhost/bunny-os-beta:376acf0e076f` — different image ID, different commit —
returns **identical counts**: 183 raw, 2 Critical, 106 High, 70 Medium, 5 Low.

Two independently built images with the same vulnerability surface is exactly
what "every finding comes from the base image" predicts, and it is here
**demonstrated rather than asserted**. Nothing Bunny builds adds to this
surface.

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
