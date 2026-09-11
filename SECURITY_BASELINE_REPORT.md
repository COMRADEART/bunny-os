# Bunny OS security baseline report

**Reviewer:** Cursor cloud agent (host-only source and gate review; **not** an independent assessment).  
**Subject:** [COMRADEART/bunny-os](https://github.com/COMRADEART/bunny-os) `main` at `23ecc9641b54b324cf66fc7dc1e4eac95c65ed4b` (2026-09-11).  
**Date:** 2026-09-11.  
**Method:** Static reading of production paths, reconciliation against existing `*SECURITY*` reports, and host unit/gate execution on this Linux review VM. **No Bunny guest was booted, no disk image was built, no QEMU/KVM ran, and bubblewrap is not installed on this host.**  
**Fixes in this pass:** none. No production private key or live credential was found in source, so nothing was rotated.

`release/reviews.py` would refuse this document as independent evidence. Treat it as an attack-surface inventory and gap analysis, not a clearance.

---

## SECURITY STATUS

**PARTIAL** for source-level controls that this host can execute.  
**BLOCKED** for stable release, public beta, OEM/enterprise/sync pilots, and any claim of “tested and secure against production threats.”

| Principle | Source (this commit) | Runtime / guest |
|---|---|---|
| Least privilege | **PARTIAL** — broker method allowlist, capsule fail-closed launch, companion `AF_UNIX` | **NOT YET VERIFIED** on this commit’s image |
| Deny by default | **TESTED** on host (policy/gate/surfaces) | Guest Trust journeys remain **NOT_RUN** in this session |
| Explicit consent | **TESTED** on host (no “always allow everything”) | Graphical portal/camera/clipboard isolation **INCONCLUSIVE** historically |
| Local-first privacy | **TESTED** defaults (telemetry off; memory deny-by-default) | Egress and remote-dispatch **NOT YET VERIFIED** live |
| Auditable actions | **TESTED** on host (trust audit + broker journal metadata) | Guest journal/AVC collection historically **blind** |

Absence of a crash in this review is not evidence of security. Rows marked **TESTED AND SECURE AGAINST TESTED THREATS** are bounded to the exact tests named below. Everything else is **NOT YET VERIFIED**.

Stable release remains **NO-GO**, matching `README.md` and `STABLE_CANDIDATE_SECURITY_REVIEW.md`.

---

## THREAT MODEL

Authoritative model: `docs/THREAT_MODEL.md` (plus Phase 5/7 extensions in the same file).

**Assets:** user files and credentials; companion memory/store; plugin/catalogue trust; local models; OS image and update keys; recovery material; audit logs.

**Boundaries this review mapped:**

```text
untrusted app / model output
        |  TrustGate (deny-by-default)
        v
capsule plan (bwrap/flatpak argv)     companion ToolBroker (allowlist)
        |                                  |
        v                                  v
kernel namespaces / mounts            allowlisted adapters (no shell)
        |
        v
bunny-system-broker (AF_UNIX, SO_PEERCRED, Polkit)
        |
        v
root: updates, power, recovery, typed policy apply
```

**Actors (from the model, restated):** malicious local user; compromised Bunny process; compromised plugin/app; compromised model file; compromised update server; malicious website; supply-chain attacker; stolen device; compromised session; malicious removable media.

**This session did not re-exercise** cross-user VM isolation, Secure Boot, LUKS, recovery media, physical hardware, or a live update channel. Those remain residual gaps the threat model already names.

Phase 0 / ADR-0010 language (“there is no sandbox”; Bash hands model-generated strings to a shell) is **historical constitution text**, not a description of `companion/` at this commit. Current code is the opposite of that path; see AI TOOL SECURITY.

---

## ATTACK SURFACE REVIEWED

| Surface | Primary paths | This session |
|---|---|---|
| App capsules | `capsules/`, `trust/`, `catalog/` | Host tests + code |
| Trust / approval UX | `trust/`, `companion/trust_surface.py`, `companion/visible_trust.py`, `shell/services/bunny_shell/core_state.py` | Host tests + code |
| Privileged broker | `services/bunny-system-broker/`, `systemd/bunny-system-broker.*` | Host tests + code |
| Update agent | `services/bunny-update-agent/`, `docs/UPDATES.md` | Code + docs; **no live manifest** |
| Companion AI tools | `companion/tools.py`, `companion/runtime.py`, `companion/executor.py`, `companion/desktop/` | Host tests + code |
| Memory / privacy | `companion/privacy.py`, `companion/memory_boundary.py`, `scripts/bunny-first-boot.py` | Host tests + code |
| systemd / SELinux | `systemd/`, `selinux/`, `config/systemd/60-bunny-os.preset` | Code; SELinux **not loaded** |
| IPC | Unix sockets, loopback TCP fallback, session D-Bus, Anaconda private bus | Code |
| Network | `config/firewalld/`, presets, listeners | Config tests; **no live `ss`** |
| Installer / first boot | `installer/`, `scripts/bunny-first-boot.py` | Host tests + code |
| Dependencies / CVE | `release/cve.py`, `CVE_REACHABILITY_DISPOSITION_REPORT.md` | Gate **re-run** |
| Existing security reports | root `*SECURITY*` + Phase 11/15/16 | Inventory below |

Historical guest evidence cited but **not re-run:** `qualification/capsules/evidence/guest-524107e50b2e/` (`CAPSULE_VM_SECURITY_REPORT.md`).

---

## PERMISSIONS

### What is enforced in code (host-tested)

`trust/policy.py` is an eight-step procedure with **no default-allow branch**. Undeclared categories never reach a prompt:

```117:123:trust/policy.py
    # 3. Not declared.
    if not declaration.known:
        return Resolution(verdict="deny", reason_code="unknown-application")
    if declaration.application_id != request.application_id:
        return Resolution(verdict="deny", reason_code="malformed-request", failure="declaration-mismatch")
    if not declaration.declares(request.category):
        return Resolution(verdict="deny", reason_code="not-declared")
```

Unenforceable categories are refused **before** standing grants or install consent:

```132:139:trust/policy.py
    if not category.enforced_by_default:
        return Resolution(verdict="deny", reason_code="not-enforceable")
```

`TrustGate` default surface is `DenyingSurface` (`None` → deny). Silence, crash, timeout, expired ticket, and out-of-offered scope all deny. `block()` can only write denials.

There is **no “always allow everything”** control. Forbidden labels are explicit:

```56:63:companion/visible_trust.py
FORBIDDEN_LABELS = frozenset({
    "Always allow everything",
    "alwaysAllowEverything",
    "Allow all",
    "Always allow all",
})
```

Shell snapshots reject unbounded approvals (`alwaysAllowEverything`, `scope: "*"`). Camera/microphone/screen_capture offer at most `session`, never `always`. Sensitive capability-applicator actions must have `safe_default="denied"`.

**TESTED AND SECURE AGAINST TESTED THREATS:** host unit tests for undeclared deny, silence deny, surface crash deny, scope widening refuse, no blanket always-allow, no automation surface auto-selected. See TESTS EXECUTED.

### Gaps (not inflation)

- **Folder `always`** is scoped to a declared directory + app + purpose, but it covers every file under that folder. Closest production analogue to “remember forever,” not a global bypass.
- **Install-time `catalog-default`** auto-allows declared **required** categories of risk ≤ medium. High/critical still prompt. Intentional, disclosed.
- **Network classes `loopback` / `local-network` / `allowlisted`** can be granted while the kernel only enforces `none` vs “has a network namespace.” Prompt text warns that allowlisted grants effectively open the internet (`trust/explain.py`). This is a **claim vs enforcement** gap, not a silent bypass.
- Phase 0/1 docs still discuss legacy CLI `bypassPermissions` / `acceptEdits`. Those strings are **not** in the Python `trust/` stack at this commit.

---

## SANDBOXING

### What exists

Primary capsule backend is **bubblewrap** with user/pid/ipc/uts/cgroup namespaces, `--unshare-net` when `network=none`, `--ro-bind /usr`, `--clearenv`, `--remount-ro /`, launched as a **systemd user transient service** (not a scope — companion units set `RestrictNamespaces=yes`, which would break `unshare(2)` if forked from the companion).

```101:107:capsules/command.py
def render_bubblewrap(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """A ``bwrap`` invocation that expresses the whole plan."""
    arguments = _unit_prefix(plan)
    arguments += ["bwrap", "--die-with-parent", "--new-session"]

    for namespace in plan.unshare:
        arguments.append(f"--unshare-{namespace}")
```

Default executor **starts nothing** (`RecordingExecutor`). Live start refuses unconfined plans. Non-confining `systemd-scope` is never auto-selected unless `allow_unconfined=True` (Settings projection / tests only).

```203:205:capsules/runtime.py
    def start(self, argv: Sequence[str], plan: IsolationPlan) -> int | None:
        if not plan.confining:
            raise CapsuleIsolationError("refusing to start an application with no confinement")
```

Network honesty is written into the planner:

```107:116:capsules/isolation.py
#: ``none`` is a network namespace with nothing in it — a kernel boundary.
#: ``internet`` is the absence of one. ``loopback``, ``local-network`` and
#: ``allowlisted`` are declared by the catalogue and mapped onto ``internet``,
#: because nothing here filters by subnet, by interface or by name.
#:
#: Measured rather than assumed: the qualification granted a capsule an
#: allowlist naming one domain, and the capsule connected to a different one.
```

### What is not present

| Technology | Status |
|---|---|
| Firecracker / gVisor | ADR-0010 T3 only — **not implemented** |
| Landlock | Detected in `tools/bunny-os/bunny_os/info.py`, **not applied** to capsules |
| Custom seccomp on bwrap argv | **Absent** (companion systemd `SystemCallFilter=@system-service` is a different process) |
| Bunny SELinux domains | Compile-test only; **not installed** |
| AppArmor | Fedora guest historically `-APPARMOR` |

**TESTED AND SECURE AGAINST TESTED THREATS:** plan-shape, traversal, credential-dir refusal, fail-closed backend selection, no unconfined launch — **as Python values**, not as a running kernel. `tests/capsules/test_isolation.py` says so explicitly.

**NOT YET VERIFIED this session:** live bwrap (binary absent here). Historical VM (`guest-524107e50b2e`) reported filesystem/IPC/PID/`network=none` isolation **ISOLATED**; allowlisted network **not enforced**; camera/GPU/clipboard **INCONCLUSIVE**; escape-class attacks **not attempted**.

---

## SYSTEMD / SELINUX

### Broker (strongest unit)

`systemd/bunny-system-broker.service` includes empty `CapabilityBoundingSet`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, `RestrictAddressFamilies=AF_UNIX`, `RestrictNamespaces`, `MemoryDenyWriteExecute`, `IPAddressDeny=any`, and a deny-list syscall filter. Host test `test_broker_systemd_hardening` asserts a subset.

Socket is intentionally world-connectable:

```9:10:systemd/bunny-system-broker.socket
ListenStream=/run/bunny/broker.sock
SocketMode=0666
```

Authorization is `SO_PEERCRED` + `/proc` start-time binding + Polkit for mutations (`docs/adr/ADR-003-privileged-broker-authentication.md`). Connection ≠ permission. Residual: any local process can *connect* and then attack the protocol/Polkit path.

### Update agent

`systemd/bunny-update-agent@.service` is correctly looser (needs network, `/sysroot`, `/boot`, `@mount`). Missing vs broker: `CapabilityBoundingSet`, `PrivateDevices`, `RestrictNamespaces`, `MemoryDenyWriteExecute`. **No unit-hardening test** analogous to the broker’s.

### Companion

`systemd/user/bunny-companion.service`: `NoNewPrivileges`, `ProtectHome=read-only`, `RestrictAddressFamilies=AF_UNIX`, `RestrictNamespaces=yes`, `SystemCallFilter=@system-service`, `MemoryMax=2G`. `MemoryDenyWriteExecute` is **deliberately absent** (PyTorch/oneDNN). Remote HTTPS providers would fail closed until this unit is reviewed.

### Anaconda bus

`systemd/bunny-anaconda-bus.service` runs `dbus-daemon` with essentially **no** sandbox directives. Live-install only (`ConditionPathExists=/run/bunny-installer/live-session`). Residual for the installer medium.

### SELinux

```1:3:selinux/README.md
Fedora SELinux stays enforcing. `bunny_os.te` and `bunny_os.fc` declare the intended Bunny service, app, plugin, and model domains and are compiled in CI. They are intentionally **not installed into the Phase 1 developer image**
```

`selinux/bunny_os.te` is a Phase 1 skeleton: `init_daemon_domain` / `application_domain` macros, var_lib manage patterns, syslog. **No** companion, capsule, installer, D-Bus, or Polkit allow rules. CI compiles `.pp`; images run Fedora `targeted`. Capsule VM AVC count of 0 was recorded as “nobody looked” (`dmesg_restrict`, no `ausearch`).

**TESTED AND SECURE AGAINST TESTED THREATS:** broker unit text contains named hardening directives.  
**NOT YET VERIFIED:** `systemd-analyze security` on a booted image; loaded Bunny MAC; AVC visibility.

---

## AI TOOL SECURITY

### Intended path (matches code)

**Model → `TaskPlan` → runtime permission/idempotency → `ToolBroker.invoke` → allowlisted implementation.**

`companion/executor.py`: an executor **has no `run` method and is handed no broker**. Runtime invokes with `caller="runtime"`:

```1416:1427:companion/runtime.py
            outcome = self.broker.invoke(
                operation.tool, operation.arguments,
                caller="runtime", classification=task.classification,
                # The authority facts, built here and nowhere else. An executor
                # returns plans; it has no channel to this parameter, ...
                context=tool_context,
            )
```

Broker refuses unknown tools (including `shell.run`), classification above the tool ceiling, missing context, and non-`runtime`/`executor`/`recovery` callers. Reviewers cannot execute. Remote provider executor proposes **zero tools**.

Desktop/voice adapters use argv lists, binary allowlists, and refuse `sh` / `gdbus` / `dbus-send`. Capability discovery uses `ALLOWED_COMMANDS` absolute paths, `shell=False`.

**FLAG — Model → arbitrary shell:** **no production path found** at this commit in `companion/`, `services/`, `capability/` for model output → `shell=True` / `os.system` / `eval` / `exec`. `shell.run` exists as a **negative test** (`tests/companion/test_desktop_security.py`, `companion/desktop/vertical_slice.py`).

**TESTED AND SECURE AGAINST TESTED THREATS:** allowlist refusal of `shell.run`; no `shell=True` in broker/shell sources (grep tests).  
**NOT YET VERIFIED:** every future tool’s argument validator; live local-model prompt injection that only changes *which allowed tool* runs.

### Prompt injection

Surfaces: user request (length-capped), task history/tool results (fenced context sources), local file search (paths revalidated), URI open (credentials in URI refused). **No companion RAG/web-fetch tool** in this build. Clipboard adapter is write-only.

Injection **cannot skip the broker**, but **can still influence arguments** of an approved tool (e.g. search fragment → path → open). Reason text cannot contain control characters; there is no model `reason` source (`test_there_is_no_reason_source_for_a_model`). Residual social engineering via 240-character attributed app text remains.

---

## MEMORY PRIVACY

`MemoryPolicy` defaults: session/durable **off**, `cloud_context="none"`. Working memory only.

```66:71:companion/memory_boundary.py
class MemoryPolicy:
    """The person's memory controls. Defaults deny everything but working."""
    session: bool = False
    durable: bool = False
    cloud_context: str = "none"
```

Audience ceilings: remote ≤ `internal`; audit ≤ `internal`; secret fields stripped by name (`api_key`, tokens, etc.). First-boot privacy flags are all `False`.

Approved **remote_dispatch** still sends `originalRequest` and tool results off-device after consent — minimization, not anonymization.

**TESTED AND SECURE AGAINST TESTED THREATS:** default-deny memory policy construction; first-boot telemetry defaults.  
**NOT YET VERIFIED:** actual packets leaving a machine; same-user local attacker reading companion state.

---

## SECRETS CHECK

| Check | Result |
|---|---|
| `BEGIN PRIVATE KEY` / OpenSSH private key in production trees | **Not found.** Hits are tests, fixtures, and scanners that *refuse* keys |
| `build/keys/` | Public snapshot key + `revoked-keys.json` + README. **No private key, no release public key** (`build/keys/README.md`) |
| Update agent | HTTPS URLs with embedded credentials refused; OpenSSL verify of Ed25519 over canonical JSON |
| Broker audit | UID/method/outcome — not parameters or file content (`docs/PRIVILEGED_BROKER.md`) |
| First-run JSON | Secret-shaped keys rejected (`installer/first_run/state.py`) |

**No critical committed secret.** No rotate-in-place action taken.

**NOT YET VERIFIED:** journald under a live credential-using session; image-level secret scan of a built artifact (explicitly out of `SECURITY_REVIEW.md` static tests).

---

## NETWORK EXPOSURE

Config intent:

- firewalld zone `target="DROP"`, no `<port` (`config/firewalld/bunny-default.xml`) — host-tested.
- Preset **disables** `sshd.service` **and** `sshd.socket` (historical 0.0.0.0:22 from socket activation), `passim.service`/`.socket` (0.0.0.0:27500), `bunny-update-agent.timer`, `bootc-fetch-apply-updates`.
- Host test forbids `0.0.0.0:<port>` in `services/`, `systemd/`, `config/` **directives** (comments stripped so the sshd explanation does not trip the test).

Known remaining listeners (from `KNOWN_LIMITATIONS.md`, **not re-measured here**): `avahi-daemon` UDP 5353 and `systemd-resolved` 5355 on all interfaces. Not Bunny app servers; still inbound exposure.

Companion may fall back to **127.0.0.1** TCP with a transport token. Same-UID local processes that can read the token file are in the companion threat model as hostile clients.

**TESTED AND SECURE AGAINST TESTED THREATS:** no `0.0.0.0` bind in owned unit/config directives; firewalld DROP text.  
**NOT YET VERIFIED on this commit’s image:** `ss -tulpn` / nftables after first boot.

---

## IPC REVIEW

| Channel | AuthZ | Schema |
|---|---|---|
| `/run/bunny/broker.sock` | `SO_PEERCRED`, system-UID denial, nonce, rate limit, Polkit for mutations | Closed `METHODS` table — no generic exec/D-Bus forward |
| Companion Unix socket | `SO_PEERCRED`; mode 0600 in 0700 dir (integration review) | Fixed `OPERATIONS` — not `getattr` |
| Companion loopback TCP | HMAC compare of per-run token | Same table |
| Installer `/run/bunny-installer/backend.sock` | Live-session UID via `SO_PEERCRED`, session token, nonce; 0600 | Ten typed operations |
| Anaconda private bus | Unix path under `/run/anaconda/` | Anaconda’s own bus conf |
| Session D-Bus (GNOME/NM/MPRIS) | User session | Shell extension proxies |

Broker methods include power, update, rollback, recovery, logs export, hardware inventory, and typed `policy.*` operations that carry **ids/versions only**, not desired state blobs.

**TESTED AND SECURE AGAINST TESTED THREATS:** installer has no generic command; broker sources contain no `shell=True` / `AF_INET` / `eval`.  
**NOT YET VERIFIED:** kernel `SO_PEERCRED` on a booted image (host tests mock or unit-test the Python); cross-user connect-and-mutate.

`INSTALLER_SECURITY_REVIEW.md` (2026-07-28) still lists “peer credentials/token-file delivery not implemented end to end” as High. **Code at this commit implements the socket server** (`installer/backend/server.py`). The review is stale; **guest E2E of that channel is still NOT YET VERIFIED.**

---

## DEPENDENCY RISKS

Re-run at this commit:

```text
$ python3 scripts/release.py cve-disposition
per-CVE analyses: 24 of 24 Critical/High advisories
  Unknown                    24
BLOCKED: 24 advisory(ies) block a stable release
```

| Metric | Value |
|---|---|
| Unique Critical/High (`--only-fixed`) | **24**, all class **Unknown** |
| Base-image fixable (historical scan) | 59 (8 Critical, 28 High, 23 Medium) |
| Carriers | podman, skopeo, bootc (Go modules: `golang.org/x/crypto` 7× Critical, grpc, podman, buildkit, docker, …) |
| Q7 “vulnerable path compiled in and active?” | **unknown** — this is the blocking question |
| Symbol analysis | **0 of 4 binaries** (`CVE_BINARY_ANALYSIS_REPORT.md`) |
| ADR-027 | Retain `fedora-bootc:44` **and** retain **NO-GO** |

`Unknown` is blocking by construction (`release/cve.py`). Nine of ten reachability questions were answered on a prior image: binaries present, not enabled by default, not listening, unprivileged-invocable, not invoked by Bunny, not removable because bootc requires them.

This review **does not** reclassify those 24 as Reachable or Unreachable. Guessing Q7 would be a waiver by another name.

Independent reviews: **0 delivered** (`python3 scripts/release.py validate-independent-reviews` re-run this session).

---

## TESTS EXECUTED

**Environment:** Linux 6.12.94+ review VM, Python 3.12.3, commit `23ecc964`. **Absent:** `bwrap`, `firecracker`, `qemu-system-x86_64`, Podman image-builder, Bunny guest.

| Command | Result |
|---|---|
| `python3 -m unittest tests.security.test_security_baseline tests.security.test_desktop_security tests.trust.test_policy tests.trust.test_gate tests.trust.test_security tests.capsules.test_security tests.installer.test_security` | **102 tests, OK** |
| `python3 -m unittest tests.companion.test_desktop_security tests.companion.test_visible_trust tests.trust.test_surfaces tests.security.test_desktop_security` | **94 tests, OK** |
| `python3 scripts/release.py cve-disposition` | **BLOCKED**, 24 Unknown |
| `python3 scripts/release.py validate-independent-reviews` | **BLOCKED**, 0 delivered |
| Capsule `runtime_qualify` on this Ubuntu review VM | **BLOCKED** — `bwrap`/`flatpak` ABSENT; only `systemd-scope`; SELinux `getenforce` missing (not a Bunny guest) |
| Capsule VM smoke / `ss` / `systemd-analyze` / guest Trust AT-SPI | **NOT_RUN** |
| Opsera MCP `security-scan` | **NOT_RUN** (namespace `needsAuth`) |
| Image secret scan / Trivy/Grype on bootc | **NOT_RUN** (tools absent) |

Historical (not this session): capsule guest `524107e50b2e` isolation JSON; development signing drills; archive-only reproducibility. README: many runtime gates **NOT_RUN**; stable **NO-GO**.

---

## CRITICAL / HIGH / MEDIUM / LOW FINDINGS

Severity is for **this baseline**, not a claim that older self-reviews were wrong to accept residual risk. Inherited CVEs are listed as release blockers, not as proven Bunny RCEs.

### CRITICAL

| ID | Finding | Evidence | Status |
|---|---|---|---|
| C-1 | **8 Critical advisories in the digest-pinned Fedora bootc base remain `Unknown`.** Gate correctly blocks stable release. Path reachability (Q7) unanswered; binaries not symbol-analyzed. | `CVE_REACHABILITY_DISPOSITION_REPORT.md`; `python3 scripts/release.py cve-disposition` at `23ecc964`; ADR-027 | **NOT YET VERIFIED** as exploitable from default desktop; **BLOCKING** for release |
| — | No Critical *Bunny application* defect (model→shell, default-allow TrustGate, committed production private key) was demonstrated in this pass. | This review | Absence ≠ proof |

### HIGH

| ID | Finding | Evidence | Status |
|---|---|---|---|
| H-1 | **Capsule network allowlisting is not a kernel boundary.** Only `network=none` uses `--unshare-net`. Allowlisted/`local-network` map to full network. Measured historically: grant `example.com`, connect `example.org`. | `capsules/isolation.py` lines 107–116; `CAPSULE_VM_SECURITY_REPORT.md` §6.1 | **TESTED** (historical guest); **unfixed**, disclosed in UI |
| H-2 | **16 High base-image advisories also `Unknown`.** Same Q7 gap. Includes podman/moby/buildkit/selinux/fulcio/otel/`x/net`/`x/text`. | CVE disposition gate | **BLOCKING** |
| H-3 | **Production update integrity not proven.** Agent implements Ed25519, expiry, repo/digest allowlist, monotonic sequence anti-rollback. `docs/UPDATES.md` still names production registry signature policy and unsigned-image rejection as blockers. No production key exists. | `bunny_update_agent.py` `_verify_signature` / `_validate_manifest`; `build/keys/README.md`; `INDEPENDENT_REVIEW_STATUS.md` | **NOT YET VERIFIED** live |
| H-4 | **Bunny SELinux domains are not operational.** Fedora targeted may still confine generic types; Bunny-specific MAC is compile-only scaffolding. AVC collection on capsule VM was blind. | `selinux/README.md`, `selinux/bunny_os.te`; `CAPSULE_VM_SECURITY_REPORT.md` §6.2 | **NOT YET VERIFIED** |
| H-5 | **Escape-class capsule attacks not attempted** (mount escape, user-ns escape, seccomp bypass, portal misuse, broker misuse). Docs admit this. | `APP_CAPSULE_SECURITY_REVIEW.md` §2.4 | **NOT YET VERIFIED** |
| H-6 | **Zero independent security (or crypto) reviews delivered.** Self-reviews and this agent report do not count. | `validate-independent-reviews`; `SECURITY_REVIEW.md` header | Process **BLOCKED** |
| H-7 | **Cross-user isolation and physical/LUKS/Secure Boot/recovery-media paths remain unqualified** for the threats that depend on them. | `docs/THREAT_MODEL.md` residual column; README hardware = zero reports | **NOT YET VERIFIED** |

### MEDIUM

| ID | Finding | Evidence |
|---|---|---|
| M-1 | Broker socket `0666` — connectable by any local UID; auth is protocol-layer. Documented, residual local DoS/authz-bug surface. | `systemd/bunny-system-broker.socket`; ADR-003 |
| M-2 | Bubblewrap renderer does not apply `dbus_talk` / `--talk-name` (Flatpak path does). D-Bus isolation relies on not mounting the session bus. | `capsules/command.py` `render_bubblewrap` vs `render_flatpak` |
| M-3 | Update-agent unit lacks several broker hardening directives; no parallel hardening test. | `systemd/bunny-update-agent@.service` |
| M-4 | `bunny-anaconda-bus.service` is an unhardened `dbus-daemon` on the live medium. | unit file |
| M-5 | Prompt injection can still steer **allowed** tool arguments. | `companion/agents/context.py`; local_files path flow |
| M-6 | Approved remote inference exports user request text (≤ remote `internal` ceiling). | `companion/privacy.py` `AUDIENCE_CEILING`; agent_bridge remote path |
| M-7 | Folder `always` grants are broad within the folder. | `trust/categories.py`; gate coverage tests |
| M-8 | Avahi/resolved listen on all interfaces (historical measurement). | `KNOWN_LIMITATIONS.md` |
| M-9 | Graphical portal/camera/clipboard isolation **INCONCLUSIVE** in console VM quals. | `CAPSULE_VM_SECURITY_REPORT.md` |
| M-10 | `ToolBroker.invoke` still accepts `caller="executor"` even though production executors are not given a broker. Defense-in-depth hole if a future adapter is wired carelessly. | `companion/tools.py` line 268 |
| M-11 | Factory finalize evaluates a **supplied record**, not the device (`available: false` executor). | `FACTORY_PROVISIONING_SECURITY_REVIEW.md` |
| M-12 | Encrypted sync crypto backend `available: false`; no independent crypto review. | `ENCRYPTED_SYNC_SECURITY_REVIEW.md` |
| M-13 | Stale reports vs current code (see inventory). Readers can over-trust old Highs or old “recorded clipboard” language. | This document |

### LOW

| ID | Finding | Evidence |
|---|---|---|
| L-1 | Landlock/Firecracker/custom capsule seccomp unused. | ADR-0010; `info.py` |
| L-2 | Companion `MemoryDenyWriteExecute` absent (documented ML/GTK exception). | `bunny-companion.service` comments |
| L-3 | Same-user loopback token readable by other processes of that user. | `companion/protocol.py`; integration review threat model |
| L-4 | SSH packages may remain installed; exposure depends on preset actually applying. | preset + **NOT YET VERIFIED** image |
| L-5 | Clipboard/bluetooth are **denied** (`not-enforceable`) rather than mediated — fail-closed, but the capability is unavailable. | `trust/categories.py` |
| L-6 | `APP_CAPSULE_SECURITY_REVIEW.md` W-1 still says clipboard is “recorded and not enforced”; policy now refuses before prompt. | W-1 vs `trust/policy.py` 132–139 |
| L-7 | `MemoryMax` may be ignored on some kernels (documented WSL). | capsule resource qual notes |
| L-8 | Phase 0/1 documents still describe the old Bash-tool sandbox absence. | `BUNNY_OS_PHASE_0.md`; ADR-0010 |

---

## RELEASE BLOCKERS

Unchanged in substance; this review **confirms** they still hold at `23ecc964`:

1. **24 Unknown Critical/High CVEs** (Q7 unanswered) — `cve-disposition` BLOCKED.  
2. **No independent security/cryptography review** — 0 delivered.  
3. **No production signing keys**; unsigned-image / registry policy unproven.  
4. **Stable evidence / hardware / recovery media / signed update channel** still open (`docs/STABLE_RELEASE_BLOCKERS.md`: unknown evidence is blocking; signature bypass cannot be waived).  
5. **Bunny SELinux not installed/qualified.**  
6. **Capsule network allowlist unenforced** if a release were to claim per-domain network permission.  
7. **README:** source gate PASS is bound to older commit `85dead7` on a Fedora 44 reference host — **not** this review VM and **not** this HEAD as a measured gate.

This report does **not** clear any of those.

---

## UNVERIFIED ITEMS

- Guest boot of `23ecc964`, graphical Trust, AT-SPI “Allow this Bunny action” / “Deny this Bunny action”.  
- Live `bwrap` isolation, portal camera/mic, GPU device nodes.  
- `systemd-analyze security` scores (docs forbid fabricating them).  
- `ss` / nftables / Avahi on a current image.  
- Signed update fetch/stage/install/rollback on hardware.  
- Cross-user broker/companion attacks.  
- Polkit `--allow-user-interaction` UX under a locked session.  
- Installer destructive path + Anaconda adapter on disposable disk.  
- Per-CVE binary/debuginfo mapping for the 24 Unknowns.  
- Independent reviewer conclusions.  
- Physical hardware, TPM/Secure Boot, LUKS, recovery ISO.  
- Opsera/Trivy container scan of the bootc image.  
- Long-running GNOME extension crash/restart.  
- Whether `MemoryMax` holds on the product kernel.

---

## Existing `*SECURITY*` reports — claim vs code

| Report | What it claims | vs code at `23ecc964` |
|---|---|---|
| `SECURITY_POLICY.md` | Process defined; never operated | Honest |
| `SECURITY_REVIEW.md` | Internal; 24 Unknown; NO-GO | **Matches** gate re-run |
| `SECURITY_REACHABILITY_REVIEW.md` | Q7 unknown blocks | **Matches** |
| `CVE_REACHABILITY_DISPOSITION_REPORT.md` | 24 Unknown BLOCKED | **Matches** (re-run) |
| `CVE_BINARY_ANALYSIS_REPORT.md` | 0/4 binaries | Unchanged this session |
| `docs/SECURITY_BASELINE.md` | Fedora SELinux enforcing, firewalld drop, hardened units, updates off | **Source/config true**; runtime **NOT YET VERIFIED** here |
| `PUBLIC_BETA_SECURITY_REVIEW.md` | NO-GO | Still correct |
| `STABLE_CANDIDATE_SECURITY_REVIEW.md` | BLOCKED / NO-GO | Still correct |
| `POST_RELEASE_SECURITY_REVIEW.md` | N/A; no release | Honest |
| `PHASE_7_SECURITY_REVIEW.md` | No Critical **in Phase 7 source**; inherited CVEs remain | Easy to misread as product clearance — **do not** |
| `INSTALLER_SECURITY_REVIEW.md` | Peer-cred High open (2026-07-28) | **Stale:** server exists; **E2E still unverified** |
| `SHELL_SECURITY_REVIEW.md` | Static OK; runtime denied | Still honest |
| `APP_CAPSULE_SECURITY_REVIEW.md` | Strong host tests; W-1 clipboard recorded | **W-1 stale** — now deny-before-prompt; escape tests still not done |
| `CAPSULE_VM_SECURITY_REPORT.md` | 17 ISOLATED; allowlist fail; AVC blind | Best guest evidence; **not this commit’s guest** |
| `COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md` | 20/22 fixed in 3 adversarial rounds | Self-review; tests still exist; **not independent** |
| `COMPANION_INTEGRATION_SECURITY_REVIEW.md` | Socket/auth hold | Self-review; host tests pass |
| `FACTORY_PROVISIONING_SECURITY_REVIEW.md` | 22 checks fail-closed on records | Evaluator real; **no device executor** |
| `FLEET_SECURITY_REVIEW.md` | No Critical in fleet **source**; no unsigned ring | **No fleet server** |
| `ENCRYPTED_SYNC_SECURITY_REVIEW.md` | Envelope/key refusal; crypto unavailable | Matches `available: false` |
| `INDEPENDENT_SECURITY_REVIEW_REQUEST.md` | Ready to send | Still unsent/uncommissioned |
| Phase 11/15/16 security ops docs | AWAITING_EXTERNAL_EVIDENCE | Fixtures only — **not approval** |

**Do not treat Phase 11–16 operational readiness, Phase 7 “no Critical in source,” or companion self-reviews as release security clearance.** Gates in `release/` already refuse that substitution.

---

## FINAL RECOMMENDATION

1. **Keep stable release, public beta, and all pilots NO-GO.** This inventory does not move those gates.  
2. **Do not ship a story that network permissions are domain-filtered** until a kernel/netfilter/Landlock (or equivalent) boundary exists; keep the current disclosure.  
3. **Commission the prepared independent security review** (`reviews/security/REQUEST.md`) with Q7/binary analysis in scope; this agent report must not be filed as that review.  
4. **Install and AVC-qualify Bunny SELinux** or stop implying Bunny-specific MAC.  
5. **Prove update signature + unsigned-image rejection** on a real registry before enabling `bunny-update-agent.timer`.  
6. **Refresh stale reviews** (installer peer-cred; App Capsule W-1) so claim-vs-code drift does not become a second threat.  
7. **Re-run capsule runtime qualify and listener/sshd/passim checks** on an image built from this (or a later) commit — historical guest `524107e50b2e` is evidence of *a* image, not of HEAD.  
8. **No code fix in this pass.** No committed production secret was found.

**Bottom line:** Bunny OS source at `23ecc964` is **directionally aligned** with least privilege, deny-by-default, explicit consent, local-first defaults, and auditable decisions, and those properties are **host-tested against the unit-level threats named above**. They are **not** demonstrated on a current guest, not independently reviewed, and not sufficient against the open CVE Unknowns, unsigned update channel, missing Bunny MAC, and untested escape/cross-user/hardware paths. **PARTIAL / BLOCKED — not PASS.**
