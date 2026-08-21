# Guest Capsule Qualification

**What this is** The App Capsule runtime qualification suite, run *inside a booted
Bunny OS image* rather than on a development host, with SELinux in Enforcing mode.

**Suite commit** `524107e50b2e`
**Image** `BUNNY_OS_BUILD_ID=39a5c575da9e.1786465088`, profile `shell`, channel `development`
**Kernel** `7.1.5-200.fc44.x86_64`
**Virtualisation** `kvm`
**Ran as** `bunny` (uid 1000), home on ext4
**Finished** 2026-08-11T16:35:55Z
**Verdict** 11 of 11 sections PASS, suite exit 0

---

## 1. Why run it again in a guest

The same suite had already passed on a Fedora WSL host. That is a weaker claim than
it looks, for three reasons that this run was designed to remove:

1. **The WSL host is not the shipped system.** It has a different kernel, a
   different systemd user session, no SELinux policy of its own, and a home
   directory on a 9p mount. A capsule that isolates there has not been shown to
   isolate on the product.
2. **SELinux was not enforcing.** Every mount, transition and socket the capsule
   makes is subject to policy in the guest and was not in WSL. A policy denial
   would have been invisible.
3. **The units were not the shipped units.** The launcher section asserts against
   the Companion units *as installed in the image*. On a development host they are
   files in a checkout; here they are what a user's session would actually run
   under.

## 2. Environment as recorded

```
selinux   mode Enforcing, policy targeted v35, fs mounted,
          self context system_u:system_r:initrc_t:s0
backends  available: flatpak, bubblewrap, systemd-scope
          confining: flatpak, bubblewrap
cgroup    cgroup2fs
```

`systemd-scope` is listed as available and deliberately **excluded from the
confining set** — it schedules and accounts, it does not confine. The suite picked
`bubblewrap`.

## 3. Section results

| Section | Verdict | What was measured |
|---|---|---|
| host | PASS | Environment recorded; confining backends `['flatpak','bubblewrap']` |
| isolation | PASS | 17 checks isolated, **each reached by the negative control** |
| crossapp | PASS | B could not read or enumerate A's storage, before or after a transfer |
| filegrant | PASS | Grant lifecycle: denied / granted / neighbour / revoked / allow-once / reuse |
| failclosed | PASS | Six distinct failure paths, each denying with its own reason |
| network | PASS (with a disclosed gap) | `none` denied external, DNS and loopback |
| selinux | PASS (AVC collection blind) | Every expected operation worked under Enforcing |
| crash | PASS | No survivor in the host namespace; no unconfined orphan |
| launcher | PASS | 31 sandboxing directives across 2 shipped units; pre-fix shape still fails |
| apptask | PASS | The production Companion route produced the file, 214.4 ms |
| resources | PASS | Cold launch 16.2 ms; memory ceiling intervened at 200 MiB |

### 3.1 Isolation, and why the control matters

Nineteen mounts inside the capsule against thirty-five outside, all under the
declared roots (`/`, `/dev`, `/proc`, `/run/bunny/app/{cache,config,data,exports,inbox,runtime,tmp}`).

The number that carries the weight is not seventeen isolated checks — it is that
**the negative control reached all seventeen**. A check that passes because the
resource is absent from the test machine proves nothing; a check that passes while
an unconfined control on the same machine reaches the same resource proves the
confinement. Every isolation claim in this suite is paired that way.

The launch line as recorded:

```
systemd-run --user --quiet --unit=bunny-capsule-… --description=…
  --property=StandardOutput=journal --property=StandardError=journal
  --property MemoryHigh=2147483648 --property MemoryMax=4294967296
  --property TasksMax=512 --property CPUWeight=100 --property KillMode=mixed
  bwrap --die-with-parent --new-session
    --unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup --unshare-net
    --ro-bind /usr /usr  --symlink usr/lib /lib  … --proc /proc --dev /dev
    --bind …/cache /run/bunny/app/cache   (and config, data, exports, inbox, runtime, tmp)
```

It is a **transient service, not a scope**. That is the fix recorded in §4 of
`CAPSULE_VM_SECURITY_REPORT.md`; a scope inherits the caller's seccomp filter and
mount namespace, and under the Companion's own `RestrictNamespaces=yes` it could
never have unshared anything.

### 3.2 The application task, end to end

This is the section that did not exist before this phase. It runs the **production**
Companion route — not a test harness that calls the capsule runtime directly:

```
approval reason  "Bunny Image Tool wants to open Pictures/holiday.png. It will save
                  a copy as holiday-resized.png. Your original file will not be
                  changed. It runs in its protected space with no network access."
export           Pictures/holiday-resized.png, 182 bytes,
                 sha256 27b5e614d887aa5360eb4b1b7258345d85073fc99c7bc44fa86fe9e0db572649
original         still exists, digest unchanged
neighbour        still exists, digest unchanged, never authorised
network          class none, enforced true, shown to the user as "Off"
elapsed          214.4 ms, exit status 0
allow-once       0 grants remaining afterwards
exit states      unknown status is -2; the unit is not collected
```

Four of those lines are there because each was once wrong, and the suite now holds
them: the neighbour digest (a resolver that accepted a bare name), the allow-once
remainder (a session grant that outlived its task), the `-2` unknown status
(`--collect` turned "could not run" into "ran and wrote nothing"), and the export
digest (a `Resource.digest` that hashed the path rather than the bytes).

### 3.3 The two disclosed gaps

Both were recorded by the suite itself, in the same JSON as the pass:

**Network allowlisting is a declaration, not a boundary.** A capsule granted only
`example.com` connected to `example.org`. This build maps every class other than
`none` onto "there is a network"; only `none` is enforced, and it is enforced by
`--unshare-net`, which is absolute. The user-facing string for an allowlisted
capsule must not imply per-domain enforcement until this is real.

**AVC collection was blind.** `kernel.dmesg_restrict = 1`, `ausearch` is not
installed, and `journalctl` returned 0 kernel lines. The recorded denial count is
`0`, and the suite states in its own explanation that this means *nobody looked*,
not *nothing happened*. The SELinux verdict rests on the positive observation —
every expected capsule operation succeeded with the policy loaded and enforcing —
and claims nothing about denials.

### 3.4 Resources

| Measurement | Value |
|---|---|
| Cold launch | 16.2 ms |
| Subsequent launches | 18.2 ms, 13.9 ms |
| Steady-state tree RSS | 17,084,416 B over 3 processes |
| Application RSS | 13,172,736 B |
| Capsule disk | 7,305 B |
| Memory ceiling declared | high 192 MiB, max 256 MiB |
| Intervention | at 200,000,000 B — `cgroup-throttle`, 2,985 `memory.high` events, 0 OOM kills |
| Host control | allocated 243 MiB against the same ceiling, killed with signal 9 |

The distinction in the last two rows is the point: inside the capsule the ceiling
*throttled* (`events.high` 2985, `events.oom_kill` 0) and the workload timed out;
the unconfined control on the same host was OOM-killed. Both are enforcement; only
one is visible to the user as the application getting slow rather than vanishing.

## 4. What this run does not establish

- **No hardware.** Everything here is `kvm`. Nothing is hardware validated.
- **No graphical surface.** `graphical.display` and `waylandDisplay` were both
  empty — this suite ran on the console. Every claim about what a person *sees* is
  made in `VISUAL_SLICE_REPORT.md` and `GRAPHICAL_SESSION_REPORT.md`, not here.
- **No denial count under SELinux**, per §3.3.
- **No per-domain network enforcement**, per §3.3.

## 5. Evidence

`qualification/capsules/evidence/guest-524107e50b2e/` — eleven section JSON files,
`runtime_qualify.log`, `dmesg-restrict.txt`, `dmesg-avc-count.txt`.

Each section file carries its own `commit`, `host`, `measurements`, `findings` and
a plain-sentence `explanation`. The `findings` list is empty on a pass and carries
the failure text otherwise; the disclosed gaps in §3.3 appear as annotations
alongside a pass, which is deliberate — a gap the suite can describe is not the
same as a check it failed.
