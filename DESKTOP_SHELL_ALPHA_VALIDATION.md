<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny desktop shell — Alpha validation

Branch: `feature/bunny-desktop-shell`
Candidate: `be7e3d281fc1782c08263215b35da83cca490428`
Base: `6eeda81ec8cd` (the desktop shell phase)
Date: 2026-08-09

Four Alpha images were built on this branch and every one of them was booted.
The earlier three are listed because each was built to answer a question its
predecessor raised on screen, and the sequence is the evidence:

| Commit | What its boot showed |
| --- | --- |
| `a4d45905484c` | Every criterion in §8 passed. At 1366×768 the System card's figures were ellipsised: `3.9 GB…` |
| `520dfa2a6f50` | A shorter string fixed RAM and not Storage — the 96-pixel dial was taking the room |
| `e440b4960829` | A smaller dial fixed neither: "Storage" is four characters longer than "RAM" |
| **`be7e3d281fc1`** | **The candidate.** Below the compact breakpoint the card stacks, and every figure is whole |

Three attempts at one truncated label is more than it deserved, and the reason
it took three is worth keeping: each fix was a piece of arithmetic about how
much room a string needs, and each was checked by rebuilding and looking. The
one that worked stopped doing arithmetic — below the breakpoint the figures go
under the dial and have the card's full width, so no label length can be wrong.

## What this phase was for

The desktop shell phase ended with twelve acceptance criteria, eleven met, and
one sentence that was the reason for this one:

> Criterion 9 is the honest gap in this run: the tiles exist and the
> applications resolve, and nothing has pressed one. `vm-desktop-story.sh`
> photographs; it does not click.

Everything the desktop was known to do, it was known to do because a program had
asked it a question. That is a real form of evidence and it has a specific blind
spot, which this phase went looking for and found four times.

**Nothing that had never been pressed worked.** The power menu still passed
`affectsInputRegion` to `addChrome` — the exact parameter that aborted the first
graphical boot, removed from one call site and left in the other, on a control
no test could reach. `shop-symbolic` had been the sidebar's Store icon since the
sidebar was written and adwaita-icon-theme has never shipped it, so that row had
drawn a broken-image placeholder on every boot. `battery-level-100-charging-symbolic`
does not exist either — adwaita breaks its own naming pattern at the top of the
range — so a laptop plugged in at 100% got the same placeholder. The character's
pose table had named `accent: 'success'` since the day it was written and the
palette had no such colour, so the documented "success turns the rim green" had
never once happened on a screen.

Each of those is a string that parses, a name that resolves, a file that lints.
None of them could be caught by anything that did not either press the control
or compare the name against the thing it names.

---

## 1. Candidate

| | |
| --- | --- |
| Branch | `feature/bunny-desktop-shell` |
| Commit | `be7e3d281fc1782c08263215b35da83cca490428` |
| Working tree | clean at the candidate commit |
| Reference host | Fedora 44, as user `bunny`, from the ext4 checkout |

The Alpha artifact in §6 and every measurement in §7 to §10 come from
`be7e3d281fc1`. The commit that carries this document is its child and changes
nothing but this file, which reaches no install route and is not copied into the
image; `docs/` is a build COPY root and the repository root is not, which is why
reports live here.

## 2. Architecture

Unchanged from the previous phase and deliberately so. GNOME Shell 50 on
Mutter/Wayland; the Bunny desktop is a GNOME Shell extension
(`bunny-shell@bunny-os.org`) running inside the compositor process in GJS, with
chrome through `Main.layoutManager.addChrome` and desktop content in the
background group beneath `global.window_group`. No compositor was replaced, no
display server was added, no new process runs.

Three modules were *split* rather than added, and the split is the same one in
each case: the half that can be evaluated without a compositor was separated
from the half that needs St, so that a claim about it can be checked by a test
instead of by a boot.

| Pure module | What it decides | Checked by |
| --- | --- | --- |
| `lib/layout.js` (existing) | where every panel goes | `node`, seven resolutions, every pair |
| `lib/services/storage.js` | which filesystem "Storage" means | `node`, six fixture mount tables |
| `lib/iconNames.js` | every icon name the desktop can draw | `node`, against the icon theme's own file list |
| `lib/character/figure.js` | the figure itself | `gjs`, against the rendered pixels |

---

## 3. Changes

### 3.1 Application interaction — the harness that presses things

`vm-desktop-story.sh` photographed the screen and had no pointer at all. It now
has one, and the reason it did not is worth stating: QMP `input-send-event` can
only deliver absolute coordinates to a device with absolute axes, and the guest
had no such device. Two were added:

* `virtio-tablet-pci` — an absolute pointer. Clicks are injected at the QEMU
  device layer, so they arrive at the guest kernel from an emulated tablet, go
  through evdev and libinput, and reach Mutter as ordinary hardware input.
  Nothing in the guest can tell them from a person.
* `virtio-serial` + `virtserialport` — a two-way channel to the injected probe.

The split of responsibility is the point. The host holds the interaction script
and can inject input; the guest holds the evidence and can see a systemd unit.
Neither can produce the other's half, so neither can fake it.

`build/scripts/qmp-input.py` sends the events. `build/scripts/desktop-drive.py`
runs the script. `build/scripts/desktop_interaction.py` is the guest's half:
it locates controls through AT-SPI — which reports Clutter's *actual* allocation
of an actor rather than what the layout solver intended — and reports four
independent signals per application (systemd unit, process, session bus name,
AT-SPI window).

Three defects in this harness were found by running it, and each had produced a
confident wrong answer first:

1. The guest announced its targets before the host attached, and QEMU discards
   what a guest writes to a chardev with no client. Replaced with a handshake.
2. The accessibility tree came back whole and was truncated at 8000 characters
   by the probe's own output cap, so it failed to parse and the run reported
   "the guest exposes 0 named controls" on a session that had exposed 311.
3. The chord `Alt+F4` was sent as one input event, so the modifier and the key
   arrived in the same evdev frame and Mutter saw F4 with no Alt. Nautilus
   appeared to close because the harness sent `Ctrl+W` afterwards and Nautilus
   answers it; the terminal, which does not, stayed open and made it visible.

One property of the machine under test also had to be turned off: a session that
idles into the lock screen switches to the `unlock-dialog` session mode, which
disables every extension that does not declare that mode — and the Bunny desktop
deliberately does not, because a dashboard drawing behind a lock screen would
show a locked machine's calendar to whoever is standing in front of it. A run
that waited seven minutes found the desktop "absent" on a session that had been
correct four minutes earlier.

### 3.2 Storage selection

The `14.2 MB / 14.2 MB` reading was a true measurement of an ostree composefs
root. The fix that followed it — `statfs($HOME)` — produced the right figure on
the image it was tried on for the wrong reason, and would have reported a
tmpfs's capacity on a live session without saying anything had changed.

`lib/services/storage.js` reads `/proc/self/mountinfo`, finds the mount that
actually backs each candidate path (longest matching mount point, highest mount
id — which is how `/var/home/bunny` gets attributed to `/var` and not to `/`),
classifies it, and takes the first persistent one. Rejected: `tmpfs`, `ramfs`,
`devtmpfs` and the kernel pseudo-filesystems (do not survive a reboot);
`overlay`, `composefs`, `squashfs`, `erofs`, `iso9660` (a composed image, not a
disk); anything mounted `ro`; and `/boot`, `/efi`, `/run`, `/tmp` (real,
writable, and not user storage).

Order: the signed-in user's home, then any home filesystem, then the primary
writable disk (`/sysroot`, `/var`, `/`), then — for a machine whose data lives
on a partition none of those names — the shallowest remaining persistent mount.
With none, `Unavailable`, and the reason each candidate was skipped is carried
out and logged rather than discarded.

Returned: mount point, filesystem type, total, used, free, and whether it is
considered persistent. The mount point and free space are in the row's
accessible description, because Storage is the only figure on that card whose
*subject* is a choice rather than the machine.

### 3.3 Glyphs

Every emoji is gone from every string a user can see. The greeting's `👋`, the
bubble's `☀`, the four suggestion chips and the `↑`/`↓` on the throughput rows
are now themed icons or plain text. The emoji fonts stay installed — an
operating system that cannot draw an emoji in a file name or a message is a
different defect — but no *control* depends on one.

The stronger half is the audit that came with it. Every icon name the desktop
can draw is declared in `lib/iconNames.js`, which imports nothing; the test
suite compares that list against `tests/shell/data/adwaita-icon-inventory.txt`,
read out of `adwaita-icon-theme-50.0-1.fc44` — the package the image installs.
No other module may contain a `-symbolic` literal at all, which is what makes
the list complete rather than one somebody maintains. Two names failed on the
first run of that check and both had been shipping.

At runtime `themedIcon` asks the live icon theme as well and falls back to the
Bunny mark with a journal line, so the worst case is the wrong picture beside
the right label rather than a broken-image box.

### 3.4 The character

It read as a robed figure on two separate booted images. The proportions changed
between those attempts and the reading did not, which is the useful part: the
problem was never the proportions.

* **The hem was the bottom of a capsule.** A capsule ends in a semicircle, so
  the garment finished in a dome *wider than the hips it sat over* — 16 units
  against 14.5. That is a robe, drawn exactly as specified, and no change to the
  hem's height could fix it. The hoodie now has a hem of its own: a flat edge,
  narrower than the shoulders, with a ribbed band under it. That band is the
  single most important shape in the file.
* **The legs touched.** 11 apart with 10.4-wide thighs left a 0.6-unit gap,
  which at this size is no gap: two legs merged into one mass under a wide hem,
  which is a skirt. Now 15 apart at 9.5 wide — 5.5 units of background between
  them.
* **Nothing separated the arms from the body.** The sleeves were the same colour
  as the torso and started inside it, so the outline from shoulder to hem was
  one unbroken shape. The sleeves now have their own shading, a cuff in the same
  rib colour as the hem, and a hand below the cuff.

Proportions did change too — 6.3 heads rather than 5.8 — but that is the smaller
half. Added: ears, a collar the neck comes out of, a kangaroo pocket, drawstrings
with aglets, knee and ankle tapers, a trouser turn-up above the shoe, and the
Bunny mark on the chest.

`lib/character/figure.js` was split out with only a `cairo` import, so the
figure can be drawn to a PNG in about a second — `gjs -m
build/scripts/render-character.js` — instead of by building an image and
photographing a virtual machine. That is what caught the rim light: it had been
stroking a straight line down the torso and another down the leg, and once the
arms moved outboard those two strokes sat at almost the same x, ran nearly the
figure's whole height and were drawn over the sleeve, so the character appeared
to be holding a coloured staff. It is unmistakable in the contact sheet and
would not have been visible in source review.

State visualisation: the palette gained the three accent colours the pose table
had been naming since it was written, so success turns the rim and floor glow
green and error turns them red for the first time. Four states also gained a
small mark beside the head — listening's arcs, thinking's dots, working's
turning ring, warning and error's bar-and-dot — chosen because those are the
states a person cannot otherwise tell apart at a glance without reading the
bubble.

### 3.5 Failure isolation

Three separate graphical boots have died over a single call — an Atk role looked
up on Clutter, a parameter `addChrome` no longer accepts, a private field that
moved. In each case the desktop was correct except for one line and the user got
no desktop.

Construction is no longer one unbroken sequence. Every optional service and
every widget is built through `_optional`, which returns the component or null,
names the failure in the journal, and records it in `degraded`; a toast tells
the user what did not start. Cards whose service failed to construct are not
built over a null — a media card with no MediaService is not a degraded card,
it is a card with nothing to say.

The `try` around the structural steps stays, because a throw that escapes
`_optional` means placing the layers or connecting the session failed, and that
is not a degraded desktop but debris in the compositor's scene graph; there,
tearing down and letting `extension.js` fall back is still right.

A test refuses an unguarded dereference of anything that can be null.

---

## 4. Tests

Run on the Fedora 44 reference host as `bunny` from the ext4 checkout.

| Suite | Result |
| --- | --- |
| `tests/shell/test_desktop_shell.py` | 79 tests, all passing |
| `python3 scripts/task.py test` (full) | see §5 |
| `python3 scripts/task.py validate` | PASS, 15 validators |

New coverage, by the defect each guards:

| Tests | Guards |
| --- | --- |
| `StorageSelectionTests` (10) | composefs root, composefs + persistent home, ordinary ext4, tmpfs-only, read-only root, separate data partition, `/boot` never chosen, the skip reason is carried |
| `IconTests` (6) | every declared name exists in the icon theme; every Bunny name has an SVG; `shop-symbolic` is gone; no module writes a name inline; a miss falls back rather than drawing a broken image |
| `EmojiTests` (3) | no user-facing string carries an emoji, dingbat, arrow or geometric shape — checked against string literals by a scanner, so a comment may still name the glyph it replaced |
| `CharacterFigureTests` (7) | rendered pixels: two legs, daylight between them, the silhouette loses half its ink at the hem, the head is narrower than the shoulders and is one shape, 5.8–7.5 heads tall |
| `CharacterStateVisualisationTests` (3) | every state declares an indicator; every pose accent is a real palette colour; `figure.js` imports no GI namespace |
| `FailureIsolationTests` (4) | `affectsInputRegion` appears nowhere; optional components are built through the guard; failures are recorded *and* logged; no unguarded dereference |
| `InteractionHarnessTests` (6) | the guest gets an absolute pointer; the click is a device event and not an accessibility action; the keyboard is proved by a file the terminal wrote; four independent launch signals; the interaction module is injected *and* SELinux-labelled; a baseline is taken before anything is pressed |

### Negative controls

A check that passes on the defect it was written for is worse than no check.

* **The character checks, against the photographed robe.** Restoring the
  geometry and the capsule torso from the run that read as a robe fails four of
  the seven: two-legs, daylight-between-them, ink-loss-at-the-hem and
  stance-wider-than-hips. All seven pass when it is restored.
* **The extension import resolver, against a renamed re-export.** The validator
  had to learn `export * from` for the three-way module split; renaming
  `VOLUME_ICONS` to `VOLUME_ICONZ` in the re-exported module produces
  `imports VOLUME_ICONS from ./icons.js, which does not export them`, and the
  pass returns when it is reverted.

---

## 5. Source gate

Measured on the Fedora 44 reference host, as user `bunny`, from the ext4
checkout — not `/mnt/c`, and not as root.

```text
branch: feature/bunny-desktop-shell
head:   be7e3d281fc1782c08263215b35da83cca490428
clean:  []
fs:     /dev/sdd ext4 (ext4, not 9p)
user:   bunny

command:  python3 scripts/release.py gate --kind source
started:  2026-08-09T06:04:11Z
finished: 2026-08-09T06:06:38Z
GATE_EXIT_CODE=0

source gate: PASS
  ok      baselineRecorded
  ok      licenceGatePassed
  ok      minimisationComplete
  ok      qualificationSuitesPass
  ok      repositoryValidation
  ok      sourceSuitesPass
```

A passing source gate asserts nothing about a built image or a booted system.
That is what §6 and §7 are for.

---

## 6. Alpha build

```text
command:  make build-alpha-image
          (build/scripts/build-alpha-image.sh — profile `beta`, channel `alpha`)
commit:   be7e3d281fc1782c08263215b35da83cca490428
started:  2026-08-09T06:11:07Z
finished: 2026-08-09T06:20:34Z
exit:     0
```

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `bunny-os-0.1.0-alpha-be7e3d281fc1.1786255521-x86_64.qcow2` | 2,112,098,816 | `a0c9d0ebbb8d9b35a56c7c96c636a3321128aadd42425be6e6b8f42f6c92f830` |
| `bunny-os-0.1.0-alpha-be7e3d281fc1.1786255521-x86_64.raw` | 10,737,418,240 | `2c96908123de98da48650bd6f3a78c9d12cf291199a4ee3fea0189d4c401a5d2` |

Both under `build/out/beta/`. The build id in the filename is the candidate
commit and its commit timestamp, so the file and the machine it becomes cannot
disagree about what they are.

---

## 7. VM boot — the exact artifact

`bunny-os-0.1.0-alpha-be7e3d281fc1.1786255521-x86_64.qcow2`, SHA-256
`a0c9d0eb…2f830`, booted under QEMU/OVMF with GDM autologin into the `bunny`
Wayland session. The harness names the image explicitly rather than discovering
it, so a run cannot silently use an older build that happens to be present.

| | 1920×1080 (`v1920`) | 1366×768 (`v1366`) |
| --- | --- | --- |
| Firmware → kernel → userspace → GDM | reached | reached |
| Session | `bunny` Wayland | `bunny` Wayland |
| Extension state | `ENABLED`, no error | `ENABLED`, no error |
| Modules installed | 40 + compiled gschema | 40 + compiled gschema |
| Wallpaper | present, 5,609 bytes | present |
| Shell answered D-Bus | immediately | immediately |
| Assistant bridge | available, `/run/user/1000/bunny-companion/runtime.sock` | available |
| Components that failed to build | none | none |
| Plain fallback desktop | never appeared | never appeared |

The desktop's own journal, from inside the guest:

```text
bunny-desktop: mutter reports rendering is software
bunny-desktop: panel blur disabled
bunny-desktop: no battery in /sys/class/power_supply; reporting AC Power
bunny-desktop: the session opened the overview at login; dismissing it for the desktop
bunny-desktop: storage is /var (ext4 on /dev/vda4), chosen as the filesystem
               the signed-in user's own files are on
bunny-desktop: no thermal sensor found; temperature reports Unavailable
bunny-desktop: layout 1920x1080 -> wide, 2 card column(s)
bunny-desktop: the Bunny desktop is up
```

No GJS exception, no extension error, no `could not be created` line, and — the
one that matters for §3.3 — no `the icon theme has no …` line at either
resolution. Every icon name the desktop asked for resolved.

### SELinux

No denial. The labelling in `desktop-inject.sh` was extended to the second
injected module and read back from the guest's own policy; the earlier failure
where `guestfish`-created files came out `unlabeled_t` and GDM exited eleven
times did not recur.

---

## 8. Application launch — criterion 9, closed

Every click below is a QEMU `input-send-event` on the emulated tablet, aimed at
the rectangle AT-SPI reported for that control. Nothing in the guest can
distinguish it from a person.

| Step | 1920×1080 | 1366×768 |
| --- | --- | --- |
| Baseline: neither application running before the click | yes | yes |
| **Files** — clicked in the Bunny UI | pressed | pressed |
| … process running | yes | yes |
| … started by the shell (`app-org.gnome.Nautilus@…service`) | yes | yes |
| … window mapped and showing | yes | yes |
| … closed | yes | yes |
| Bunny Shell after Files | responded, extension `ENABLED` | responded, `ENABLED` |
| **Terminal** — clicked in the Bunny UI | pressed | pressed |
| … started by the shell (`gnome-terminal-server.service`, `app-org.gnome.Terminal.slice`) | yes | yes |
| … window mapped and showing | yes | yes |
| … **accepted typed input** | yes | yes |
| … closed | yes | yes |
| Bunny Shell after Terminal | responded, extension `ENABLED` | responded, `ENABLED` |
| Desktop still assembled and still exposing its controls | yes, 107 | yes, 99 |

The keyboard evidence is a file, not a screenshot. The driver typed
`date > /var/home/bunny/bunny-terminal-typed.txt` and pressed Return; the
harness read that path out of the guest's disk after shutdown:

```text
Sun Aug  9 03:32:35 UTC 2026
```

A window that was mapped but never took focus, or a terminal that opened without
a shell, both look exactly like success in a photograph and neither can produce
that file.

One field is worth stating plainly rather than rounding up: at 1366×768 the
terminal's `pgrep` sample came back empty at the instant the window was first
seen, while the systemd unit, the AT-SPI window and the typed file were all
positive. Three of four signals and the keyboard proof; the fourth is recorded
as it was measured.

---

## 9. Telemetry

Read from the running Alpha guest.

| Reading | Value | Source |
| --- | --- | --- |
| CPU | 1% idle, 13% while starting Nautilus | `/proc/stat`, delta between samples |
| RAM | 975.5 MB – 1.2 GB / 5.8 GB | `/proc/meminfo`, `MemAvailable` |
| Storage | **3.9 GB / 8.3 GB on `/var` (ext4, `/dev/vda4`)** | `/proc/self/mountinfo` + statfs |
| Temperature | `Unavailable` | no hwmon and no thermal zone in this guest |
| Network | ↑ 0 B/s ↓ 0 B/s idle; ↑ 135 B/s ↓ 90 B/s under load | `/proc/net/dev`, monotonic delta |
| Battery | `AC Power` | `/sys/class/power_supply` — no battery present |
| Audio | volume indicator present | `Gvc.MixerControl` |
| Brightness | hidden | no backlight in this guest |
| Clock / date | `03:32 Sun 9 Aug` | session clock |

No fabricated value, no `0` standing in for a failed read, and no filesystem
capacity that is a true measurement of the wrong filesystem. The storage figure
is the one that changed: it was `14.2 MB / 14.2 MB`, and it is now the ext4
partition the user's files are actually on, with the mount point and free space
in the row's accessible description.

---

## 10. Responsive layout

Checked two ways, because the obvious way is not reliable at one of the two
resolutions.

**From the compositor's own allocations.** AT-SPI reports every control's
extents in screen coordinates, taken from Clutter's actual allocation rather
than from what the layout solver intended — so if a control is drawn somewhere
other than where the solver put it, this finds where it *is*.

| | 1920×1080 | 1366×768 |
| --- | --- | --- |
| Controls with an allocation | 107 | 99 |
| Controls off-screen or clipped | **0** | **0** |
| Overlapping panel pairs | **none** | **none** |
| Breakpoint | `wide`, 2 card columns | `compact`, sidebar collapsed |
| Sidebar | 196 px, expanded with labels | 60 px, icons with tooltips |
| Dock | 560 × 64 at (680, 996) | 560 × 64 at (403, 684) |
| System card | 304 × 236, dial beside the figures | 248 × 208, dial above them |
| Character band | 347 × 520 | 274 × 411 |

Every figure on the System card is whole at both: `RAM 1.0/5.8 GB`,
`Storage 3.9/8.3 GB`, `Temp Unavailable`. Getting that right took three builds
and is the subject of the table at the top of this document.

**From the layout solver, under `node`.** Seven resolutions, every pair of
rectangles compared, every panel required to stay on screen and the character
required to survive — unchanged from the previous phase and still passing.

### The sheared screenshot

The 1366×768 framebuffer capture is diagonally torn with colour fringing.
That is virtio-vga's scanout stride against a width that is not a multiple of
eight; the tear is in the *picture*, not in the session, and the two independent
measurements above are taken from the same run that produced it. A supplementary
capture at 1360×768 — eight pixels narrower, the same `compact` breakpoint — is
included so the small layout can be looked at.

---

## 11. Screenshots

Under `build/out/` on the reference host, copied into `build/out/alpha-a1/`,
`alpha-a2/` and `alpha-a3/`.

All from the candidate artifact, under `build/out/`.

| File | What it shows |
| --- | --- |
| `alpha-1920/00-desktop.png` | the desktop as it appears after login |
| `alpha-1920/01-files-open.png` | Files, opened by clicking the dock tile |
| `alpha-1920/02-files-closed.png` | after Files closed |
| `alpha-1920/03-terminal-open.png` | Terminal, opened by clicking the dock tile |
| `alpha-1920/04-terminal-typed.png` | after the typed command ran |
| `alpha-1920/05-terminal-closed.png` | after Terminal closed |
| `alpha-1920/06-desktop-after.png` | the desktop, intact, after both |
| `alpha-1366/*.png` | 1366×768 — the run every figure in §8 and §10 comes from; the capture is sheared, see §10 |
| `alpha-1360/t230.png` | 1360×768 — the same `compact` breakpoint, viewable, with the System card stacked |
| `character/contact-sheet.png` | the ten character states, rendered offline by `gjs -m build/scripts/render-character.js` |

---

## 12. Against the acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Working tree clean at the candidate commit | yes |
| 2 | Source gate passes | PASS, exit 0, on the reference host as `bunny` from ext4 |
| 3 | Real Alpha artifact builds | yes, `make build-alpha-image`, exit 0 |
| 4 | SHA-256 recorded | yes, §6 |
| 5 | The exact built artifact boots | yes, both resolutions |
| 6 | Bunny Shell appears automatically | yes, extension `ENABLED`, no error |
| 7 | No plain fallback desktop | never appeared |
| 8 | No fatal GNOME Shell exception | none; no component failed to build |
| 9 | **Files launches by clicking the Bunny UI** | yes — dock tile, `role: button`, inside `Bunny dock` |
| 10 | **Terminal launches by clicking the Bunny UI** | yes — same, and it accepted typed input |
| 11 | Closing either does not crash Bunny Shell | shell responded and stayed `ENABLED` after both |
| 12 | Storage reports useful persistent storage | `/var`, ext4, `/dev/vda4` |
| 13 | No tofu glyphs in critical UI | none; no icon failed to resolve |
| 14 | Character reads as a human in a hoodie | yes — see §3.4 and the contact sheet |
| 15 | Character states still work | ten states, each with a pose and an accent that is a real colour |
| 16 | 1920×1080 has no major overlap | 0 controls off-screen, no panel pair overlapping |
| 17 | 1366×768 remains usable | same, sidebar collapsed, no clipping |
| 18 | No fabricated telemetry | none; `Unavailable` where the machine cannot answer |
| 19 | All required tests pass | §4 |
| 20 | Final source gate passes | PASS |

---

## 13. Known limitations

Carried forward from the previous phase and still true:

1. **The in-shell character is 2D vector, not 3D.** It cannot be otherwise
   inside the compositor: a Wayland client's surface cannot be reparented into
   the shell's scene graph. The 3D renderer remains the companion window's.
2. **Measured only on llvmpipe.** Every run reported software rendering, so
   `desktop-blur` has still never been exercised in its enabled state.
3. **One monitor.** The layout solves for the primary monitor; a second gets the
   wallpaper and nothing else.
4. **Two palettes.** GTK surfaces are evergreen and mint; the desktop is violet.
   St cannot read the JSON token file.
5. **`_backgroundGroup` is private API**, with a logged fallback.
6. **The companion window opens over the character.** It autostarts and is an
   ordinary window, so it covers the desktop the way any window does. It is the
   first thing on screen after login, over the middle of the dashboard, and the
   interaction between it and the in-shell figure is still an unanswered product
   question rather than a defect.

Found or clarified in this phase:

7. **The desktop is disabled at the lock screen.** GNOME switches to the
   `unlock-dialog` session mode when the screen locks, which disables every
   extension that does not declare that mode. The Bunny desktop does not declare
   it deliberately — a dashboard drawing behind a lock screen would show a
   locked machine's agenda and notifications — so the desktop is torn down and
   rebuilt across a lock. That rebuild has not been exercised deliberately; it
   was observed happening and then configured away in the harness.
8. **The 1366×768 framebuffer capture is sheared.** virtio-vga's scanout stride
   against a width that is not a multiple of eight. The session is unaffected;
   §10 measures the layout from the accessibility tree instead, and a 1360×768
   capture is provided for looking at.
9. **The assistant has still never answered a real request through the
   interface.** The bridge is reachable and the panel is wired to it, but no
   query has been typed into the desktop and answered end to end. This phase
   pressed the launcher tiles; it did not converse.
10. **The Quick Access card draws uninstalled applications with a generic
    icon.** They are correctly marked unavailable and are not launchable, but a
    row of identical generic marks is not informative.
11. **No test covers the desktop at more than one scale factor.** Text scaling
    is an input to the layout solver and is exercised in the unit tests, but no
    booted run has used a HiDPI scale.
