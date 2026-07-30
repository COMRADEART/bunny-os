# Security reachability review

Date: 2026-07-29. Scope: the 24 unique Critical and High fixable findings in the
consumer-facing beta profile, none of which has an available fix.

**Result: all 24 remain `Unknown`, and `Unknown` is blocking.**

That is the honest outcome of a bounded review, and it is worth being precise
about why, because nine of the ten questions *were* answered with measured
evidence. The review did not fail for want of effort. It failed on one question
that cannot be answered without work this phase did not scope.

## Method

Ten questions per finding, fixed by the release brief. Every answer cites
evidence gathered by running something against the built beta image, not by
reading source. `release/reachability.py` refuses an answer without evidence and
refuses the conclusion "not reachable" while any answer is `unknown`.

The evidence files are `evidence/reachability/beta-binaries.txt`,
`beta-facts.txt` and `beta-permissions.txt`.

## What was measured

All 24 findings sit in Go modules vendored into the same three binaries, so the
answers are common to the set.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Is the vulnerable binary installed? | **yes** | `/usr/sbin/podman` 45,220,848 B; `/usr/sbin/skopeo` 26,035,008 B; `/usr/sbin/bootc` 17,397,824 B |
| 2 | Does it run by default? | **no** | `find /etc/systemd -name '*podman*' -o -name '*bootc*'` returns nothing; no preset enables either |
| 3 | Does it listen on a socket? | **no** | `podman.socket` is a unix socket at `%t/podman/podman.sock` and is absent from `sockets.target.wants` |
| 4 | Can an unprivileged user invoke it? | **yes** | mode 0755 root:root, no setuid; rootless invocation is possible |
| 5 | Can Bunny or a plugin invoke it? | **no** | the broker exposes typed fixed backends and has no generic exec path; no backend invokes a container runtime |
| 6 | Does sandboxing limit exposure? | **yes** | `selinux-policy-targeted` enforcing; Bunny units carry systemd sandboxing |
| 7 | **Is the vulnerable code path compiled in and active?** | **unknown** | **not determined** |
| 8 | Can the package be removed? | **no** | `rpm -q --whatrequires podman` → `bootc`, `toolbox`; `--whatrequires skopeo` → `bootc`, `rpm-ostree` |
| 9 | Can the functionality be isolated? | **no** | bootc uses the same libraries in-process to fetch and stage updates |
| 10 | Does a systemd or SELinux control reduce exposure? | **yes** | no enabled unit reaches the code automatically; SELinux confines a rootless invocation |

## Why question 7 is unresolved

Answering it means determining, per CVE, whether the specific vulnerable
function inside a vendored module is linked into a 45 MB stripped Go binary and
reachable from any entry point that binary exposes. Go's linker performs dead
code elimination, so the presence of a module in the build graph does not imply
the vulnerable function survived into the binary — and its absence from a symbol
table does not prove it was not inlined.

Doing this properly is per-CVE symbol and call-graph analysis. It is exactly the
kind of work an independent security review exists to do, and it is the first
explicit question in `reviews/security/REVIEW_PACKAGE.md`.

Guessing at it would be worse than leaving it open. A wrong "not reachable"
here would clear 8 Critical findings on the strength of an assumption.

## Outcomes

| Outcome | Count | Advisories |
|---|---|---|
| Remediated | 0 | — |
| Not reachable with evidence | 0 | — |
| Reachable but mitigated | 0 | — |
| Waiver candidate | 0 | — |
| Blocking | 0 | — |
| **Unknown** | **24** | all |

`Unknown` remains blocking, so the practical effect is identical to `Blocking`.
The distinction is kept because it records *what kind* of work would resolve it:
`Blocking` would mean "we know it is reachable", `Unknown` means "we do not
know, and here is precisely what we do not know".

## The one finding that is probably a scanner artifact

`CVE-2020-27815` is reported against `linux-kernel 7.1.5-200.fc44.x86_64` with a
fixed version of `4.9.249`. A 2020 JFS bug, with a "fix" in a stable series six
major versions behind what is installed. Grype's kernel classifier compares
against upstream stable series and is unreliable across major versions.

It is recorded as `Unknown` rather than `Remediated` because the remediation
path is "confirm against the Fedora kernel changelog" and nobody has. Being
almost certainly fine is not evidence.

## What would change this

1. **An independent security review** answering question 7 per CVE. This is the
   only route by which a Critical becomes non-blocking, and
   `release/vulnerability.py` enforces that: a Critical with a non-blocking
   disposition and no completed independent review reference is rejected at
   parse time.
2. **Fedora rebuilding the container stack** against patched Go modules, which
   makes the question moot. See `docs/adr/ADR-027-base-image-security-decision.md`
   for the precise waiting condition.

## What was tried and did not help

- **Rebasing.** The base was rebuilt by Fedora during this phase — a genuinely
  new digest, `sha256:fb71f099…` — and the counts did not move.
- **Updating the packages.** `dnf check-update podman skopeo` returns nothing.
- **Removing the packages.** `bootc` requires both. Removing them removes the
  update mechanism.
- **Minimisation.** `toolbox` was removed. It carried none of the 24 and the
  count did not move, which is documented in `docs/PACKAGE_MINIMISATION.md` as
  the reason "reduce the scan count" is a prohibited motive.

## Standing conclusion

No waiver was created. No severity was reduced. The vulnerability blocker stands
and `gate-stable-release` reports NO-GO on it.

The value of this review is not that it cleared anything. It is that it narrowed
an unbounded "59 findings, unclear exposure" into one specific, answerable
question about 24 findings, assigned to a party who can actually answer it.
