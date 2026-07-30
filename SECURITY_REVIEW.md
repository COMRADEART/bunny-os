# Bunny OS Phase 1 security review

## Current security position — 2026-07-30

**This document, and every other security review in this repository, is
internal.** `release/reviews.py` refuses to record any of it as an independent
review, and that refusal is correct. Read what follows as a statement of what the
project believes, not as evidence.

### The vulnerability position blocks, and is unchanged

| Scanned | Fixable | Critical | High | Medium |
|---|---|---|---|---|
| `fedora-bootc:44` base alone | 59 | 8 | 28 | 23 |
| Bunny OS beta profile | 59 | 8 | 28 | 23 |
| Bunny OS beta, after minimisation | 59 | 8 | 28 | 23 |

Deduplicated to 24 unique Critical/High pairs, **all dispositioned `Unknown`**.
`Unknown` blocks.

Every finding comes from the base image; the beta profile adds none. Package
minimisation removed `toolbox` and **changed no scan number** — no claim is made
that it reduced security risk.

### Nine of ten reachability questions are answered

Measured against the built beta image: the carrier binaries are installed at
`/usr/sbin`, mode 0755, no setuid; **no podman or bootc unit is enabled**;
`podman.socket` is a unix socket absent from `sockets.target.wants`; nothing in
Bunny invokes a container runtime; SELinux is enforcing; and **the packages cannot
be removed** because `bootc` requires podman and skopeo and `rpm-ostree` requires
skopeo.

The tenth question — *is the vulnerable code path compiled into the installed binary
and active or invocable?* — is unresolved. It needs the binary, its debuginfo, and
the advisory's own description of the vulnerable function.

### What the qualification evidence closure measured that was new

All 24 findings are carried by **exactly four ostree objects**:

| Carrier | Advisories | Modules |
|---|---|---|
| `…8fbfb47329…` | 15 | x/crypto, selinux, fulcio, docker, x/net |
| `…8cc9b0248b…` | 7 | buildkit, podman/v5, grpc, otel |
| `…755cc7cfe2…` | 1 | x/text |
| `…eacf5a37b7…` | 1 | linux-kernel |

The single-advisory carrier `…755cc7cfe2…` is the object previously identified as
**`toolbox`**, which minimisation removed. If confirmed, `GO-2026-5970` has no
installed executable to invoke. It remains `Unknown`: the attribution is not
confirmed, and question 7 is unanswered either way.

Twenty-four independent questions became four binaries to identify and two Go
binaries to analyse.

### The rule that stops this being answered badly

`release/cve.py` refuses a `Not present` conclusion drawn from a symbol observation
alone, for **every** combination of stripped state and language — including an
unstripped C binary, because a file-static or inlined function is absent from that
table too. For Go the refusal states why: the compiler inlines across package
boundaries and the linker rewrites call graphs.

A `Not present` conclusion additionally requires the source and binary versions to
match exactly, the build configuration to be recorded, a mapping from function to
binary, and a reviewer. A **Critical** finding additionally requires a completed
independent review *and* a reviewer drawn from the delivered-review set — a reference
to somebody else's review does not make this analysis independent.

### No security control was weakened, and one was added

- No waiver was created. No severity was reduced. No `Unknown` was converted.
- `gate-stable-release` reports `NO-GO` on `vulnerability-position`.
- The vulnerability gate now consults **both** the per-finding disposition and the
  per-CVE binary analysis. A clear position with no analysis behind it was previously
  possible and is not any more.
- **A numeric scanner score cannot replace a per-finding disposition.** There is no
  field in the model that accepts one, and a test asserts the word "score" appears
  nowhere in the aggregate output.

### What an independent security review would do

`reviews/security/REQUEST.md` is prepared and has not been sent. It is the only route
by which any Critical finding becomes non-blocking, and the code enforces that at
parse time.

See `SECURITY_REACHABILITY_REVIEW.md`, `CVE_BINARY_ANALYSIS_REPORT.md`,
`CVE_REACHABILITY_DISPOSITION_REPORT.md`, and
`docs/adr/ADR-027-base-image-security-decision.md`.

---

## Phase 1 review outcome (2026-07-28)

Architecture and host-tested controls are suitable for a developer-image validation attempt. Consumer/beta release is **not approved**.

## Strengths

- Linux/systemd/SELinux remain authoritative; no new kernel, driver stack, root shell, passwordless sudo, TCP broker, or Bunny privileged group.
- Broker obtains kernel peer credentials before parsing, rebinds PID/start/UID, rejects service UIDs, requires active-session Polkit for mutation, and exposes only typed fixed backends.
- Broker service has empty capabilities, no IP, strict filesystem/home/proc/device/namespace/syscall controls, fixed environment, restart limits, cancellation/timeouts, and journald metadata-only audit.
- Update metadata has signature/key revocation, expiry, monotonic rollback protection, channel/arch/contract/Bunny/repository/digest/space checks. Developer updates and telemetry are disabled.
- firewalld drops unsolicited inbound, app/model server policy is loopback, SSH is disabled, support bundle is local/redacted/retained, and private signing keys are excluded.

## Open findings

| Severity | Finding | Required closure |
|---|---|---|
| Blocker | No image/runtime/VM evidence | full KVM image, negative, listener, egress, rollback, recovery, and AVC suite |
| High | Registry signature policy and release key ceremony are not provisioned | enforce signed OCI policy; demonstrate unsigned/malicious image rejection and rotation/revocation |
| High | Root Python broker/update code has only local review and host mocks | Linux adversarial integration, cross-user, PID-race, fuzz, symlink, cancellation and external review |
| High | Disk/Secure Boot chain is unqualified | Secure Boot positive/negative/update/rollback tests; LUKS2 installer validation |
| Medium | Bunny SELinux domains are compile-only and not installed | collect AVCs, minimize allows, enforce domains for broker/updater/Core/app/plugin/model |
| Medium | Recovery is an in-deployment target/QCOW2 definition | signed independent media, safe-graphics, backup/restore traversal/ownership tests |
| Medium | Fedora repositories are not snapshot-pinned and repeated builds did not run | pinned metadata, two clean builds, semantic and artifact comparison |
| Medium | Upstream Bunny Linux artifact is absent | signed manifest/hash/mode/install/update/rollback qualification |

Static tests found no broker `shell=True`, network listener, eval/exec, inbound firewall opening, private key file, world-writable tmpfiles path, or enabled telemetry default in the owned sources. This is not a binary/image secret scan.

## Phase 2 addendum

Bunny Shell adds no privileged service or network listener. Its fixed GNOME extension launch table, strict desktop-entry parser, typed intent boundary, metadata-only approved-root search, non-executing terminal proposal, credential-free workspace settings, private Core projection, lock-screen redaction, default-off telemetry/clipboard history, resource-limited user units, and Safe Shell passed host tests. It cannot grant approvals or bypass the broker.

Runtime review is still blocked by the missing image, signed Bunny artifact, GNOME 50/portal/systemd/SELinux execution, and cross-user/adversarial VM evidence. `SHELL_SECURITY_REVIEW.md` is authoritative for Phase 2 findings. Release approval remains denied.

## Phase 3 addendum

Phase 3 adds strict typed installer plans, protected primary-user secrets, disk identity binding, installation-media/read-only/mounted/complex-target blockers, two-step disk-specific erase confirmation, fixed `lsblk`, serial/UUID redaction, simulation-only fail-closed execution, LUKS2 fallback/recovery policy, structured log redaction, signed media/hash/path validation, conservative driver/remotes, and first-run privacy defaults. Sixty host tests cover the new layer.

No production Anaconda adapter, kernel peer-credential service, real disk, image, encrypted boot, Secure Boot, TPM, VM, UI, or supply-chain test ran. The external media manifest is not proven embedded into an ISO. These are Blocker/High findings in `INSTALLER_SECURITY_REVIEW.md`; beta/release approval remains denied.

## Phase 5 addendum

Phase 5 adds pre-storage redaction/user-content exclusion, strict imported fields, source preservation, no automatic severity/closure/merge, component-scoped failure matching, irreversible installer journaling, fail-closed update routes, hash-only preservation manifests, physical-evidence hardware promotion, non-identifying crash metadata, alert-only automation, repository-private-key rejection, complete signed-candidate requirements, and mandatory nine-party approval.

No Phase 4/public-beta dataset, candidate, signed media/update, migration, multi-user, traffic, diagnostic, accessibility, recovery, supply-chain, soak, or hardware evidence exists. `STABLE_CANDIDATE_SECURITY_REVIEW.md` remains `BLOCKED / NO-GO`; stable publication is denied.

## Phase 7 preflight addendum

The Phase 7 entry gate is denied by the same five protected Blocker codes and 31
missing or pending evidence/approval entries. No OEM, enterprise, fleet, tenant,
remote-wipe, or sync trust boundary was implemented, so no Phase 7 security
approval is claimed. Adding those attack surfaces before stable signing,
rollback, recovery, encryption, runtime isolation, and supply-chain evidence
would be unsafe. `docs/PHASE_7_BASELINE.md` is the current disposition.

## Phase 7 remediation security addendum

Real image execution found and fixed a health-service sandbox mismatch:
`ProtectSystem=strict` allowed `/var/lib/bunny-os/health` but denied the
separate `/var/lib/bunny` state boundary exercised by the health probe. The
unit now grants only those two explicit writable paths, and the VM gate requires
the service to finish successfully in addition to reaching a normal target.
Installed-path systemd verification also found and fixed ignored start-limit
directives and an unsupported executable-condition name; the corrected system
and user units verify cleanly in the beta image fixture.

The repaired release-mode license scan passed the 6,077-record beta SPDX with
zero unresolved or prohibited markers while recording 306 provenance-covered
`NOASSERTION` records. The Grype gate did not pass: 8 Critical and 28 High
fixable matches remain, primarily embedded in Fedora's bootc-required Podman and
Skopeo packages, plus the kernel classifier finding. These are neither waived
nor converted to PASS. A reviewed Fedora package update/rebase or equivalent
patched supply-chain input is required before release consideration.

## Phase 7 security review summary

Twelve separate assessments are recorded in `PHASE_7_SECURITY_REVIEW.md`: OEM supply chain, factory provisioning, device identity, enterprise enrolment, policy agent, fleet service, enterprise console, encrypted sync, device pairing, account recovery, remote wipe, and air-gapped management. Companion reviews: `FACTORY_PROVISIONING_SECURITY_REVIEW.md`, `FLEET_SECURITY_REVIEW.md`, `ENCRYPTED_SYNC_SECURITY_REVIEW.md`, `MULTITENANCY_TEST_REPORT.md`.

No unresolved Blocker or Critical issue exists in Phase 7 source. Three Minor defects were found and fixed during implementation, each caught by a new test rather than by inspection: an OEM key-namespace collision check that could never fire, a policy-domain validator registered with the wrong arity, and two privacy refusals preempted by a generic unknown-field check so the message misrepresented the reason for rejection.

Three Major limitations remain open and are recorded in `KNOWN_LIMITATIONS.md`: the policy agent has no privileged transport because the existing broker refuses system UIDs and requires an active logind session; the settings layer has no organisation scope so resolved policy cannot yet change a running desktop; and factory finalisation evaluates a supplied record rather than inspecting the device.

The structural properties worth noting are those that make a compromised control plane survivable. Update signature verification is not expressible as a policy or a ring setting, so a fully compromised fleet server cannot install arbitrary software. There is no generic remote shell and no operation accepts a command or argv. A failed fleet update that lost rollback is an unrepresentable report rather than an incident to discover. Signing authorities are separated into five disjoint namespaces validated at parse time, so a fleet key cannot cause an OS image to be installed.

The inherited position is unchanged and independently blocking: 8 Critical and 28 High fixable vulnerability findings in the Fedora bootc-required dependency set, neither waived nor converted to PASS, plus the five stable-release blocker codes and 31 missing evidence entries. No Phase 7 pilot may begin.

## 2026-07-29 vulnerability position: measured, and it is upstream

The 59 findings previously attributed vaguely to "the Fedora kernel and bootc-required Podman/Skopeo/Toolbox" were measured directly rather than inferred.

| Scanned | Fixable | Critical | High | Medium |
|---|---|---|---|---|
| `quay.io/fedora/fedora-bootc:44` base image alone | 59 | 8 | 28 | 23 |
| Bunny OS developer profile | 95 | 19 | 43 | 33 |

**Every one of the 59 comes from the base image.** That is exactly the number the earlier beta report cited, which confirms the beta profile adds none of its own. The developer profile's extra 36 come from `build/packages/developer.txt` — podman, buildah, skopeo, toolbox — whose own header already states these are "intentionally absent from future consumer images".

So the consumer-facing position is 59, and all of it is inherited.

### It cannot be fixed from this repository today

Three routes were tested, not assumed:

- **Rebase.** `podman pull quay.io/fedora/fedora-bootc:44` returns the same digest `sha256:5cd90a82…`. There is no fresher base to move to.
- **Layer updates.** `dnf check-update podman skopeo` inside the base returns nothing. Fedora 44 ships podman 5.8.4-1, skopeo 1.22.2-2 and containers-common 0.67.0-1, and those are current.
- **Remove the packages.** They are in the base image, not in our package lists, so removing them from `developer.txt` cannot help a consumer profile that never included them.

The findings are overwhelmingly in Go modules vendored into those binaries — `golang.org/x/crypto` (9 of the base's Critical/High), podman itself, sigstore/fulcio, grpc, `golang.org/x/net`, `golang.org/x/text`. Fedora has not yet rebuilt them against patched modules.

### What this changes

`NEXT_PHASE.md` previously listed "consume a reviewed Fedora update" as the first action. That action is not available. The real options are:

1. **Wait for Fedora** to rebuild the container stack. No engineering, unknown duration, and the position may worsen before it improves.
2. **Change the base** to one without the container toolchain. A significant architecture change: `ADR-001` and `ADR-002` select `fedora-bootc` deliberately, and bootc needs container tooling to function.
3. **Waive with review**, per finding, recording why each is not reachable in a Bunny OS deployment. Several plausibly are not — a CVE in podman's registry client is not reachable on a device that never runs podman — but that argument has to be made and reviewed one CVE at a time, not asserted in bulk.

Option 3 is the only one the project can act on unilaterally, and `docs/STABLE_RELEASE_BLOCKERS.md` permits it only for "a narrowly scoped High issue" on "an explicitly unsupported configuration". Nineteen Critical findings are outside what that clause allows.

**No waiver was created and the position remains a blocker.** The value of this measurement is that it identifies who can actually fix it, which is not us.

## 2026-07-29 signing path exercised with development keys

Previously every signature-related check in this repository was a source-text assertion. The path has now been run.

An Ed25519 development keypair was generated **outside the repository** at `~/.bunny-dev-keys/`, and used against the real 2 GB OCI archive:

| Check | Result |
|---|---|
| `openssl pkeyutl -sign -rawin` over the artifact | signed |
| `openssl pkeyutl -verify -pubin -rawin` | "Signature Verified Successfully" |
| Same signature against a truncated copy | rejected, `EVP_DigestVerify` failure |
| `sign-stable-rc.py` with a key inside `build/keys/` | refused: "private signing keys must not be stored in the repository" |
| `sign-stable-rc.py` with an external key, no candidate | refused: "missing stable candidate manifest" |
| `phase5.py candidate-gate` | BLOCKED: manifest absent |

The key-hygiene control is therefore enforced in practice and not only asserted by a test that greps the source.

**This is not release signing evidence.** These are development keys, there has been no key ceremony, there is still only one potential signer, and no twelve-artifact candidate exists to sign — that needs the live ISO, beta raw and recovery ISO, none of which have been built. `signature_verification` remains not-run in both tracks.

## 2026-07-30 release blocker closure security addendum

### The base image was rebuilt during this phase, and the position did not move

`quay.io/fedora/fedora-bootc:44` now resolves to `sha256:fb71f099…`, created
2026-07-29T11:06:05Z. The previous measurement recorded `sha256:5cd90a82…`.
Fedora genuinely rebuilt the base — and the scan is identical: 59 fixable, 8
Critical, 28 High, 23 Medium.

That single observation changes how "wait for Fedora" should be read. It is no
longer a plan with an implied date; a rebuild has now been watched to land
without moving the vulnerability position. `docs/adr/ADR-027-base-image-security-decision.md`
records the decision to retain the base regardless, with four checkable
conditions that would reopen it.

### The reachability review narrowed the problem to one question

`SECURITY_REACHABILITY_REVIEW.md` answered nine of the ten mandated questions
with evidence measured on the built beta image:

- podman, skopeo and bootc are installed at `/usr/sbin`, mode 0755, **no setuid**;
- **no podman or bootc unit is enabled** — `/etc/systemd` contains no symlink for
  either and no preset enables them;
- `podman.socket` is a unix socket at `%t/podman/podman.sock` and is **not** in
  `sockets.target.wants`;
- nothing in Bunny invokes a container runtime; the broker has no generic exec path;
- SELinux targeted policy is enforcing;
- **the packages cannot be removed**: `bootc` requires podman and skopeo, and
  `rpm-ostree` requires skopeo.

The tenth — whether the vulnerable code path is compiled in and active — was not
answered, because it needs per-CVE symbol analysis of a 45 MB stripped Go
binary. All 24 unique Critical/High pairs are therefore `Unknown`, which blocks.

**No waiver was created and no severity was reduced.**
`release/vulnerability.py` refuses a severity reduction without a completed
independent review, and refuses a non-blocking disposition on a Critical for the
same reason. Both refusals are tested.

### Controls added this phase

| Control | Enforces |
|---|---|
| Seven signing roles with disjoint namespaces | a key from one authority cannot be presented for another; checked at parse time |
| The reserved `dev-` prefix | a development key can never satisfy a production release gate |
| Rotation overlap requirement | a replacement published after its predecessor expires is refused, so devices that update late are not stranded |
| Evidence digest verification | a record naming a missing or substituted artifact blocks |
| Commit binding on evidence | evidence does not transfer between commits |
| Self-review wall | a reviewer affiliated with the project cannot be recorded as independent |
| Protected package categories | recovery, accessibility, firmware, installer and security packages cannot be removed, and a dependency cascade into them fails the build |

### An SBOM observation with security consequences

Removing `toolbox` removed the binary from `/usr/bin` and the entry from the rpm
database — verified in a running container — and syft still reports the package,
located at `/sysroot/ostree/repo/objects/…` in a base layer.

The `fedora-bootc` base ships an ostree object store, so `dnf remove` cannot
remove content baked into a lower layer. Two consequences worth carrying
forward: minimisation on this base reduces what *executes* but not what *ships*,
and archive-derived and SBOM-derived scan counts disagree (59 against 84). The
archive scan is treated as authoritative and the discrepancy is recorded rather
than averaged away.

### Position

Unchanged and blocking. 8 Critical and 28 High fixable findings, neither waived
nor converted to PASS. `gate-stable-release` reports `NO-GO`. No release
approval is given and no pilot may begin.

## 2026-07-30 hosted independent builder security addendum

The first execution of `.github/workflows/independent-builder.yml`, and what it
does and does not establish about trust.

### No production signing secret is reachable, asserted rather than assumed

The guard job names all four secrets explicitly and fails if any resolves to a
non-empty value:

```text
BUNNY_OS_RELEASE_KEY  BUNNY_RECOVERY_KEY  BUNNY_UPDATE_KEY  BUNNY_CATALOGUE_KEY
```

Naming them individually rather than iterating over `secrets` is deliberate: the
point is that these four names resolve to nothing in this workflow, and a future
edit that wires one in fails here. The guard passed on every one of the five
dispatches, including the four that failed for other reasons.

The artifacts the workflow produces are unsigned and cannot be promoted. The
import refuses any bundle claiming production provenance without a signature.

### The imported evidence is cross-referenced, not signed

`release/hosted.py` checks each claim a hosted builder record makes against
another file in the same bundle that would have to be edited consistently for the
claim to survive — the runner's own environment report, the CI provenance, the
artifact manifest, the build provenance.

This detects a record edited in one place. It does **not** detect a consistently
forged bundle, and the import record says so:

```json
"signed": false,
"provenanceClaim": "unsigned"
```

`tests/portability/test_hosted_import.py::test_a_consistently_forged_bundle_is_not_claimed_to_be_caught`
asserts the limit directly, so that the acceptance of such a bundle is understood
rather than mistaken for a proof. Closing that gap needs the hosted build to sign
its bundle with a key the importer can verify, which is a key-management change,
not a workflow change.

### A dead base digest is a supply-chain observation

The pinned base image `sha256:fb71f099…` had been garbage collected upstream. The
hosted builder could not obtain it; the local builder built against it from cache.

Two things follow. First, an artifact's provenance can name a base that no longer
exists, and nothing about the artifact reveals this. Second, and more sharply: a
build reproducing on one machine may be reproducing *from that machine's cache*,
and cannot be reproduced by anyone else. A pinned digest is a record of what was
used, not a guarantee of availability, and the two are easy to confuse.

Mitigation, recorded in `KNOWN_LIMITATIONS.md`: mirror the pinned base into a
registry under this project's control.

### An archive-only build cannot qualify anything

`BUNNY_ARCHIVE_ONLY=1` produces an OCI archive and no disk image. Nothing was
installed, nothing booted, no recovery media was written, no hardware was
exercised. Both protected gates refuse such an artifact and name what it did not
do; the build provenance declares `archiveOnly: true`; and a record that does not
declare the field at all is treated as *unknown*, not as a full build.

This matters because an archive-only artifact is otherwise indistinguishable from
a complete one: same filename, same digest discipline, same provenance shape.
