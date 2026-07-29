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
