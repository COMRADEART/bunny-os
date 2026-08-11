# Guest rebuild — storage, build inputs, and image identity

What had to be true before the image could be rebuilt, what was measured, and
what the rebuilt image actually contains. Deliverables 1, 2 and 3 of the guest
rebuild phase.

---

## 1. Storage and build environment

The previous phase ended with the WSL distribution remounted read-only and every
command failing with an I/O error. That reads like hardware trouble and was not:
the host disk was full.

**Cause, stated plainly.** Three qualification operations each ran
`cp -a "$REPO" "$WORK/bunny-os"`, and the repository contained tens of gigabytes
of generated images under `build/out`. Each copy was 69–72 GB. This was a defect
in the operations tooling, not in the Bunny OS build: the container build context
already excluded those trees through `.containerignore`, and the image build was
never the thing consuming the space.

### Measured before the rebuild

| Measure | Before reclaim | After reclaim |
|---|---:|---:|
| Windows host `C:` free | 15.7 GB | 15.7 GB |
| WSL virtual disk logical size | 578.1 GB | 578.1 GB |
| WSL filesystem used | 373 GB of 1007 GB (39%) | 282 GB of 1007 GB (30%) |
| Build workspace free (inside WSL) | 583 GB | 675 GB |

### What was reclaimed, and what was deliberately kept

* three qualification work copies — **213 GB**;
* five superseded build trees under `build/out` (`beta`, three archived betas,
  one `shell.*.bak`, `live`) — **35 GB**;
* container storage, by name rather than by `system prune -a` — **49 GB**
  (59 GB → 9.8 GB).

Two images were kept because they are not regenerable in the sense that matters:

* `quay.io/fedora/fedora-bootc:44` — upstream rebuilds this daily and old digests
  vanish, so dropping it means the next build silently uses a *different* base
  and the image identity changes without anybody choosing that;
* `localhost/bunny-os-shell:57068ea4b2b5` — the image the previous guest
  qualification ran against, which the committed evidence binds to.

### The host disk did not change, and that is the important part

`fstrim -av` reported 702.8 GiB trimmed inside the guest filesystem. The VHDX
stayed at 578.1 GB and `C:` free stayed at 15.7 GB. **Freeing space inside WSL
returns nothing to Windows** — the virtual disk is not sparse, so it can grow and
never shrinks on its own.

What the reclaim bought is therefore not headroom but *the absence of a reason to
grow*: with ~290 GB of freed extents inside an already-allocated 578 GB file, the
build's writes land in space the file already owns. That is why the rebuild was
attempted on 15.7 GB of host free space, and why the disk stayed between 282 GB
and 297 GB used for its whole duration.

Returning the ~240 GB to Windows requires compaction from an elevated
environment, which qualification tooling deliberately does not automate:

```
wsl --shutdown
# elevated, Hyper-V module present:
Optimize-VHD -Path '<the VHDX for FedoraLinux-44>' -Mode Full
# or:
wsl --manage FedoraLinux-44 --set-sparse true
```

The distribution and its disk identity should be confirmed with `wsl -l -v` and
the actual file listing at the time, not copied from this document.

**Status: not `BLOCKED_STORAGE`.** The build ran and completed.

---

## 2. Build-input audit

### The container context was never the problem

`.containerignore` already excludes `.git`, `build/out`, `node_modules`,
`desktop`, `ui`, and the Python bytecode trees. `tests/image/test_copy_discipline.py`
now asserts the large trees stay excluded, with a control proving the rule file
was actually read — a rule set that parsed to nothing would have passed every
check.

### The qualification tooling had no guard, and now does

`scripts/check-copy-size.py` measures what a copy would move, refuses an
order-of-magnitude miss, and names the directories responsible. Every operations
script that stages a tree calls it first, and the staging itself changed from
`cp -a` to `tar --exclude=build/out --exclude=.git`.

It has **no allowlist**, deliberately. The failure was a directory nobody had
thought about; an allowlist would not have known about that one either. It is
also asserted *absent* from the install routes — a size guard on a running Bunny
OS protects nothing.

The build script no longer archives the previous `build/out/shell` tree before
overwriting it. Archiving was right when the disk had room and is what left five
superseded 8 GB trees behind; the image it held is still in the container store
under its commit tag, which is the copy the evidence binds to.

---

## 3. Image identity

| Field | Value |
|---|---|
| Source commit | `0482f4c90f00445cedd91f7ab56f588fb44261f4` |
| Branch | `feature/bunny-companion-capsules-trust` |
| Profile | `shell` |
| Base image | `quay.io/fedora/fedora-bootc:44` |
| Image reference | `localhost/bunny-os-shell:0482f4c90f00` |
| Recorded at | 2026-08-11T15:58:40Z |
| `SOURCE_DATE_EPOCH` | 1786463293 |
| Build host kernel | 6.18.33.2-microsoft-standard-WSL2 (Fedora 44 under WSL2) |
| podman | 5.8.4 |
| image-builder | 76.0.0 (osbuild 185) |
| qcow2 | 2,965,065,216 bytes, sha256 `f79721572fe18e4b76ccb9843753cee0240aac815a41edb9a37dd023d1116f35` |
| OCI archive | 3,147,130,880 bytes, sha256 `edb17ca59fdb0ff1fb0151b9976ef7d2913adf806948d73b704c702f57f2535a` |
| Repeated-build comparison | **not performed** in this build |

### What the image was verified to contain

Read out of the built image rather than inferred from the source tree:

| Expected | Found |
|---|---|
| `/usr/libexec/bunny-image-tool` | present, **mode 0555**, `#!/usr/bin/python3` |
| `companion/capsule_task_bridge.py` | installed |
| `companion/capsule_tasks.py` | installed |
| catalogue entry for the tool | present in `/usr/share/bunny-os/catalog/images.json` |
| `reset-failed` before launch | present |
| `EXIT_STATUS_UNKNOWN` | present |
| `SubprocessExecutor.diagnostics` | present |
| `--collect` on the capsule unit | **absent** (only the comment explaining why) |
| `StandardOutput=journal` | present |
| content-digest binding | present |
| session-scoped grant | present |
| capsule unit name ends `.service` | present |
| `ReadWritePaths=` on the runtime unit | present |
| tmpfiles rule creating the state roots | present |

All five integration fixes from the previous phase are in the image.

### One thing is not in this image, and it is stated rather than worked around

`/usr/libexec/bunny-session-ready` — the readiness probe — was committed *after*
this build started and is therefore absent. The build is at `0482f4c`; the probe
landed later. It ships in the next build. Until then a graphical run must inject
it the way the capsule qualification harness injects its own tooling, and any
readiness result obtained that way is a result about an injected program rather
than an installed one. That distinction is worth keeping because it is exactly
the distinction the `apptask` section refuses to blur for the image tool.
