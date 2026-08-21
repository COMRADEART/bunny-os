# The Graphical Session

**What this is** Whether a Bunny OS image, booted from nothing, reaches a session a
person could use — and how that question was made answerable instead of guessed.

**Image** profile `shell`, built from the branch under qualification
**Harness** `build/scripts/vm-desktop-story.sh` → QEMU with `virtio-vga`, `virtio-tablet-pci`, QMP `screendump`, AT-SPI
**Verdict** Ready, with all eight conditions true and the marker observed on the serial console.

---

## 1. The problem this replaces

Every graphical harness in this repository had, at some point, waited a fixed
number of seconds and photographed whatever was on screen. That is how a
screenshot of GDM and a screenshot of a blanked screen both got recorded as "the
desktop".

A delay is not a readiness condition. It is a guess that happens to be right on
the machine it was tuned on, and it fails in the direction that looks like success.

`scripts/bunny-session-ready.py` replaces the guess with a conjunction of eight
conditions, each separately true or false, each measured from the running system
and reported **by name**. It prints one JSON document always, and the line
`BUNNY_SESSION_READY` on its own **only** when every condition holds. The marker is
what a serial console can be grepped for; the JSON is what says which condition was
false when it is not.

Exit status is 0 when ready and 1 when not, so a shell can wait on it in a loop
rather than sleeping.

## 2. The eight conditions

| Condition | Asks | Observed |
|---|---|---|
| `session` | logind: does this user have an **active** graphical session? | `userState: active`, `hasGraphicalSession: true` |
| `compositor` | Does a Wayland display exist, with gnome-shell under it? | `wayland-0`, socket exists, shell running |
| `shell` | Is the Bunny Shell extension loaded, and **not in error**? | `bunny-shell@bunny-os.org`, state `1.0` (ENABLED) |
| `companion` | Is the Companion runtime active, and not crash-looping? | active, **0 restarts** |
| `client` | Does the Companion's own socket answer? | `/run/user/1000/bunny-companion/runtime.sock`, connected |
| `trust` | Is the trust store readable and the gate constructible? | `/home/bunny/.local/share/bunny/trust/grants.json` |
| `capsules` | Is a **confining** backend available? | confining `['flatpak','bubblewrap']` |
| `tasks` | Did the task runtime accept a status request, and are the programs present? | `['image.resize']`, `missingPrograms: []` |

```
markerSeen: true    notReady: []    ok: true
```

### 2.1 Four of the eight are worded to defeat a specific false pass

- **`shell` asks GNOME, not the filesystem.** An extension directory that exists is
  not an extension that loaded. GJS errors are silent from outside; the shell's own
  state enum is not.
- **`companion` counts restarts.** Sampling "is it active right now" passes on a
  unit that is crash-looping, because it is active for part of every cycle.
- **`capsules` requires a *confining* backend.** `systemd-scope` is present on every
  systemd machine, carries a cgroup, and confines nothing. A session that would run
  the first application unconfined is not a ready Bunny session, so `systemd-scope`
  alone fails this check by design.
- **`tasks` checks for the program, not the package.** The operation table names
  `/usr/libexec/bunny-image-tool`; a package that installs libraries but not the
  binary satisfies a dependency check and fails this one. (This is the shape of a
  defect already recorded once in this project: pipewire arrived without `paplay`.)

## 3. The Companion window unit is deliberately inactive

`bunny-companion-window.service` shows `activeState: inactive` and this is a
**pass**, not a tolerated failure.

The unit is disabled by preset in `config/systemd/60-bunny-os-user.preset`. The
GNOME Shell extension has its own assistant surface — the character, the input
field, the approval panel — and the separate GTK window covered the character it
was supposed to accompany. Readiness treats the window as optional-if-present: a
profile without it is a real configuration; a profile that *has* it and cannot
start it is a failure.

The distinction is expressed in the source as two lists, `REQUIRED_USER_UNITS` and
`OPTIONAL_USER_UNITS`, rather than as a special case in a condition.

## 4. How the desktop is observed

Three instruments, because no one of them can answer the whole question:

| Instrument | Answers |
|---|---|
| QMP `screendump` | What is actually on the screen — the only thing that catches a shrug, a blank, or a covered character |
| AT-SPI accessibility tree | What controls exist, their names, roles and screen extents |
| `virtio-tablet-pci` absolute pointer | Presses a real button at real coordinates |

The pointer is absolute rather than relative because a relative device needs to
know where the cursor started, and on a freshly booted compositor it does not.

**The screenshot is not decoration.** The blocker that held this phase for three
cycles was diagnosed from a photograph — the words *"the runtime did not finish
within the deadline"* were on screen the whole time and identified the defect
immediately, after nine text-only diagnostics had not. A harness that records only
JSON cannot see a product that is wrong in a way nobody thought to assert.

## 5. Harness faults found along the way

Nine, on the graphical journey alone. In every one of them **the product was
correct and the instrument was lying**, which is the failure mode that costs the
most time, because it produces confident wrong answers rather than errors:

| Fault | What it reported |
|---|---|
| `_run` returned a dict, unpacked as a tuple | Killed the probe; every later answer `null` |
| One raising command killed the whole probe | Same, from any single bad command |
| `WAYLAND_DISPLAY` missing from the probe environment | "No compositor" on a desktop that was drawing |
| Polling the whole tree every 2 s | Stalled the instrument; reported an empty desktop |
| Kept only parsed controls | "0 seen" indistinguishable from "never ran" |
| Keyboard shortcut did not fire, no pointer fallback | "The assistant did not open" |
| `listening` check stricter than the working path | "The assistant did not hear it" |
| Journey ran third; the assistant answers one request per session | "No response" |
| Walk depth raised 12→20 on a wrong theory | Broke a working instrument (deeper walk times out) — reverted |

The last row is the one worth keeping: **a change made to fix a failure, on a
theory that was never tested, broke an instrument that had been working.** It was
found and reverted only because the previous depth was recorded.

## 6. Evidence level

| Claim | Level |
|---|---|
| The image boots to a graphical session | **VM runtime validated** |
| All eight readiness conditions hold | **VM runtime validated** |
| The Bunny Shell extension loads and reports ENABLED | **VM runtime validated** |
| The Companion runtime is active and not looping | **VM runtime validated** |
| A confining capsule backend is present in the session | **VM runtime validated** |
| Anything on physical hardware | **Not established** |
| Multi-monitor, HiDPI, hardware GPU | **Not established** |

## 7. Evidence

`qualification/capsules/evidence/journey-*/journey.json` (the `readiness` block),
`screens/*.ppm`, `serial-tail.log`. The readiness probe itself is
`scripts/bunny-session-ready.py`; the harness is
`build/scripts/vm-desktop-story.sh` with `desktop-drive.py`, `desktop-probe.py`
and `desktop_interaction.py`.
