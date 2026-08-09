<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny desktop shell report

Branch: `feature/bunny-desktop-shell`
Base: `2e1573a32ce1` (`feature/public-alpha-integration`)
Date: 2026-08-08

## What this phase found

Bunny OS booted to GNOME. The session was `Bunny`, the extension was installed,
and what a user saw after logging in was the stock desktop with a Bunny menu in
the corner. Everything the product promises — the assistant, the character, the
dashboard — existed, and every one of them lived in a window somebody had to
know how to open.

Nothing was broken. That is what made it worth doing: there was no defect to
fix, only a product that had been built as a set of applications and never
assembled into a desktop.

Three things this phase learned that were not visible from the repository, each
of which changed the work:

**The character could not be the one that already exists.** The repository
ships a GLB, a GTK4 GLArea renderer and a full 3D pipeline in
`companion/character/three_d`. None of it is reachable from a desktop shell. A
GNOME Shell extension runs *inside* the compositor process, in GJS, with no GTK
and no GL context of its own, and a Wayland client's surface cannot be
reparented into the compositor's scene graph. That is a protocol boundary, not
an effort estimate, and it is why the figure standing on the desktop is drawn
with Cairo from a data definition while the 3D renderer keeps its window.

**Four separate defects were invisible to every check in the repository and
visible in the first screenshot.** An accessibility constant that does not
exist, an `addChrome` parameter that was removed, an overview that was already
open, and a storage figure that was a true measurement of the wrong
filesystem. None of them is catchable statically; three of them produced a
session that booted cleanly, logged nothing alarming and passed
`vm-shell-smoke`. The harness that photographs the screen is the deliverable
that found them, and it is in the tree.

**A harness defect and a product defect look identical from outside.** The
first graphical run produced a kernel console where the desktop should have
been. The cause was that files `guestfish` creates have no SELinux label, so
`accounts-daemon` could not read the autologin record and GDM exited eleven
times. Had that not been chased into the guest's own journal it would have been
reported as "the desktop does not start".

---

## 1. Architecture discovered

| Question | Answer |
| --- | --- |
| Display server | Wayland, via Mutter |
| Compositor | GNOME Shell 50 — `build/packages/shell.txt` states outright that Bunny Shell is "an integration layer on GNOME/Mutter, not a compositor" |
| Session entry | GDM offers `Bunny` and `Bunny (Safe Shell)` from `/usr/share/wayland-sessions`; both exec `/usr/libexec/bunny-shell-session`, which exports `BUNNY_SHELL_MODE`, starts `bunny-shell.target` and then `exec`s `gnome-session` |
| Existing shell surface | `bunny-shell@bunny-os.org`, a single 132-line `extension.js` adding one panel indicator and seven keybindings |
| Other UI | Python GTK4 programs (`bunny-launcher`, `bunny-settings`, `bunny-command`, …) and the companion window, all ordinary application windows |
| "The blue screen" | Stock GNOME with Fedora's default background. There was no Bunny-drawn desktop of any kind |
| Layer shell | Not available. Mutter does not implement `wlr-layer-shell`, and no `gtk4-layer-shell` is packaged |
| Install mechanism | `build/scripts/install_routes.py` declares every path that reaches the image, once, read by both the installer and the closure analyser |

### Why an extension, and not something else

| Option | Why not |
| --- | --- |
| Replace the compositor | Puts the boot path, the display-stack qualification and the TPM/Secure Boot evidence at risk to gain nothing the extension cannot do |
| GTK4 window at a background layer | Needs `wlr-layer-shell`, which Mutter does not implement. Under Mutter it would be an ordinary window in the stack |
| Reparent the existing 3D window into the shell | Not possible on Wayland. Protocol boundary |
| **GNOME Shell extension (chosen)** | It *is* the desktop; native Clutter; no new process; no new package; the session, the install routes, the gates and the safe-shell path are all unchanged |

The whole change is additive. `bunny-shell-session.py`, `bunny.desktop`,
`bunny-safe.desktop`, the systemd units, the Containerfile, the profiles and
every gate are untouched.

---

## 2. Graphical stack used

St and Clutter actors inside the compositor process, in GJS, with Cairo for the
character, the dials, the network graph and the floor glow. No new runtime
dependency and no new package for the shell itself — the only package added in
this phase is an emoji font, and the reason is in §7.

Actors go in two layers:

* **Chrome** — top bar, sidebar, dock, toasts, search results, power menu —
  through `Main.layoutManager.addChrome`, above windows, hidden automatically
  under a fullscreen window.
* **Desktop content** — character, cards, bubbles, contrast scrim — into
  `Main.layoutManager._backgroundGroup`, beneath `global.window_group`, so an
  open window covers the dashboard the way it covers a wallpaper.

`_backgroundGroup` is private API; the fallback inserts into `uiGroup` below
`window_group`, reaching the same place by a different route, and logs which
one it took.

---

## 3. Files created

**The desktop** (`shell/components/gnome-shell-extension/`, 34 new modules):

```
lib/tokens.js  layout.js  animation.js  util.js  widgets.js
lib/desktopShell.js  topBar.js  sidebar.js  bottomDock.js
lib/wallpaperLayer.js  notificationLayer.js
lib/cards/base.js  systemOverview.js  quickAccess.js  mediaWidget.js
              agendaWidget.js  systemMonitor.js
lib/character/state.js  definition.js  renderer.js  viewport.js
lib/assistant/bubble.js  suggestions.js  panel.js
lib/services/telemetry.js  power.js  network.js  audio.js  brightness.js
                launcher.js  mpris.js  agenda.js  assistant.js  search.js
```

**The assistant bridge**: `shell/services/bin/bunny-shell-assistant`.

**The wallpaper**: `shell/assets/wallpapers/bunny-nocturne.svg`.

**The VM harness**: `build/scripts/vm-desktop-story.sh`, `desktop-inject.sh`,
`desktop-probe.py`, `qmp-screendump.py`, `ppm-to-png.py`.

**Tests**: `tests/shell/test_desktop_shell.py` (42 tests).

## 4. Files modified

| File | Change |
| --- | --- |
| `shell/components/gnome-shell-extension/extension.js` | Boots `DesktopShell` behind a setting and a recovery path; the indicator is unchanged |
| `…/stylesheet.css` | Rewritten as the desktop's visual layer |
| `…/metadata.json` | Description and version 2 |
| `…/schemas/…gschema.xml` | `desktop-enabled`, `desktop-blur`, three focus keybindings |
| `shell/components/dconf/10-bunny-shell` | Wallpaper default, dark colour scheme, gradient fallback |
| `build/packages/desktop.txt` | Emoji fonts — see §7 |
| `release/validation.py` | The extension validator now reads 35 modules instead of 1, and resolves the import graph |
| `docs/BUNNY_SHELL.md`, `DESIGN_SYSTEM.md`, `VISUAL_IDENTITY.md` | The desktop, the two palettes, the wallpaper's composition |
| `.gitattributes` | `shell/services/bin/**` and `installer/bin/**` are `-text` |

No install route was added. Every new file reaches the image through routes
that already existed, which is the property `install_routes.py` exists to have.

---

## 5. System integrations implemented

| Reading | Source | Verified in the VM |
| --- | --- | --- |
| CPU load | `/proc/stat`, delta between samples | 1% on an idle guest |
| Memory | `/proc/meminfo`, `MemAvailable` | 1.1 GB / 5.8 GB |
| Storage | `statfs` on the home directory | Corrected — see §7 |
| Temperature | hwmon by name, thermal zone fallback | `Unavailable`, correctly — the guest has no sensor |
| Battery / AC | `/sys/class/power_supply` | `AC Power`, correctly — the guest has no battery |
| Network throughput | `/proc/net/dev`, monotonic delta | `↑ 0 B/s ↓ 0 B/s` on an idle guest |
| Connection state | NetworkManager, `Gio.NetworkMonitor` fallback | Connected |
| Volume | `Gvc.MixerControl` | Indicator present |
| Brightness | `org.gnome.SettingsDaemon.Power.Screen` | Hidden — no backlight in a VM |
| Applications | `Shell.AppSystem` | Present ones launch; absent ones named in the journal |
| Media | MPRIS over the session bus | Card collapsed — nothing playing |
| Calendar | `org.gnome.Shell.CalendarServer`, local-file fallback | "Nothing scheduled today" |
| Power actions | `org.gnome.SessionManager`, logind for suspend | Menu present |
| Assistant | `bunny-shell-assistant` → `companion.protocol` | See §9 |

**No metric has a fallback value.** A reader that cannot answer returns nothing
and the widget prints `Unavailable`. Two tests enforce it: no reader may
contain `?? 0` or `|| 0`, and the wording has one definition.

---

## 6. Character implementation status

| Piece | State |
| --- | --- |
| `CharacterStateManager` | Complete. Ten states, transient states return by themselves, `error` does not, sleep after five idle minutes |
| Runtime binding | Complete. The companion's own presentation phase drives the state; a test compares the mapping against `companion.presentation.PRESENTATION_PHASES` |
| Renderer interface | Complete. `attach`/`setState`/`setLevel`/`setSize`/`destroy` |
| Vector renderer | **Implemented and rendering.** Cairo, from `definition.js`; breathing, blink, arm lift, head tilt, lean, mouth, per-state rim light |
| Image renderer | Implemented, not default. Plays a character package's frames |
| GL / GLB renderer | **Not implemented in the shell**, and cannot be — see §1. It remains the companion window's |
| Floor glow | Complete. Colour and intensity follow state |
| Click to open | Complete |

The figure is a young adult in a dark hoodie with the Bunny mark on the chest,
dark trousers and pale sneakers, lit from the left in violet. Every colour and
proportion is data; a replacement character is a different object of that shape.

---

## 7. What the screenshots found

The harness photographs the emulated framebuffer through QMP at four increasing
delays. Everything below was found by looking at those pictures, and none of it
was catchable by any static check.

| Run | Result | Cause |
| --- | --- | --- |
| `run1` | Kernel console; `gdm.service` exited 1, restarted 11 times | **Harness.** `guestfish`-created files have no SELinux label; `accounts-daemon` was denied on the autologin record and GDM gave up |
| `run5` | Recovered GNOME session on the Bunny wallpaper | **Product.** `Clutter.AccessibleRole` does not exist — roles are `Atk.Role` — so a screen-reader hint threw and took the desktop with it |
| `c1` | One unsized bar in the corner, GNOME's bar beside it | **Product.** `addChrome` rejects `affectsInputRegion`, and it parents the actor *before* validating, so the constructor aborted mid-way |
| `c2` | Top bar, sidebar and dock, with GNOME's overview drawn over the middle | **Product.** GNOME opens the overview at login; it was already open, so `showing` had fired before anything was listening |
| `c3` | **The desktop.** Everything below | Three residual defects, all fixed |
| `c4` | The desktop, with all three fixed | Storage 4.4 GB / 8.3 GB, emoji drawn, figure reproportioned |
| `c5` | Unchanged from `c4`; the assistant bridge ran and answered | Bridge answered about the wrong account — a probe defect, fixed |
| `c6` | **Confirmation.** Desktop unchanged, bridge reaches the live runtime | — |

`c3` also produced three findings that only a picture could give:

* **Storage read "14.2 MB / 14.2 MB"** on a machine with a 14 GB partition. A
  real measurement of the wrong filesystem — `/` is an ostree composefs mount.
  The `Unavailable` discipline does not help here, because a confident wrong
  answer is indistinguishable from a right one. Now measured on the home
  directory, with the path in the accessible description.
* **Every emoji was a tofu box.** The image ships sans and CJK fonts and no
  emoji font at all. Removing the emoji was the wrong trade — an OS whose
  desktop cannot draw one cannot draw one in a file name or an assistant reply
  either — so the font is installed.
* **The character read as a robed figure.** A torso 45 units wide reaching to
  y=89 of 150 put the hem at the knee and the shoulders wider than the stance.
  Corrected in the definition: 7.2 heads tall, hem at y=80, longer legs.

---

## 8. Remaining placeholders

| Thing | State |
| --- | --- |
| Suggested actions | The *list* is contextual from what the desktop can see — time of day, runtime reachability, what is installed. The *wording* of the three assistant prompts is fixed text |
| Agenda | Real provider, no demo data. Empty state on a machine with no calendar, deliberately — see `services/agenda.js` |
| Speech input | Hands off to `bunny-command --listen`; the shell opens no capture stream of its own |
| Bubble waveform | Follows the state's rhythm, not a measured level, and says so. The shell does not have the capture stream and should not |
| Notifications | The desktop's own toasts only. GNOME's message tray is untouched — replacing it is a phase of its own |
| Sidebar collapse | Implemented and driven by the breakpoint; there is no manual toggle yet |
| Reduced transparency | Not implemented. Reduced motion is |

---

## 9. Tests executed

| Suite | Result |
| --- | --- |
| `tests/shell/test_desktop_shell.py` | 42 tests, all passing |
| `scripts/task.py test` (Windows) | 4361 tests, 1 error — `test_duplicate_boot_check_is_load_bearing` needs symlink privilege; pre-existing and environmental |
| `scripts/task.py test` (Fedora, as `bunny`, ext4) | Passing, inside the source gate |
| `scripts/task.py validate` (Fedora) | PASS, 15 validators, ShellCheck included |

Three of the new tests cross the language boundary, which is the only place a
compiler would have helped and there is not one: the layout solver runs under
`node` at seven resolutions with every pair of rectangles compared; every
companion presentation phase must map to a character state; every colour token
must appear in the stylesheet.

The strengthened extension validator was given a negative control before it was
trusted — renaming `glass` to `glassy` in one import produced a FAIL naming the
file and the symbol, and the pass returned when it was reverted.

---

## 10. Gate results

Measured on the Fedora 44 reference host, as user `bunny`, from the ext4 copy —
not `/mnt/c`, and not as root.

```text
source gate: PASS
  ok      baselineRecorded
  ok      licenceGatePassed
  ok      minimisationComplete
  ok      qualificationSuitesPass
  ok      repositoryValidation
  ok      sourceSuitesPass
```

```text
repository validation: PASS
  ok    JSON parsing                     316 documents parsed
  ok    Schema validation                49 schemas
  ok    Python compilation               775 files compiled in memory
  ok    Shell syntax                     77 scripts parsed by bash -n
  ok    ShellCheck                       77 scripts, no suppression
  ok    Desktop entries                  10 entries (2 session, 8 launcher)
  ok    XML and SVG                      10 XML/SVG assets parsed
  ok    Licence headers                  686 declarations over 888 files
  ok    Workflow YAML                    6 workflows parsed
  ok    Committed evidence consistency   26 record(s) agree
  ok    GNOME extension syntax           35 modules parsed, imports resolved
  ok    systemd unit programs            23 units, 1 recorded gap(s)
  ok    Shell layout                     7 required shell directories
  ok    Capability manifests             14 manifests
```

A passing source gate asserts nothing about a built image or a booted system.
That is what §11 and §12 are for.

---

## 11. Image build result

Profile `shell-test`, built on the Fedora 44 reference host from
`/root/bunny-os`:

```text
build/out/shell-test/
  bootc-fedora-44-qcow2-x86_64/bootc-fedora-44-qcow2-x86_64.qcow2
  bunny-os.oci.tar        2,056,140,800 bytes
  provenance.json  normalisation.json  SHA256SUMS
```

`/usr/lib/os-release` in the built image, read from inside the running guest:

```text
NAME="Bunny OS"
BUNNY_OS_PROFILE=shell-test
BUNNY_OS_CHANNEL=development
BUNNY_OS_COMMIT=<the commit built>
```

All 35 desktop modules and the compiled gschema reached
`/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org/`, confirmed from
inside the guest, not from the build log.

---

## 12. VM boot result

Confirmation run `c6`, image built from `a704125a1182`, booted under QEMU/OVMF
at 1920×1080 with GDM autologin into the `bunny` Wayland session. Screenshots
taken from the emulated framebuffer through QMP at t=120, 180, 240 and 300
seconds. The desktop is present in all four.

Read from inside the guest after the graphical target settled:

```text
extension state:   ENABLED        (no error attached)
modules installed: 35             + compiled gschema
sessions:          1 1000 bunny  -      manager
                   2 1000 bunny  seat0  user  tty2
wallpaper:         file:///usr/share/backgrounds/bunny-os/bunny-nocturne.svg
                   present, 5609 bytes
assistant bridge:  available, /run/user/1000/bunny-companion/runtime.sock
renderer:          mutter reports software; panel blur disabled accordingly
```

On screen at 1920×1080:

* **Top bar** — Bunny mark and wordmark; `Search anything...`; volume, network
  and brightness indicators; `AC`; `23:48 Sat 8 Aug`; the user's initials.
* **Sidebar** — Home (selected, violet rule), AI Assistant, Files, Apps,
  Settings, divider, Terminal, Store, and Power apart at the bottom.
* **Greeting** — "Good evening, Bunny 👋" over "How can I help you today?".
* **Character** — standing centre, dark hoodie, violet Bunny mark on the chest,
  dark trousers, pale sneakers with violet accents, violet floor glow beneath.
* **System** — 1% dial, RAM 1.1 GB / 5.8 GB, Storage 4.4 GB / 8.3 GB, Temp
  `Unavailable`.
* **Quick Access** — Files, Bunny and Bunny Approvals live; VS Code, OBS,
  Blender, Discord and Spotify dimmed and marked not installed.
* **Today's Agenda** — "Nothing scheduled today", with `View Calendar`.
* **Network & Power** — ↑ 0 B/s ↓ 0 B/s, the graph, `Battery — AC Power`.
* **Bunny** — the assistant card, with `Ask anything...`, microphone and send.
* **Suggested actions** — four, contextual to what this machine has.
* **Dock** — Bunny Assistant, Files, Terminal, Applications. Browser, VS Code
  and Spotify are absent because they are not installed, which is the dock's
  documented behaviour.

### Against the acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Bunny OS boots | Yes |
| 2 | The Bunny desktop instead of the plain screen | Yes |
| 3 | Top bar visible | Yes |
| 4 | Sidebar visible | Yes |
| 5 | Bottom dock visible | Yes |
| 6 | Wallpaper renders | Yes |
| 7 | Character in the centre | Yes — vector, not 3D; see §6 |
| 8 | Cards arranged around the character | Yes, five |
| 9 | Files and Terminal can launch | Both resolve and are in the dock. **Not clicked** — the harness has no pointer |
| 10 | Time and system information from the OS | Yes, every figure in §5 |
| 11 | No major overlap at 1920×1080 | None between desktop elements. The companion window opens over the character — a window, covering the desktop as windows do |
| 12 | Gates still pass | Source gate PASS on the reference host |

Criterion 9 is the honest gap in this run: the tiles exist and the applications
resolve, and nothing has pressed one. `vm-desktop-story.sh` photographs; it does
not click.

---

## 13. Known limitations

1. **The in-shell character is 2D vector, not 3D.** It cannot be otherwise
   inside the compositor; see §1. The 3D renderer remains the companion
   window's, and the two are different implementations of the same character.
2. **Measured only on llvmpipe.** Every VM run reported software rendering.
   Nothing here has been seen on a GPU, and `desktop-blur` has therefore never
   been exercised in its enabled state on real hardware.
3. **One monitor.** The layout solves for the primary monitor. A second monitor
   gets the wallpaper and nothing else.
4. **Two palettes.** The GTK surfaces are still evergreen and mint; the desktop
   is violet. St cannot read the JSON token file, so a single source would have
   to be compiled into both at build time. Recorded in `docs/DESIGN_SYSTEM.md`.
5. **`_backgroundGroup` is private API.** There is a fallback and it is logged,
   but a Shell release that changes the scene graph will need attention.
6. **The companion window opens over the character.** It is an ordinary window
   and windows cover the desktop; the interaction between the window and the
   in-shell figure is a product question this phase did not answer.
7. **No user has used it.** Everything in this report is a measurement of a
   machine, including the screenshots. Nobody has clicked anything: no dock
   tile has been pressed, no search has been typed, no request has been sent
   to the assistant through the interface, and no state transition of the
   character has been driven by a real task. The bridge is proved to reach the
   runtime; the path from a keystroke to a reply on screen is not.
8. **`shell-test`, not the Alpha image.** The desktop was built and booted in
   the profile whose purpose is exercising the shell. The Alpha payload and the
   installer ISO have not been rebuilt on this branch.
