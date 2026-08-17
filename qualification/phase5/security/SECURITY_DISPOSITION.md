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

## 2. Scope, stated first because it is the matrix's largest limitation

**This matrix is not about the Alpha Release Candidate.**

| | |
| --- | --- |
| Image | `localhost/bunny-os-beta:79bb99ddb39d` |
| Source commit | `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8` |
| Scanned | 2026-07-29T23:23:00Z, grype 0.116.1 |
| **The candidate** | **`e906a48793d74544b39c14cc3e35e0654f5311e2`** |

A re-scan of the candidate was attempted in Phase 5 and **failed**:

    failed to catalog: an error occurred attempting to resolve
    'localhost/bunny-os-beta:e906a48793d7': podman: unable to populate layer
    cache … : no space left on device

The image is present in the builder's store and grype's database is current
(built 2026-08-17T06:19:33Z, `valid`). What is absent is disk: the Windows host
volume has 8.6 GB free, and grype's layer cache filled `/tmp` while expanding a
6 GB image. The blocker is the same one that stops the Phase 5 build, and it is
recorded in `RELEASE_GATES.md` §4.

**The counts below must not be quoted as the candidate's.** Phase 4's own
figure for the candidate — 59 fixable findings, 8 Critical and 28 High — comes
from a `--only-fixed` scan and is a different measurement from this one.

---

## 3. The matrix

Full rows in `disposition-matrix.json`, regenerable with
`python qualification/phase5/security/build_disposition_matrix.py`.

| | Count |
| --- | ---: |
| Total findings | 37 |
| Critical | 8 |
| High | 16 |
| Medium | 13 |
| **Status `PENDING_REVIEW`** | **37** |
| With a bounded reachability package prepared for the reviewer | 24 |

Every finding, without exception:

* comes from the base image (`fromBaseImage: true`, 37 of 37)
* has **no network exposure** (`networkExposure: none`, 37 of 37)
* is **not waiver-eligible** (`waiverEligible: false`, 37 of 37)

By runtime reachability: **35 installed-not-executed**, 2 executed-by-default
(both `linux-kernel`, privilege level `kernel`).

By package, the concentration is stark: `golang.org/x/crypto` carries 13 of the
37, `github.com/containers/podman/v5` a further 6. Two thirds of the matrix is
a handful of Go modules linked into `podman`, `skopeo` and `bootc`.

### The Bunny impact column, and what it is made of

§17 asks for "Bunny impact". Every value in that column is read from a measured
field, never inferred. For example, `GHSA-5cgq-3rg8-m6cv`:

* **exploit prerequisites** — "A local user must invoke podman, skopeo, bootc
  or toolbox and drive it to the affected code path; no unit is enabled that
  reaches it automatically."
* **mitigation** — "`/etc/systemd/system` contains no podman or bootc symlink,
  `podman.socket` is not in `sockets.target.wants`, and
  `bootc-fetch-apply-updates.timer` is not enabled. Binaries are 0755
  root:root with no setuid bit. SELinux targeted policy is enforcing."

Those are checks that were run, with the evidence files named
(`evidence/reachability/beta-binaries.txt` and siblings). **They reduce
exposure. They do not dispose of the finding**, and this matrix does not let
them: the status stays `PENDING_REVIEW`.

### The owner column

§17 asks for an owner. Every row reads:

> unassigned — the project has one principal and the review must be independent
> of them

That is the honest entry. Intake *rejects any reviewer whose name or
organisation matches a project principal*, so the owner of these rows cannot be
the person who would otherwise be assigned them. Writing a name in that column
would be writing a name that intake would refuse.

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
