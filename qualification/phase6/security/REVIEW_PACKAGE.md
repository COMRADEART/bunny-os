# Independent security review package

**For an external reviewer. Self-contained and checkable.**

Everything asserted below is either a digest you can recompute or a measurement
you can re-derive with the commands given. Nothing here is a disposition: every
finding is `PENDING_REVIEW`, and it is your determination that changes that.

Verify this package's own integrity first:

    python qualification/phase6/security/verify_package.py

---

## 1. Artifact identity

| | |
| --- | --- |
| Build commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Image reference | `localhost/bunny-os-beta:e906a48793d7` |
| Image manifest digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Image version | `0.3.0-beta.e906a48793d7` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| OCI archive | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| Installation ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| Base image | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Builder image | `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` |
| Package snapshot | `fedora-44-beta-20260810-tts` |
| `SOURCE_DATE_EPOCH` | `1786986334` |
| Build log | `beta-build.log`, in the artifact directory |

All digests re-verified against the bytes on 2026-08-18; see
`../baseline/freeze.log`.

**Two caveats you should have up front.**

1. `repeatedBuildComparisonPerformed: false` for this artifact. The
   three-builder reproducibility result belongs to the commits measured for it,
   not to this one.
2. The upstream base tag `quay.io/fedora/fedora-bootc:44` **no longer resolves**
   to `sha256:1f08084a…`; it now resolves to `sha256:f51e9dca…`. Fedora rebuilds
   that tag frequently. The artifact's base is reconstructible only from the
   retained local copy, `localhost/bunny-os-retained-base:1f08084a…`.

---

## 2. Scanner provenance — read this before the counts

The same image, the same scanner binary, reports **8 Critical** or **1
Critical** depending on the route, and the difference is not noise.

| Route | Database | Distinct advisories | Critical |
| --- | --- | ---: | ---: |
| `oci-archive:` (binary-reading) | 2026-08-17 | 56 | **1** |
| `dir:` (binary-reading) | 2026-08-17 | 56 | **1** |
| `sbom:` (module granularity) | 2026-08-17 | 80 | **8** |
| `oci-archive:` | July feed | 114 | 8 |

Binary-reading routes match Go findings at **function** granularity, using the
database's `qualifiers.go_imports`. An SBOM carries a module and a version and
nothing about which packages were linked, so it matches at **module**
granularity.

**This package carries the conservative (module-granularity) inventory: 80
advisories, 8 Critical, 36 High.** A disposition should be argued against the
number that is hardest to argue against.

The July/August difference is a separate matter: the July feed had **no Fedora
44 advisory data**, so it reported zero rpm findings. Every August scan reports
26 distinct rpm advisories. That is a database coverage change, not a change in
the image.

---

## 3. Vulnerability inventory

Full machine-readable inventory:
`qualification/phase5/security/candidate-disposition-matrix.json` — 80 rows,
each carrying advisory id, severity, affected packages, fixed versions, artifact
type, and status.

| Severity | Distinct advisories |
| --- | ---: |
| Critical | 8 |
| High | 36 |
| Medium | 29 |
| Low | 6 |
| Unknown | 1 |
| **Total** | **80** |

All 80 are `PENDING_REVIEW`. The project's own tooling **refuses at parse time**
any non-blocking disposition of a Critical that does not reference a completed
independent review (`release/cve.py`, `release/vulnerability.py`), and
`build_disposition_matrix.py` has no code path that emits `ACCEPT` or
`NOT_APPLICABLE`. That refusal is not discipline; it is the absence of a
function.

---

## 4. Exposure measurement — the eight Criticals

§4 asks for a Bunny exposure hypothesis per finding and forbids claiming
`NOT_APPLICABLE` merely because Bunny does not intentionally invoke a component.
What follows is therefore **measurement**, not disposition: for each Critical,
whether the affected module version is present, and whether the specific
functions the advisory names are linked into the shipped binaries.

Instruments: `symbol_probe.py`, `exposure_probe.py`. Evidence:
`evidence/symbols.json`, `evidence/exposure.json`.

Only two binaries in the image carry any of these modules:
`/usr/bin/podman` (45 220 848 bytes) and `/usr/bin/skopeo` (26 035 008 bytes).
`/usr/sbin/podman` and `/usr/sbin/skopeo` are the same bytes.

### Embedded module versions

| Module | podman | skopeo | Fixed at |
| --- | --- | --- | --- |
| `golang.org/x/crypto` | **v0.53.0** | v0.46.0 | v0.52.0 |
| `google.golang.org/grpc` | **v1.72.2** | v1.79.3 | v1.73.0 |
| `golang.org/x/net` | v0.55.0 | v0.48.0 | varies |
| `golang.org/x/text` | v0.38.0 | v0.32.0 | varies |
| `golang.org/x/mod` | v0.36.0 | — | varies |

### Per-advisory measurement

| Advisory | Named import | podman: version / code | skopeo: version / code |
| --- | --- | --- | --- |
| GHSA-5cgq-3rg8-m6cv | `x/crypto/ssh/knownhosts` | v0.53.0 **fixed** / **present** (1/1 symbols) | v0.46.0 vuln / **absent** |
| GHSA-89gr-r52h-f8rx | `x/crypto/ssh` | v0.53.0 **fixed** / present (7/10) | v0.46.0 vuln / **absent** |
| GHSA-f5wc-c3c7-36mc | `x/crypto/ssh/agent` | v0.53.0 **fixed** / present (2/2) | v0.46.0 vuln / **absent** |
| GHSA-jppx-rxg9-jmrx | `x/crypto/ssh/agent` | v0.53.0 **fixed** / present (1/1) | v0.46.0 vuln / **absent** |
| GHSA-rm3j-f69w-wqmq | `x/crypto/ssh` | v0.53.0 **fixed** / present (17/21) | v0.46.0 vuln / **absent** |
| GHSA-vgwf-h737-ff37 | `x/crypto/ssh` | v0.53.0 **fixed** / present (9/23) | v0.46.0 vuln / **absent** |
| GHSA-x527-x647-q7gg | `x/crypto/ssh` | v0.53.0 **fixed** / **absent** (0/2) | v0.46.0 vuln / **absent** |
| **GHSA-p77j-4mvh-x3m3** | `google.golang.org/grpc` | **v1.72.2 VULNERABLE / present (3/3)** | v1.79.3 fixed / present |

**Seven of the eight fail one of the two tests on every binary, and they fail
different ones.** `podman` carries the `x/crypto` ssh code at a version where it
is already fixed; `skopeo` carries a vulnerable version with that code not
linked at all. No binary in the image is simultaneously on a vulnerable version
and carrying the affected code.

**One survives both.** `GHSA-p77j-4mvh-x3m3` — gRPC — is present in
`/usr/bin/podman` at **v1.72.2**, below the v1.73.0 fix, with all three named
symbols (`Server.Serve`, `Server.ServeHTTP`, `Server.handleStream`) linked.

This is exactly and only what the binary-reading scan reported: one Critical,
`GHSA-p77j-4mvh-x3m3`, located at `/usr/bin/podman`.

### The reachability question this leaves you

The named symbols are all **server-side** gRPC entry points. The reviewer's
question is therefore concrete rather than open-ended:

> Does any configuration Bunny ships cause `podman` to serve gRPC, and can any
> untrusted party reach it?

What the project can tell you, and what you should verify independently:

* Bunny **does** invoke `podman`. The Capsule runtime launches sandboxed
  applications through it (`capsules/`, `COMPANION_CAPSULE_INTEGRATION_REPORT.md`).
* `podman system service` is the gRPC/REST surface. Whether any Bunny unit
  starts it, and on what socket, is checkable in `systemd/` and in the image's
  unit set.
* The update path — the other consumer of container tooling — is **disabled**;
  see `UPDATE_TRUST_ARCHITECTURE_DECISION.md`.

**The project does not offer a disposition on this.** It is the one Critical
where both tests are failed, and it is the one that most needs an independent
determination.

### A correction you must read before trusting Phase 5's file

Phase 5 recorded that *neither* binary contains the `x/crypto/ssh` packages.
That is false for `podman`, and the probe that produced it could only ever have
answered "no" — a `strings … | grep -q` pipeline under `set -o pipefail`, where
`grep`'s early exit kills `strings` with `SIGPIPE` and `pipefail` turns 141 into
a failure. Reproduced with a control in `PIPEFAIL_CORRECTION.md`.

Phase 5's **conclusion** was right. Its **evidence** was not, and it had no
version data at all, so it could not have reached the podman answer.

---

## 5. Exposure measurement — the thirty-six High findings

Full rows in the inventory. Grouped by what decides them:

| Group | Findings | Measured position |
| --- | ---: | --- |
| Go modules in `podman` / `skopeo` (`x/net`, `x/text`, `x/mod`, buildkit, docker, selinux, fulcio, otel, grpc, podman itself) | 19 | Both binaries present; versions differ between them (see table above), so per-advisory the applicable binary must be identified. Not yet done per advisory. |
| rpm — `curl` / `libcurl` 8.18.0-7.fc44 | 6 | **installed**, confirmed by `rpm -q` |
| rpm — samba libs (`libldb`, `libsmbclient`, `libwbclient`, `samba-client-libs`, `samba-common`) 2:4.24.4-1.fc44 | 5 | **installed** |
| rpm — `sqlite-libs` 3.51.2-1.fc44 | 2 | **installed** |
| rpm — `fuse-overlayfs` 1.16-2.fc44 | 1 | **installed** |
| kernel 7.1.5-201.fc44 | 2 | **installed** |
| python — `protobuf` 3.19.6 | 2 | **present** at `/usr/lib/python3.14/site-packages/protobuf-3.19.6.dist-info` |

**Stated as a limitation rather than glossed:** the per-advisory version-and-symbol
analysis done for the eight Criticals has **not** been done for the nineteen Go
High findings. Given what it revealed about the Criticals — that podman and
skopeo carry different versions of the same modules, and that the module-level
inventory merges them — the same analysis is likely to change several of those
rows. It is named here as work outstanding, not offered as complete.

The image ships a full SSH client and server (`/usr/bin/ssh`, `/usr/sbin/sshd`,
`/usr/bin/ssh-agent`, `/usr/bin/scp`, `/usr/bin/sftp`). None of the Go
`x/crypto/ssh` findings apply to these — they are OpenSSH, a different
implementation — but their presence is relevant to the threat model and is
recorded so you do not have to discover it.

---

## 6. Why nothing here is dispositioned

An upstream fixed version exists for most findings. **This project cannot apply
it.** The packages are in the base image, not in `build/packages/`, and `bootc`
requires `podman` and `skopeo` while `rpm-ostree` requires `skopeo`. A base
rebuild was observed on 2026-07-29 without the counts moving, so "wait for
Fedora" is not a plan with a date on it. See
`docs/adr/ADR-027-base-image-security-decision.md`.

That is a statement about **which party can act**, not a claim that the findings
are somebody else's problem. §4 forbids that move and this package does not make
it.

**And it compounds with the update decision.** Updates are `UNSUPPORTED` for
this release class: an installed alpha receives **no security updates at all**,
and remediation requires reinstalling from a newer artifact. Your review should
weigh the findings on the assumption that **nothing will be patched in the
field**.

---

## 7. What you are being asked to return

Record: reviewer identity or review authority, review date, the artifact digest
reviewed, findings considered, conditions, and unresolved findings.

Result, exactly one of:

    APPROVED
    APPROVED_WITH_CONDITIONS
    BLOCKED
    MORE_EVIDENCE_REQUIRED

Intake: `operations/data/independent-reviews.json`, validated by
`python scripts/release.py validate-independent-reviews`. Intake **rejects** any
reviewer whose name or organisation matches a project principal, and binds the
record to a commit.

An internal re-scan is not an independent review, and this package does not
present one as such.

---

## 8. Additional matters for your attention

Not vulnerabilities in the inventory; design observations a reviewer should see
rather than find.

1. **The update manifest is parsed before it is authenticated.**
   `_verify_signature` is the **last** call in `_validate_manifest`. Schema,
   sequence, channel, architecture, contract version, versions, image reference,
   expiry, sizes and the anti-rollback comparison are all evaluated first.
   Bounded — the fetch is capped at 256 KiB and the parsing is pure Python — and
   unreachable in this release class. Measured as check D3 in
   `../update/evidence/refusal-qualification.json`.

2. **Update key rotation has no path.** Trust is conferred by a `.pem` inside
   the image, so adding, rotating or revoking a key requires shipping a new
   image — which is the mechanism that is unavailable. No key-signing key
   exists. Relevant if the project later moves to supporting updates.

3. **`bunny-update-agent status` reports `configured: true` on an image that can
   never update**, because the field is `CONFIG_PATH.exists()`. Not a
   vulnerability; a field that reads as capability and means file-presence.

4. **No production signing key exists.** The artifact is development-signed.
   All five keys in the register are refused for production by the project's own
   admission path, measured in
   `qualification/phase5/signing/SIGNING_CONFORMANCE.md`.

5. **The accessibility matrix carries two FAILs**, the only outright FAILs
   anywhere in the project's matrices. Out of scope for a security review, named
   because it is the only place a matrix records a defect rather than an absence.
