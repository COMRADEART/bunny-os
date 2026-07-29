# Bunny OS Phase 1 security review

## Review outcome

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
