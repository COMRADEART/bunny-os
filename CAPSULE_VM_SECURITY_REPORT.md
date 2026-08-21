# App Capsule Security in the Virtual Machine

**What this is** The security posture of the capsule boundary as measured in a
booted Bunny OS guest, with SELinux Enforcing — including what the measurement
cannot see.

**Commit** `524107e50b2e`
**Kernel** `7.1.5-200.fc44.x86_64`, `kvm`, cgroup v2
**SELinux** Enforcing, `targeted` v35
**Backend chosen** bubblewrap (`flatpak` also available and confining; `systemd-scope` available and **not** counted as confining)

---

## 1. The boundary as built

```
systemd-run --user --unit=bunny-capsule-<app>.<id>
    --property=StandardOutput=journal --property=StandardError=journal
    --property MemoryHigh=… MemoryMax=… TasksMax=512 CPUWeight=100 KillMode=mixed
  bwrap
    --die-with-parent --new-session
    --unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup --unshare-net
    --ro-bind /usr /usr   --symlink usr/{lib,lib64,bin,sbin} → /{lib,lib64,bin,sbin}
    --proc /proc --dev /dev
    --bind <capsule>/{cache,config,data,exports,inbox,runtime,tmp} → /run/bunny/app/*
    --tmpfs /tmp
    [--ro-bind <approved file> /run/bunny/files/<hash>/<name>]   ← only if granted
    --remount-ro /
    --clearenv --setenv HOME /run/bunny/app/data --setenv LANG C.UTF-8
      --setenv PATH /usr/bin:/bin --setenv TMPDIR /run/bunny/app/tmp …
```

Three properties of that command line carry most of the security value:

- **`--clearenv`** — the environment is rebuilt from a declared list, not filtered.
  A filter is a blocklist and will miss the next variable somebody invents.
- **`--remount-ro /`** *after* the binds — the writable set is exactly the capsule's
  own roots and nothing else, regardless of what the base image permits.
- **A transient service, not a scope.** See §4.

## 2. What was measured, and what each verdict means

Thirty-two paired checks, each run twice: once inside the capsule, once by an
unconfined control on the same machine in the same session.

| Verdict | Count | Meaning |
|---|---|---|
| ISOLATED | 17 | The control reached it; the capsule did not |
| SHARED | 6 | Both reached it — see §2.1, the word understates five of the six |
| INCONCLUSIVE | 6 | Neither reached it; **the check proves nothing here** |
| BOTH-DENIED | 3 | Neither reached it, and the control was denied by the host |

The seventeen isolated checks:

```
credentials   browser_profile_read, gnupg_read, ssh_read, ssh_key_read
ipc           dbus_session, dbus_system
user-files    home_read
file-grant    neighbour_file_read
cross-app     other_capsule_enumerate
network       network_external, network_dns, network_localhost,
              network_allowed_domain, network_forbidden_domain
filesystem    symlink_escape_home, traversal_etc_passwd, write_outside_home
```

### 2.1 `SHARED` is a capability comparison, not a content comparison

This is the most misreadable line in the evidence and is stated plainly here. The
verdict compares whether the *capability* was present, not whether the *contents*
were the same. For five of the six:

| Check | Inside the capsule | Control |
|---|---|---|
| `process_visibility` | 2 processes, **0 of them somebody else's** | 239 processes, 236 somebody else's |
| `filesystem tmp` | 0 entries, writable | 24 entries incl. `.X11-unix`, `.ICE-unix` |
| `environment` | 15 variables, **0 of concern** | 35 variables, 1 of concern |
| `mounts` | 19 mounts, all under declared roots | 35 mounts |
| `own_data_write` | wrote to `/run/bunny/app/data` | wrote to its own scratch |

Only `subprocess` is genuinely shared in the ordinary sense — a capsule may fork,
which is intended, and is bounded by `TasksMax=512` rather than by prohibition.

So the process table *is* isolated (`--unshare-pid` works: two processes, none
belonging to anyone else) and the row says `SHARED` because "can the process list
be read at all" is true in both. The isolation for these five lives in the
`structural` block of the evidence, which asserts the mount prefixes and the
environment allowlist directly.

### 2.2 The six inconclusive checks are reported, not hidden

`camera`, `gpu`, `clipboard`, `granted_file_read`, `other_capsule_secret_read`,
`own_data_read` — in each case the control also found the resource absent, because
this suite runs on the console: there are no `/dev/video*` nodes, no
`WAYLAND_DISPLAY`, and some fixtures are absent by construction for the control.

A check where the control finds nothing proves nothing about confinement. Counting
these as passes would have inflated the isolated count from 17 to 23 and made the
suite weakest exactly where it looked strongest. They are counted separately and
named.

The camera and clipboard rows will only become meaningful when the suite is run
from inside a graphical session; that is recorded as outstanding, not as passed.

## 3. Cross-application separation

Capsule B could neither read nor enumerate capsule A's private storage — **before
or after** a deliberate transfer between them — and could read exactly the one
artefact it had been granted.

The "after" half is the part that matters. A transfer mechanism that grants access
to one file by making the neighbourhood reachable is a common shape, and it passes
any test that only checks the state before the transfer.

## 4. The launcher shape, and the defect it fixes

The capsule launches inside units carrying **31 sandboxing directives across the 2
shipped Companion units**, and the suite additionally asserts that the *pre-fix
shape still fails* under both.

The defect: a `systemd-run --user --scope` runs in the **caller's** context. Under
the Companion's own hardening — `RestrictNamespaces=yes` in particular — the scope
inherits the seccomp filter and the mount namespace, so `bwrap` cannot unshare and
fails with 226/NAMESPACE. The Companion could therefore never have launched a
capsule at all, on any machine, in any configuration.

A manager-spawned **transient service** is spawned by systemd itself and is not
subject to the caller's restrictions. The suite keeps the old shape as a live
negative control rather than deleting it, so a future change that reverts to a
scope fails a test rather than silently reintroducing an unlaunchable product.

## 5. Failure and crash boundaries

| Scenario | Result |
|---|---|
| Kill the launcher | No survivor in the host namespace (2 processes checked, both gone, neither escaped its mount namespace) |
| Stop the unit | 0 orphans, none unconfined |
| Corrupt the policy store mid-run | Denied, with reason `store-unreadable` |

`--die-with-parent` and `KillMode=mixed` are what make the first two rows true, and
both are asserted from the recorded command line rather than assumed.

## 6. Two disclosed weaknesses

### 6.1 Network allowlisting is not enforced

A capsule granted `example.com` connected to `example.org`. In this build, only the
`none` class is a boundary — enforced by `--unshare-net`, which admits no
exceptions and was verified against external hosts, DNS **and** loopback. Every
other class currently means "there is a network".

The grant record shows the intent that was not enforced:

```
allowed: example.com   forbidden: example.org   verdict: allow   reason: user-allowed
```

**Consequence for the product:** no user-facing string may imply per-domain
enforcement. The one class safe to describe in absolute terms is Off.

### 6.2 SELinux denials could not be observed

`kernel.dmesg_restrict = 1`, no `ausearch`, `journalctl` returned 0 kernel lines.
The recorded AVC count is `0` and the suite's own explanation states that this
means *nobody looked*.

What the SELinux section does establish is one-directional and still worth having:
every expected capsule operation succeeded with the policy loaded and Enforcing.
That rules out policy blocking the capsule. It does not rule out the capsule doing
something policy would have denied had anyone been able to see it.

## 7. Evidence level

| Claim | Level |
|---|---|
| Namespace, mount, filesystem, credential and IPC isolation | **VM runtime validated** |
| Cross-application separation | **VM runtime validated** |
| Network `none` | **VM runtime validated** |
| Network allowlist | **Not enforced** — disclosed, §6.1 |
| Crash and orphan boundaries | **VM runtime validated** |
| SELinux non-interference | **VM runtime validated** |
| SELinux denial count | **Not measured** — disclosed, §6.2 |
| Camera, GPU, clipboard isolation | **Not established** — inconclusive, §2.2 |
| Anything on physical hardware | **Not established** |

## 8. Evidence

`qualification/capsules/evidence/guest-524107e50b2e/{isolation,crossapp,network,selinux,crash,launcher,resources}.json`,
`runtime_qualify.log`, `dmesg-restrict.txt`, `dmesg-avc-count.txt`.
