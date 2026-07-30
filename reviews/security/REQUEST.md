<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent security review — request

Bunny OS is a Fedora bootc-based desktop operating system. This request asks for
one thing above all others: a per-CVE determination of whether 24 Critical and
High vulnerability findings are reachable in a Bunny OS deployment.

Nothing in this repository can answer that question, and no amount of further
work here will change that. It is the only route by which any Critical finding
becomes non-blocking, and the code enforces that: `release/vulnerability.py` and
`release/cve.py` both reject a non-blocking Critical disposition that does not
reference a completed independent review.

## Exact scope

**In scope:**

1. **Per-CVE reachability of 24 Critical and High findings.** All 24 sit in Go
   modules vendored into the container stack that `fedora-bootc:44` installs. One
   review bundle per advisory is provided under
   `security/reachability/packages/<ADVISORY>/`, nine files each. This is the
   priority and the rest of the scope is secondary to it.
2. **The privileged broker** — `services/`. A D-Bus service running as root that
   exposes typed fixed backends to unprivileged clients. Specifically: whether
   the typed-backend model actually forecloses a generic exec path.
3. **The root update agent** and the bootc update trust chain.
4. **The installer secret channel** — how a disk passphrase reaches the
   installer without transiting a log, a shell argument or a world-readable file.
5. **The SELinux domains** shipped in `selinux/`.
6. **Phase 7 enrolment, policy and remote-administration boundaries** —
   `enterprise/`, `oem/`. None of these is operated; the review is of the design
   and implementation, not of a running service.

**Out of scope:**

- The encrypted-sync cryptography. That is a separate request
  (`reviews/cryptography/REQUEST.md`), because a cryptographic review and a
  systems security review are different specialisms.
- Accessibility. Separate request.
- Licensing and trademark. Separate request.
- Anything the project has not built. There is no hosted service, no fleet, and
  no manufactured device.

## Commit

- **Evidence baseline commit:** `80df25b09f6578276d18c8a82f15c47dd8959740`. Every
  measurement cited in the bundles was taken at this commit.
- **Base image:**
  `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`,
  created 2026-07-29T11:06:05Z.
- **Your scope commit:** the commit you are given when the engagement starts.
  Record it as `scopeCommit` in your review record. Intake rejects a review whose
  scope commit is not the commit being qualified — evidence does not transfer
  between commits, and neither does a review.

## Artifacts

| Artifact | What it is |
|---|---|
| `security/reachability/packages/<ADVISORY>/` | 24 bundles, 9 files each: summary, finding, installed package, source package, binary analysis, activation analysis, sandbox analysis, evidence manifest, review questions |
| `security/reachability/sources/ACQUISITION.md` | The exact commands to obtain each source, binary, debuginfo and debugsource RPM from Fedora infrastructure, with the verification each requires |
| `evidence/vulnerability/beta-grype.json` | The raw scan, grype 0.116.1 |
| `evidence/reachability/beta-facts.txt` | Unit enablement, socket definitions, `rpm --whatrequires` output |
| `evidence/reachability/beta-permissions.txt` | Modes and ownership of the carrier binaries |
| `evidence/reachability/beta-minimised-binaries.txt` | Installed NEVRAs after package minimisation |
| `SECURITY_REACHABILITY_REVIEW.md` | The bounded review that answered nine of ten questions |
| `docs/adr/ADR-027-base-image-security-decision.md` | Why the base is retained and the precise conditions that would reopen it |
| `docs/PRIVILEGED_BROKER.md`, `docs/THREAT_MODEL.md`, `docs/SECURITY_BASELINE.md` | Design documents |
| `SECURITY_REVIEW.md` | The project's own internal review. Read it as a statement of what the project believes, not as evidence. |

The image itself is not in the repository. `docs/BUILDING.md` builds it from the
pinned base digest; a Fedora host with podman and image-builder reproduces the
archive the scan was taken against.

## Threat model

Summarised from `docs/THREAT_MODEL.md`. The adversaries that matter here:

1. **A local unprivileged user** on a shared machine, attempting to reach root or
   another user's data. This is the adversary most of the 24 findings are
   relevant to, because the carrier binaries are mode 0755 with no setuid and any
   user can invoke them.
2. **A malicious or compromised Bunny plugin**, attempting to escape the typed
   broker backends into arbitrary execution.
3. **A network attacker** on the same LAN. Bunny exposes no listener by design;
   the review should test that claim rather than accept it.
4. **A compromised update source**, attempting to install an unsigned or
   downgraded deployment.
5. **A thief with the powered-off device**, against LUKS2 and the recovery-key
   flow.

Explicitly *not* in the model: a nation-state adversary with physical access and
unlimited time; a compromised Fedora build system (that is a supply-chain
question the reproducibility work addresses separately).

## Questions

Ordered by how much they matter to the release.

1. **For each of the 24 advisories: is the vulnerable code path compiled into
   the installed binary, and is it active or invocable?** Each bundle's
   `review-questions.md` breaks this into six sub-questions. Answer per advisory,
   not for the set — they are in five different modules across at least two
   binaries.
2. **Which installed binary carries each module?** The scan records an ostree
   object digest, not a path, because `fedora-bootc` ships an object store. Four
   distinct carrier objects account for all 24 findings. The project has not
   confirmed which of `/usr/sbin/podman`, `/usr/sbin/skopeo` or `/usr/sbin/bootc`
   each corresponds to, and has recorded `unknown` rather than guess.
3. **Is the `golang.org/x/text` finding's carrier the removed `toolbox` binary?**
   The one High finding whose carrier object matches the object the previous
   phase identified as toolbox — which package minimisation removed from the
   installed root, while the object survives in a lower base layer. If confirmed,
   that advisory's invocation analysis differs from the other 23.
4. **Does the typed-backend broker model actually foreclose a generic exec
   path?** The project asserts it does. This is the assertion whose failure would
   matter most.
5. **Is `CVE-2020-27815` a scanner artefact?** Reported against kernel
   `7.1.5-200.fc44.x86_64` with a stated fixed version of `4.9.249`. The project
   believes it is an artefact and has recorded it as `Unknown` rather than
   `Remediated`, because "almost certainly fine" is not evidence.
6. **Does SELinux targeted policy materially confine a rootless `podman`
   invocation?** If a finding is reachable, is the mitigation real or nominal?
7. **Does the installer secret channel leak the passphrase** into a log, a
   process argument, a journal field or a temporary file?
8. **Is the update trust chain sound** against a downgrade and against an
   unsigned deployment?

## Expected report format

Markdown or PDF, plus a machine-readable record conforming to
`security/reachability/schemas/independent-review-record.schema.json`.

The record must carry:

- `reviewId`, `reviewType: "security"`, `reviewerName`, `reviewerOrganisation`;
- `independenceDeclaration` — your own statement, at least a sentence;
- `scopeCommit` — the commit you were given;
- `scopeArtifacts` — what you actually reviewed;
- `findings[]` — each with `findingId`, `severity`, `summary`, `state`, and for a
  reachability determination, `advisoryIds` and `reachabilityConclusion`;
- `conclusion` — `pass`, `conditional` or `fail`;
- `reportDigest` — the SHA-256 of your report file;
- `signature` — a detached signature over `reportDigest`, by a key you publish
  independently of this repository.

Intake recomputes `reportDigest` from the file and rejects a mismatch. An
unsigned record is rejected: without a signature the report can be substituted
after delivery and the record still validates.

`reachabilityConclusion` must be one of `Not present`, `Present but
unreachable`, `Reachable but mitigated`, `Reachable and blocking`, `Unknown`.

## Severity model

Use `critical`, `high`, `medium`, `low`, `informational`.

- **critical** — remote or unprivileged-local path to root, or to another user's
  data, on a default installation.
- **high** — a privilege or data boundary crossed under conditions a normal user
  reaches without deliberate misconfiguration.
- **medium** — a boundary crossed only from an already-privileged position, or
  requiring configuration the project documents as unsupported.
- **low** — hardening gap with no demonstrated path.
- **informational** — observation, no security claim.

Rate what you find on its own terms. Do not adjust a severity because a package
came from the base image; the project's own tooling rejects that reduction, and
so should you.

## Expected independence statement

We need a statement in your own words covering:

- no employment, contract, consultancy, equity, or advisory relationship with
  ComradeArt or the Bunny OS project, other than this engagement;
- no authorship of any code, document or design under review;
- no undisclosed relationship with any party that benefits from a particular
  conclusion;
- that your conclusions are your own and were not directed, edited or
  pre-approved by the project.

`release/reviews.py` rejects any reviewer whose name or organisation matches a
project principal. The check is a floor, not a substitute for the statement.

## Confidentiality requirements

- The repository is source-available under GPL-3.0-or-later and Apache-2.0. The
  code is not confidential, and you may quote it freely.
- **Findings are embargoed until remediated or until 90 days from delivery,
  whichever is sooner.** After that, publish freely.
- Do not publish an unremediated Critical or High finding during the embargo.
- Coordinate a public disclosure timeline with the project via
  `SECURITY_POLICY.md`.
- There is no user data to protect: no Bunny OS installation exists outside the
  project's own test builds.

## Prohibited claims

Do not write, and the project will not accept:

- **"Certified"**, "approved", "compliant" or "endorsed" of any component. This
  review produces evidence, not a certification.
- **A reachability conclusion drawn from a symbol table alone.** Go's compiler
  inlines across package boundaries and its linker rewrites call graphs, so
  neither the presence nor the absence of a module-level name settles whether the
  vulnerable instructions were emitted. `release/cve.py` rejects a `Not present`
  conclusion whose only support is a symbol observation on a stripped or Go
  binary.
- **A conclusion about a version other than the installed one.** The installed
  NEVRAs are `podman-5.8.4-1.fc44.x86_64`, `skopeo-1.22.2-2.fc44.x86_64`,
  `bootc-1.16.4-1.fc44.x86_64`. An analysis of a different build establishes
  nothing about the shipped one, and intake rejects the mismatch.
- **"No issues found"** as a whole-system claim. Say what you looked at and what
  you did not.
- Any statement that the project is ready for a stable release, an OEM pilot, an
  enterprise pilot, or a hosted service. Those are gate decisions with many other
  inputs and this review is one of them.

`Unknown` is an acceptable and often correct answer. It remains blocking, which
is the current state — so concluding `Unknown` costs the project nothing it has
not already lost. A wrong `Not present` on a Critical finding would clear a
blocker that should not be cleared, and that is the outcome this request is most
concerned to avoid.
