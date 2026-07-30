# ADR-027: Base image security decision

- Status: **Accepted — retain `fedora-bootc:44`, and retain `NO-GO`**
- Date: 2026-07-29
- Supersedes nothing. Constrained by ADR-001 and ADR-002, which selected
  `fedora-bootc` deliberately.
- Related: `SECURITY_REACHABILITY_REVIEW.md`, `docs/STABLE_RELEASE_BLOCKERS.md`

## Context

The consumer-facing beta profile carries 59 fixable vulnerability findings — 8
Critical, 28 High, 23 Medium — and **every one of them comes from the base
image**. The beta profile adds none of its own. This was measured, not inferred:
the base was scanned alone and produced exactly the same counts.

The findings are overwhelmingly in Go modules vendored into `podman`, `skopeo`
and `bootc`: `golang.org/x/crypto` (7 of the 8 Criticals), `google.golang.org/grpc`,
`github.com/sigstore/fulcio`, `golang.org/x/net`, `golang.org/x/text`.

Three facts constrain every option below, and all three were tested rather than
assumed:

- `podman pull quay.io/fedora/fedora-bootc:44` now returns
  `sha256:fb71f099…`, a **fresh rebuild** created 2026-07-29T11:06:05Z. The
  previous analysis recorded `sha256:5cd90a82…`. Fedora did rebuild the base
  during this phase, **and the counts did not move.**
- `dnf check-update podman skopeo` inside the base returns nothing. Fedora 44
  ships podman 5.8.4-1, skopeo 1.22.2-2, containers-common 0.67.0-1, and those
  are current.
- `rpm -q --whatrequires podman` returns `bootc` and `toolbox`;
  `--whatrequires skopeo` returns `bootc` and `rpm-ostree`. **bootc requires
  both.** bootc is the update mechanism. Removing them removes the ability to
  update the system.

So the packages cannot be updated, cannot be removed, and rebasing lands on a
base with the same problem.

## Options evaluated

### Option A — Wait for a corrected Fedora 44 bootc base

| Dimension | Assessment |
|---|---|
| Vulnerability position | Unchanged today. The 2026-07-29 rebuild proves rebuilds happen without the Go modules moving. |
| bootc support | Native. |
| Kernel | 7.1.5-200.fc44, current. |
| GNOME compatibility | GNOME 50, already integrated. |
| SELinux | targeted policy, already integrated and enforcing. |
| image-builder support | Native; osbuild 185 / image-builder 76.0.0 in use. |
| Driver support | Fedora's, which is the reason ADR-001 chose it. |
| Secure Boot | shim-x64 + grub2-efi-x64 already in the package set. |
| Update architecture | bootc, already implemented and exercised. |
| Rollback | bootc deployments, already implemented. |
| Recovery | Existing recovery profile builds. |
| Package availability | Full Fedora archive. |
| Migration burden | **None.** |
| Long-term support | Fedora 44 lifecycle; a release-version bump is a separate decision. |
| Licence impact | None. |
| Hardware compatibility | Unchanged, and still unqualified for a different reason. |

*Cost:* unknown duration. The position may worsen before it improves — the
developer profile already moved from 59 to 95 findings under measurement.

### Option B — Move to a newer supported Fedora bootc base

There is no newer Fedora bootc base to move to. Fedora 45 does not exist as a
bootc base at the time of writing, and moving to a pre-release base would trade
a known vulnerability position for an unknown one plus a migration. Every
dimension in the table above would need re-qualification from zero, and the
project has not qualified the current base yet.

*Assessment:* not available, and would not help if it were.

### Option C — Change to another image-managed Linux base

The realistic candidates are other bootc-capable bases or an entirely different
image-managed system.

| Dimension | Assessment |
|---|---|
| Vulnerability position | Unknown, and would need the same per-CVE work to establish. Any base that runs bootc needs a container runtime and inherits the same Go supply chain. |
| bootc support | Non-Fedora bases largely do not ship bootc. Losing it means rewriting the update, rollback and recovery architecture. |
| Kernel | Would change; the driver and firmware matrix restarts. |
| GNOME compatibility | Varies; GNOME 50 integration is Fedora-tuned. |
| SELinux | Several candidates use AppArmor or nothing. The broker's confinement argument assumes SELinux. |
| image-builder support | osbuild is Fedora-centric. |
| Driver support | Would regress on the hardware nobody has tested yet. |
| Secure Boot | Shim signing differs per distribution and is a months-long process for a new vendor. |
| Update architecture | Rewrite. |
| Rollback | Rewrite. |
| Recovery | Rewrite. |
| Package availability | Varies. |
| Migration burden | **Very high.** Phases 1–7 assume this base. |
| Long-term support | Would need a new assessment. |
| Licence impact | Possible; some bases carry redistribution terms `build/license-policy.json` already refuses. |
| Hardware compatibility | Restarts. |

*Assessment:* a distribution change to escape vendored-Go CVEs in a container
runtime that every bootc-style base needs is trading a measured problem for an
unmeasured one, at the cost of most of the work to date.

## Decision

**Retain `quay.io/fedora/fedora-bootc:44`, pinned by digest, and retain
`NO-GO`.**

The base is not being retained because the vulnerability position is
acceptable. It is not acceptable. It is being retained because none of the
three options improves it, and two of them make everything else worse.

The vulnerability blocker stays open and continues to block
`gate-stable-release`. It is not waived, not downgraded, and not reclassified.

## The waiting condition, precisely

This decision is revisited when **any** of the following becomes true. Each is
checkable without judgement:

1. `podman pull quay.io/fedora/fedora-bootc:44` resolves to a digest other than
   `sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`
   **and** a rescan reports fewer than 8 Critical fixable findings.
2. Fedora ships a `podman` or `skopeo` build whose vendored `golang.org/x/crypto`
   is at or above 0.52.0 and whose `google.golang.org/grpc` is at or above
   1.79.3. Checkable with `dnf check-update` inside the base, or by scanning it.
3. An independent security review, delivered and recorded in
   `operations/data/independent-reviews.json`, determines per CVE that specific
   Critical findings are not reachable in a Bunny OS deployment. This is the only
   route by which a Critical becomes non-blocking, and
   `release/vulnerability.py` enforces that it requires such a review.
4. A Fedora bootc base for a newer release exists, is supported, and passes the
   fifteen-dimension evaluation above.

Until one of those holds, the correct engineering action is *not* to change the
base. It is to close the blockers that are actually within reach — hardware,
recovery media, reviews, a second builder — none of which this decision affects.

## Consequences

- `gate-stable-release` continues to report NO-GO on `vulnerability-position`.
- No Critical finding is waived. `docs/STABLE_RELEASE_BLOCKERS.md` permits a
  narrow waiver only for a High finding on an explicitly unsupported
  configuration, and 8 Criticals are outside what that clause allows.
- Package minimisation was performed anyway, for its own sake, and is recorded
  in `docs/PACKAGE_MINIMISATION.md`. It removed `toolbox` and changed no scan
  number, which is the honest outcome and is why reducing a scan score is a
  prohibited motive for removal.
- The base image digest is pinned in every build that produces evidence, so the
  position is reproducible and the waiting condition is testable.
