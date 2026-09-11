# Installer trust evidence — peercred/token + Secure Boot/LUKS

**Reviewer:** Cursor cloud agent (host-only source and unit tests; **not** an independent assessment).  
**Subject:** [COMRADEART/bunny-os](https://github.com/COMRADEART/bunny-os) after allowlist fail-closed (#47 on `main`).  
**Date:** 2026-09-11.  
**Method:** Static reading of the installer trust path, reconciliation against `INSTALLER_SECURITY_REVIEW.md` (2026-07-28) and PR #44’s baseline note, plus host unit tests on this Linux review VM. **No Bunny guest was booted, no disk image was built, no QEMU/KVM ran, and no UEFI/LUKS/Secure Boot firmware was exercised.**

`release/reviews.py` would refuse this document as independent evidence. Treat it as a tagged evidence map and a bounded CODE hardening, not a clearance.

Every finding is tagged **CODE** / **INTEGRATION** / **IMAGE** / **BOOT**. This session does **not** claim IMAGE or BOOT. Platform owns `finalise-image` / `vm-smoke` digests.

---

## STATUS

| Scope | Status | Bound |
|---|---|---|
| Installer AF_UNIX peercred + session token + nonce (source + host tests) | **PASS** | Kernel `SO_PEERCRED` on this host’s socketpair; token file 0400; wrong/empty token; nonce replay; stdout greeting has no token |
| Live guest E2E of that channel (second user, systemd unit, Anaconda bus) | **PARTIAL** → residual **INTEGRATION** | Code exists; guest not run |
| Destructive Anaconda adapter on live media | **BLOCKED** | Fail-closed without a live executor; no adapter invention in this pass |
| UEFI / LUKS2 / Secure Boot / recovery on a real or VM image | **BLOCKED** | **IMAGE / BOOT — NOT_RUN.** Do not read host tests as firmware evidence |
| Stable release | **NO-GO** | Unchanged; README physical hardware = zero reports |

**Headline for Gate Keeper / LEAD:** the 2026-07-28 High “peer credentials/token-file delivery not implemented end to end” is **stale as a code-absence claim**. The socket server is in tree. This pass closed two CODE gaps (token on stdout/journal; `SO_PEERCRED` fail-open on missing/unreadable credentials) and added host tests. Guest E2E and physical Secure Boot / LUKS / recovery remain **NOT YET VERIFIED**.

---

## WHAT EXISTS IN CODE

### Trust channel (live installer backend)

```text
bunny-setup (live uid ≥ 1000)
        |  AF_UNIX 0600, SO_PEERCRED, session token, 60s timestamp, nonce
        v
bunny-installer-backend (root)     installer/backend/server.py
        |  InstallerService        installer/backend/service.py
        |  fail-closed without production adapter
        v
AnacondaAdapter / private bus      IMAGE — not claimed here
```

| Control | Where | Host evidence |
|---|---|---|
| Socket bind umask `0o177` → mode **0600** | `ProtocolServer.open` | `test_the_socket_is_mode_0600` |
| `SO_PEERCRED` UID vs `live_uid` | `ProtocolServer.peer_uid` / `handle` | Kernel socketpair + foreign-uid mock |
| Missing / unreadable / invalid peercred **refused** | `PeerCredentialError` | `test_missing_so_peercred_is_refused_not_admitted` |
| Session token 0400, `O_EXCL\|O_NOFOLLOW`, `fchmod` | `write_session_token` | leftover 0644 and symlink tests |
| Token **not** on stdout (would have hit the journal) | `listening_greeting` | greeting has no `sessionToken` |
| Unit `StandardOutput=null` | `systemd/bunny-installer-backend.service` | unit-file test |
| Token compare + empty token refuse | `InstallerService._authenticate` | wire tests |
| Nonce replay window (`deque` maxlen 1024) | same | wire replay test |
| 60s timestamp window | `installer/protocol.py` | existing `test_rejects_stale_request` |
| Secrets off the JSON protocol (memfd / `SCM_RIGHTS`) | `ProtocolServer.handle` | existing `test_install_wire` |
| `install.start` fail-closed without adapter | `InstallerService` | existing backend tests |
| Live UID must be ≥ 1000 | `InstallerService.__init__` | source |

The unprivileged client reads **only** `/run/bunny-installer/session-token` (`installer/frontend/client.py`). It never needed the stdout greeting.

### CODE gaps closed in this pass

1. **Session token on stdout** — `serve()` printed `sessionToken` in the process greeting. systemd default `StandardOutput=journal` would persist it. The architecture report already said the token must not be in the socket greeting; stdout was the same class of leak. **Fix:** greeting carries `sessionTokenPath` only; unit sets `StandardOutput=null`. **CODE.**
2. **`SO_PEERCRED` not fail-closed** — missing option or `getsockopt` failure was an uncaught exception (could take down the accept loop) rather than a refuse. **Fix:** `PeerCredentialError`, refuse the connection. **CODE.**
3. **Token file mode on a leftover inode** — `open(..., O_TRUNC, 0o400)` does not chmod an existing 0644 file. **Fix:** unlink + `O_EXCL` + `fchmod 0400`. Symlink at the path is removed, not followed; the target is untouched. **CODE.**
4. **Missing host tests** for kernel peercred, socket 0600, token 0400, empty token, wire replay, no token in events. **CODE.**
5. **Probe/architecture overclaim** — `installer-backend-probe.py` documented a second-UID `SO_PEERCRED` refusal it does not perform (one process, one uid). Corrected. **CODE** (honesty).
6. **Stale host probe vs memfd secrets** — after the protected fd channel landed, the probe’s successful `install.start` no longer sent secrets, so it failed closed before measuring confirmation+kickstart. Restored fixture secrets on the existing channel. **CODE.** Still RecordingExecutor, still not Anaconda.

### LUKS / recovery (source only)

| Control | Where | Tag |
|---|---|---|
| LUKS2 only; TPM requires fallback password + recovery key + PCR policy | `installer/encryption/plans.py` | **CODE** — host-tested in `tests/installer/test_encryption.py` |
| Encrypted `install.start` requires `recoveryKeyConfirmed` and passphrase over the fd channel | `InstallerService._dispatch` | **CODE** |
| Kickstart `--luks-version=luks2`; passphrase not in protocol JSON | `test_install_wire` | **CODE** (recording executor, not cryptsetup) |
| `installer.recovery.prepare` returns `prepared: False` until a production adapter verifies recovery | `InstallerService` | **CODE** — honest refusal |
| Hardware probe reads efivar `SecureBoot-*` when present; preflight is “state detection only; derived boot chain unqualified” | `installer/hardware/probe.py`, `preflight.py` | **CODE** — does **not** qualify firmware |
| Legacy BIOS classified unsupported | `tests/installer/test_hardware.py` | **CODE** |

### What this session did not invent

No production Anaconda live adapter. No fake IMAGE digest. No fake BOOT chain. No Polkit/logind installer path (the installer is not the system broker).

---

## TESTS RUN

**Environment:** Linux 6.12.94+, Python 3.12.3, uid 1000. **Absent:** QEMU, Podman image-builder, OVMF, Bunny guest, physical UEFI firmware.

| Command | Result |
|---|---|
| `python3 -m unittest tests.installer.test_trust_channel tests.installer.test_backend tests.installer.test_protocol tests.installer.test_security tests.installer.test_encryption tests.installer.test_install_wire tests.installer.test_hardware tests.boot.test_unit_runtime_directories` | **56 tests, OK** |
| Same plus remaining `tests.installer.test_*` modules | **212 tests, OK (skipped=19)** — skips are GTK/runtime, not trust-channel failures |
| `python3 build/scripts/installer-backend-probe.py` | **exit 0**, `findings: []`. Socket `0o600`; wrong token `authentication`; replay `authentication`; wrong phrase refused; start `complete` on **RecordingExecutor** (`"recorded, nothing was written"`). Not Anaconda. Not a guest. |
| IMAGE / BOOT / `finalise-image` / `vm-smoke` / physical Secure Boot / LUKS | **NOT_RUN** |
| Opsera MCP `security-scan` | **NOT_RUN** (namespace `needsAuth`) |

The backend probe previously failed closed after the memfd secret channel landed (`the account password did not arrive over the protected channel`) because the probe never sent descriptors. That is a host-probe bug, not an Anaconda result. This pass sends fixture secrets over the existing fd channel so the probe matches `test_install_wire`. **CODE.** Still not IMAGE.

---

## UNVERIFIED

| Item | Tag | Why it is not claimed |
|---|---|---|
| Second real user connecting to `/run/bunny-installer/backend.sock` on live media | **INTEGRATION** | Foreign uid is mocked on the host; no `useradd` + `su` live session |
| systemd activation, `live-session` marker, token `fchown` to uid 1000 as root | **INTEGRATION** | Unit file asserted; unit not started here |
| Anaconda private bus + destructive install | **INTEGRATION** / **IMAGE** | Fail-closed without adapter; probe uses `RecordingExecutor` |
| Guest E2E of peercred/token (PR #44 note) | **INTEGRATION** / **IMAGE** | Still **NOT YET VERIFIED** |
| ISO embed of media manifest; signed live image | **IMAGE** | Platform / `finalise-image` |
| VM smoke, OVMF Secure Boot development keys | **BOOT** | Platform / `vm-smoke` |
| Physical Secure Boot enrolment, TPM2 PCR, LUKS unlock at firmware, recovery ISO | **BOOT** | README: zero physical hardware reports; `ENCRYPTION_QUALIFICATION_REPORT.md` leaves `secure-boot-interaction`, `recovery-key`, `recovery-media-access` as **NOT_RUN** |
| Historical VM rows (`luks-password-unlock`, `incorrect-password`, `tpm-fallback`) | **BOOT** | Prior commits / qualification trees — **not re-run** on this tree |
| Broker-parity `/proc` start-time bind on installer peers | **CODE** (residual) | Installer is a short-lived live-uid + token channel; not added here |
| Nonce deque wrap after 1024 unique nonces | **CODE** (residual) | Installer session is tens of operations; 60s timestamp still applies |
| `/run/bunny-installer` directory mode 0755 (vs companion 0700) | **CODE** (residual) | systemd `RuntimeDirectory` default; socket 0600 + token 0400 still bind the objects |
| SELinux installer domain | **IMAGE** | Bunny policy is compile-test only; live images use Fedora `targeted` |
| Cleanup after partial partition/encryption/bootloader failure | **BOOT** | Open High in the 2026-07-28 review; needs fault injection on a disk |

---

## Ranked backlog (for Gate Keeper / LEAD)

1. **INTEGRATION — guest E2E of the installer socket.** Boot a disposable live image, confirm 0600 socket, 0400 token owned by the live user, `SO_PEERCRED` refuses a second account, wrong token/replay still refuse, `install.start` still fail-closed without Anaconda. Owner: Platform image + Security witness. This is the remaining half of the 2026-07-28 High.
2. **IMAGE — reviewed Anaconda adapter on the composed ISO**, with the adapter injection path that already exists (`AnacondaDBusExecutor.preflight`). Do not invent an adapter in a host-only agent. Owner: Platform.
3. **BOOT — LUKS2 password unlock + recovery key + wrong credential** on the current image digest (`finalise-image` / `vm-smoke`). Historical PASS rows are not this tree. Owner: Platform.
4. **BOOT — Secure Boot interaction** (`ENCRYPTION_QUALIFICATION_REPORT.md` `secure-boot-interaction` is NOT_RUN). Needs OVMF with enrolled keys or physical firmware. Owner: Platform + Hardware.
5. **BOOT — recovery media against an encrypted install** (`recovery-media-access` NOT_RUN). Owner: Platform.
6. **CODE (low) — installer peer `/proc` start-time bind** if guest E2E shows PID reuse is in the live-media threat model. Broker already has this; copy only with tests.
7. **CODE (low) — nonce store vs wrap.** Prefer a set+TTL if the protocol ever grows chatty.
8. **IMAGE — SELinux installer/Anaconda allow rules.** Skeleton policy does not cover this socket.
9. **Independent review** of the destructive adapter and boot chain. This document is not that review.

Do **not** spend a host-only agent on (2)–(5). They are IMAGE/BOOT by construction.

---

## Mapping to the 2026-07-28 open table

| 2026-07-28 finding | Tag then | This tree |
|---|---|---|
| No production Anaconda adapter / destructive evidence | Blocker | Still **BLOCKED**. **INTEGRATION** / **IMAGE** |
| No live/beta image or UEFI/LUKS/Secure Boot VM | Blocker | Still **BLOCKED**. **IMAGE** / **BOOT** |
| Peer credentials/token-file not implemented E2E | High | **CODE implemented + host-tested.** **INTEGRATION** guest E2E still open |
| Anaconda/bootc ISO compatibility | High | **IMAGE** — not this pass |
| Cleanup after partial encrypt/bootloader failure | High | **BOOT** — not this pass |
| Media manifest not proven embedded in ISO | High | **IMAGE** — not this pass |
| JSON Schema meta-validator | Medium | Unchanged |
| First-run/GTK/live-session runtime | Medium | Unchanged; GTK may skip on this host |
| Inherited broker/update/SELinux/signing | Medium | Out of scope (see `SECURITY_BASELINE_REPORT.md`) |

---

## TESTS RUN receipt

See **TESTS RUN** above. This section is not a second set of claims.
