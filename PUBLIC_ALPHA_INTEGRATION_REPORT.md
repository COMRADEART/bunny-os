<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Public Alpha integration report

Branch: `feature/public-alpha-integration`
Base: `b8b99f69a4d2f742fafb28dcbdd8d1805ff0dd20` (`b8b99f6`, `feature/companion-3d-renderer`)
Date: 2026-08-07

## What this phase found

The companion stack was feature-complete. The product around it was not, and the
gap was invisible from the repository — every one of the defects below passed
every test that existed, because the tests ran against a checkout and the
defects were in what the *image* did.

Two of them are the phase:

**The companion had never started at login on any image ever built.**
`/usr/lib/systemd/user-preset/60-bunny-os.preset` has named
`bunny-companion.service` since the integration branch, with a comment beside it
saying it is enabled rather than left to the desktop entry. It was not. Nothing
runs `systemctl --global preset-all`, and a user manager does not apply presets
by itself. Measured in a live graphical session on the first booted Alpha image:

```text
systemctl --user is-enabled bunny-companion.service bunny-companion-window.service
disabled
disabled

bunny-companion.service  ActiveState=inactive
```

**The image had a sound server and no player.** `pipewire`, `wireplumber`,
`pulseaudio-libs` and `alsa-lib` were all installed; `paplay`, `pactl`,
`pw-play`, `pw-cat`, `aplay`, `arecord`, `parecord` and `spd-say` were all
absent. The libraries arrive transitively and the *programs* live in packages
nothing pulled in. The companion drives players by name, so every audio backend
reported "no audio backend answered" on a machine with working speakers, and the
Speech Dispatcher voice provider could never have been selected at all.

Neither was findable without booting an image and looking at it. That is what
this phase built the means to do.

---

## 1. Starting and final SHAs

| | |
| --- | --- |
| Base commit | `b8b99f69a4d2f742fafb28dcbdd8d1805ff0dd20` |
| Gate commit | `8bb2b0d3b667737918c082dfe2fea1d491d2d556` |
| Commits | 14 |
| Files changed | 50 (+9,323 / −42) |
| Image built from the gate commit | `bunny-os-0.1.0-alpha-8bb2b0d3b667.1786121034-x86_64.qcow2` |

Every commit in the range, in order:

```text
d93e22d The character a machine starts with was decided by tuple order
69c0f7f Nothing started the window
6542a0b Two tests were asserting more than was true
501d936 "Added to the evidence tree" is a question about commits, not about files
62b7ef9 The image had a sound server and no player
aa9c6af A harness that asks the booted system about itself
fa9ae69 The gates, and a collector that cannot call an unrun gate a passed one
bb2f085 BUNNY_ALPHA_IMAGE, so the harness can run from a worktree
2594f87 virt-customize cannot inspect a bootc disk, and says so
09ace58 Two harness scripts reached Linux with CRLF and bash blamed the script
bf5da4b The first booted Alpha image made one outbound connection nobody asked for
3ee45ff The companion has never started at login on a built image
43176be The capability record reported three desktop capabilities unavailable
8bb2b0d Disable could not reach a unit wanted from /usr/lib; mask can
```

## 2. Alpha scope

`docs/PUBLIC_ALPHA_SCOPE.md` is the freeze. It names 24 features Alpha 0.1
contains, 16 it defers, the default-character policy, the default security
posture, and the rule that a new proposal is deferred by default unless the
success path fails without it.

No feature outside that list was added on this branch. Everything built here is
either integration of what already existed, or a fix for a defect that broke the
success path.

**Telemetry is absent, not off.** There is no counter, no ping, no crash upload
and no usage measurement in Bunny OS Alpha 0.1. §27's debugging need is met by
local diagnostics export.

## 3. Build-input impact

```text
examined 50 paths: 33 installed, 14 context-only, 3 unreachable
declared install routes: 72 (was 67)
profiles affected: beta, desktop, developer, live, minimal, recovery, shell, shell-test
BUILD-AFFECTING: YES
```

New install routes: two desktop entries (`art.comrade.BunnyCompanion.desktop`,
`art.comrade.BunnyDiagnostics.desktop`, desktop profiles), a Speech Dispatcher
drop-in, and two `/usr/libexec` programs added to `SYSTEM_SCRIPTS`
(`bunny-companion-window`, `bunny-companion-recovery`). One new generated route:
`/usr/lib/os-release`, declared in `GENERATED_ROUTES` with its producer.

`build/scripts/build-input-closure.py --audit` passes: the installer installs
only what the route table models.

## 4. Boot architecture, measured

From the booted VM's own systemd accounting, not from a stopwatch:

| Stage | Monotonic since kernel start |
| --- | --- |
| systemd-journald | 6.124 s |
| sysinit.target | 9.863 s |
| basic.target | 9.963 s |
| multi-user.target | 11.007 s |
| gdm.service (login screen) | 10.755 s |
| graphical.target | 11.009 s |
| user session (autologin) | seat0 session 1, tty2 |
| companion service ready | active, 0 restarts |

Kernel `7.1.5-200.fc44.x86_64`. `systemd-detect-virt` = `kvm`, recorded and
asserted: **this is VM evidence and is labelled as such.** No WSL startup is
reported anywhere in this phase as Bunny OS boot evidence.

Firmware/bootloader handoff is not separately timed — `systemd-analyze time`
returned empty on this guest, so the firmware and loader intervals are NOT_RUN.
The boot reached GRUB (the menu reads `Bunny OS Alpha 0.1 (ostree:0)`) and
systemd printed `Welcome to Bunny OS Alpha 0.1!`.

GTK-visible and first-character-frame timestamps are **NOT_RUN**: the harness
boots headless and reads a serial console, so nothing observes a frame. The
launcher writes them into `session-timeline.json` when a window opens; that file
is collected but a headless VM never produces one.

## 5. Image architecture

One reproducible-development image target: `make build-alpha-image`, which
builds the `beta` profile — the installed desktop payload — with
`BUNNY_RELEASE_CHANNEL=alpha`. A profile names a package set; a channel names a
promise. Renaming the profile would have changed the profile enumeration in the
installer, the closure analyser, the preset table and every per-profile evidence
record, to change a string the channel already carries correctly.

Contents confirmed present in the built image: Linux kernel 7.1.5, firmware,
GRUB + shim, Fedora 44 base userspace, systemd, GNOME/GDM, GTK 4, Mesa (DRI +
Vulkan), the Bunny runtime at `/usr/lib/bunny-os/python`, both character
packages, the voice runtime, the speech-input runtime, the agent-provider
runtime, the desktop action broker, schemas, user units, desktop entries, the
first-run application, and diagnostics.

**Nothing is downloaded at first boot.** Verified as a consequence of §13/§28
below: no outbound connection is made and every update timer is disabled.

## 6. Installed-artifact provenance

Collected from inside the booted VM, as the desktop user, through their session:

```text
2D renderer          /usr/lib/bunny-os/python/companion/character/animated_renderer.py
3D renderer          /usr/lib/bunny-os/python/companion/character/three_d/renderer.py
ToolBroker           /usr/lib/bunny-os/python/companion/tools.py
agents               /usr/lib/bunny-os/python/companion/agents/service.py
capability runtime   /usr/lib/bunny-os/python/capability/runtime.py
companion runtime    /usr/lib/bunny-os/python/companion/runtime.py
desktop actions      /usr/lib/bunny-os/python/companion/desktop/broker.py
presentation         /usr/lib/bunny-os/python/companion/presentation.py
speech input         /usr/lib/bunny-os/python/companion/speech/service.py
voice                /usr/lib/bunny-os/python/companion/voice/service.py

10/10 imported from /usr/lib/bunny-os/python
rejections: []
```

Each carries its SHA-256 in the record. The rejection list is empty and it is
*checked*, not assumed: the probe rejects a module imported from anywhere but
the installed root, a set `PYTHONPATH`, and an existing user site-packages
directory. All three are absent.

## 7. First-run experience

The old first run was thirteen pages of static copy with a Next button. It said
"No multi-gigabyte model is downloaded automatically", which is true, and it
never looked to see whether one was there.

It is now the ten pages `companion.onboarding` declares, each showing what its
own survey found on this machine. From the booted VM:

```text
 1. welcome          required
 2. privacy
 3. character        "This machine will use the text-only presentation."
 4. microphone       "…no speech-recognition model is installed…"
 5. speaker          survey: audio
 6. providers        "No local AI provider is installed on this machine.
                      Bunny still starts…and typed input works"
 7. local_model      survey: providers
 8. remote_provider  skippable
 9. permissions
10. finish           required
```

**Offline completability is asserted, not claimed**: `10 steps, 2 required, 0 of
those ask for something`. The two required pages — welcome and finish — carry no
survey, so a machine with no network, no microphone, no speakers, no model and
no GPU completes all ten.

## 8. Default-character policy

`companion/character/policy.py`. Four rules, each tested as the behaviour it
forbids:

| Rule | Test |
| --- | --- |
| A user's selection outranks the policy, permanently | `test_a_user_selection_is_never_replaced` |
| The policy raises a selection and never lowers one | `test_a_lost_gpu_does_not_change_the_selected_package` |
| A package that will not validate is not eligible at its rung | `test_a_package_that_will_not_validate_is_not_eligible_at_its_rung` |
| Recovery restores rather than chooses | `test_restore_refuses_when_capability_does_not_permit` |

The ladder names a *bundle*, not a package id, because the two built-ins
disagree about their own naming (`org.bunny-os.default-bunny` and
`bunny-default-3d`) and a hard-coded pair selected one and failed on the other.

Policy state lives in its own file beside the character registry, so the
registry's validated schema keeps answering one question.

## 9. Provider onboarding

`companion/onboarding/providers.py` asks §8's five questions separately:
installed, running, models, resource requirement, eligible — with a reason and a
remedy for each. Running it on the development host found the defect the
separation exists to catch: something answered on `127.0.0.1:8080` with a model,
and requiring a binary on `PATH` reported it as "not installed, install it".
For a server, answering is the operational fact; the binary only shapes the
remedy.

On the booted VM, with no provider installed:

```text
No local AI provider is installed on this machine. Bunny still starts,
the character appears and typed input works; answers need a provider you
install yourself.
```

No model is downloaded. The estimate shown for a model is labelled an estimate
and derived from the reported size; a model whose size the provider did not
report gets no estimate rather than a zero.

## 10. Speech onboarding

`companion/onboarding/speech.py` reports four layers — microphone, library,
model, recogniser — and names the *first* missing one. On the booted image:

```text
speech-model  available=False  the vosk library is not importable: No module named 'vosk'
```

`vosk` is not in the Fedora repositories and is not shipped. Speech recognition
is therefore **unavailable on the Alpha image**, which is §9's supported branch:
push-to-talk reports its state, typed input is preserved, and the first-run page
says what is missing and that Bunny will not download it. Exit criterion 10 is
conditional on speech resources existing, and they do not.

## 11. Companion autostart

The P0. `bunny-companion-window.service` and `/usr/libexec/bunny-companion-window`
are new; the launcher spends a one-shot safe-mode request, waits for the socket
with a bound and an actionable reason, applies the default-character policy,
records the session timeline, and counts the launch so three dead starts arm
safe mode.

After the fix, from the booted VM:

```text
is-enabled: 'enabled\nenabled'
bunny-companion.service         active, NRestarts=0
bunny-companion-window.service  loaded
gnome-terminal-server processes: 0
```

`MemoryDenyWriteExecute` is deliberately absent from the window unit. Mesa's
shader compilers and llvmpipe's JIT map executable pages, and a window killed
the moment it draws in 3D is not hardened, it is broken.

## 12. Service dependency graph

`docs/ALPHA_SESSION_SERVICES.md`. The graph, the restart discipline, and the
table of what may fail without taking the runtime down — Vosk, Ollama,
llama.cpp, audio output, microphone, 3D graphics and the character package are
all optional. The one hard requirement is the capability runtime, expressed as
`ConditionPathExists=` rather than as a crash.

## 13. Offline results

Two offline VM stories were run with `-nic none` and NetworkManager conditioned
off inside the guest. Results are in the gate record. What is asserted:
`network.offline-has-no-default-route`, plus every online assertion.

## 14. Network audit

Measured from inside the guest with `ss -tulpn` and `ss -tnp state established`,
on a freshly installed system nobody had touched. **One outbound connection
existed:**

```text
10.0.2.15:59080 -> 109.230.233.153:443   gnome-software (pid 1531)
```

Three findings and three fixes:

* **gnome-software** refreshes metadata from the moment the session starts.
  `download-updates=false` does not stop it — that key governs downloading
  *updates*. The unit is masked. `--global disable` was tried first and did not
  work: it writes into `/etc/systemd/user` and cannot reach a unit wanted from
  `/usr/lib/systemd/user`.
* **sshd** was `LISTEN` on `0.0.0.0:22` despite `disable sshd.service` in the
  preset, because Fedora ships socket activation. `sshd.socket` is now disabled
  by name.
* **passimd** — fwupd's local metadata cache — listens on `0.0.0.0:27500` and
  advertises over mDNS, so a Bunny OS laptop on a café network offers that
  network a service. Disabled.

Five system timers that each contact a server on their own schedule are disabled
by name: `bootc-fetch-apply-updates`, `dnf-makecache`, `dnf5-makecache`,
`fwupd-refresh`, `malcontent-webd-update`. The first is worth naming: it does not
only check, it *applies*, and a machine that swapped its own deployment
overnight would be a machine whose build identity changed while nobody was
looking.

Remaining listeners are loopback (`systemd-resolved`, `chronyd`, `cupsd`) plus
`avahi` and `systemd-resolved` on mDNS/LLMNR, which are pre-existing and outside
this phase's scope — recorded in §38 below as open.

## 15. Installation

**BLOCKED — not this branch's defect.** `make build-alpha-iso` fails in
`image-builder`'s `bootc-generic-iso` pipeline:

```text
FileNotFoundError: [Errno 2] No such file or directory:
  '/boot/efi/EFI/fedora/shimx64.efi'
```

Traced: `quay.io/fedora/fedora-bootc:44` ships an **empty `/boot`**. `shim-x64`
is installed and its file list names those paths, but they are not materialised
in the container, and `dnf reinstall shim-x64` does not repopulate them. The
disk-image path works because bootc regenerates `/boot` at deployment; the ISO
path needs the files in the container.

`image-builder 76.0.0`, `osbuild 185`. This is an upstream incompatibility
between the current base image and the current ISO pipeline, and it predates
this branch — `LIVE_INSTALLER_MEDIA_REPORT.md` has recorded the live ISO as
NOT PRODUCED since 2026-08-01, and this is the first time anyone ran the build
and found out why.

The installation path itself (`installer/`, Anaconda profile, kickstart,
`vm-install-smoke.sh`) is unchanged and untested this phase.

## 16–17. Upgrade and rollback

**NOT_RUN.** `bootc` is the mechanism and `vm-upgrade-test.sh` /
`vm-rollback-test.sh` exist; neither was run this phase. An upgrade test needs
two builds published to a registry the guest can reach, and this phase disabled
every automatic update path deliberately (§14) — reconnecting one to test it is
a change to the security posture that belongs in its own review.

`bunny-update-agent.timer` remains disabled. No Alpha update channel exists.

## 18. Recovery mode

`/usr/libexec/bunny-companion-recovery` and `art.comrade.BunnyDiagnostics.desktop`.
Reachable from the applications list, because the moment it is wanted is the
moment the companion window is not there to offer it. It reads systemd and the
filesystem, never the companion protocol.

From the booted VM: **12 diagnostic sections**, covering both units, the socket,
the store, safe mode, the renderer, the selected character, providers, audio,
microphone, speech and desktop actions. Six actions, each stating its effect:
restart, disable 3D for the next start, reset presentation, safe mode,
text-only, export.

`--text` prints the same report, so nothing essential lives only in a window.

## 19. Safe mode

`companion/support/safemode.py`. Six restrictions with the variable that
implements each, and five things it keeps. It is a *combination of flags that
already existed* — `speech_enabled`, `desktop_enabled`, `voice_enabled`, plus a
provider configuration with remote providers **removed rather than disabled** —
so it inherits their tests rather than needing its own reduced code path.

One-shot by default. Three consecutive launches that do not reach a usable
window arm it automatically: §34's crash-loop breaker, written as a file in the
state directory rather than as a hope.

## 20. Hardware capability detection

`companion/hardware.py`, and the §20 rule is structural: `hardware_facts()` and
`operational_probes()` do not talk to each other, and every probe carries
`wouldHaveBeenInferredFrom` naming the hardware fact a naive implementation
would have used. From the booted VM:

```text
arch=x86_64  kernel=7.1.5-200.fc44.x86_64
cpu={'count': 4, 'model': 'Intel(R) Core(TM) Ultra 9 185H'}
memory total=5.8 GiB available=4.5 GiB
gpus=[{'vendor': 'virtio', 'driver': 'virtio-pci', 'node': 'card1'}]
dri=['by-path', 'card1', 'renderD128']
audio (from /proc/asound) = {'inputs': 0, 'outputs': 0, 'soundCards': []}
virtualised=True (kvm)

operational:
  local-model        False  no local AI provider is installed
  speech-model       False  the vosk library is not importable
  audio-output       True   2 device(s) from pipewire
  three-d-renderer   True   libEGL is present
```

The audio row is the separation working: `/proc/asound` reports **no sound
card**, and the operational probe reports **two devices from pipewire**. A
record that inferred one from the other would have got it exactly backwards.

## 21. Real GPU results

**NOT_RUN.** Every graphics figure in this phase is from `virtio-gpu` in QEMU or
from llvmpipe on the reference host. No hardware-GPU validation exists, and none
of the numbers here is presented as one. Exit criterion 26 is **not met**.

## 22. Physical-laptop results

**NOT_RUN.** Exit criterion 27 is **not met**.

## 23. Suspend/resume

**NOT_RUN.** No suspend was performed in a VM or on hardware this phase.

## 24–25. Multi-monitor and display scaling

**NOT_RUN.** The harness boots headless. The character dock is recorded as a
*named position* rather than coordinates in `companion/settings.py`, which is
§24's "do not rely on absolute coordinates" implemented but not exercised.

## 26. Accessibility

The recovery report, the first-run wizard and every survey have a text form that
is the same content, not a reduced one — `--text` on the diagnostics program,
`--describe` on the first run, `bunny-os --json companion onboarding`. The
diagnostics window spells the verdict into each row's accessible label rather
than leaving it in a tick glyph. Reduced motion, no-animation, text-only,
captions and UI scale are all settings that persist.

Not exercised with an actual screen reader this phase: **NOT_RUN**.

## 27. Security posture

| Setting | State on the built image |
| --- | --- |
| Remote AI | off; no remote provider configured, none reachable in safe mode |
| Continuous microphone | not implemented |
| Wake word | not implemented |
| Desktop actions | approval required; the setting refuses any other value |
| Local AI | preferred |
| 3D | adaptive |
| Telemetry | absent |
| Update timers | all five disabled by name |
| sshd | service and socket disabled |

## 28–36. The stories

| Story | Result |
| --- | --- |
| §30 product-level Alpha | **PARTIAL.** Boot, login, autostart, provenance, capability, diagnostics and identity are measured in a VM. The steps needing a person at a screen — the character appearing, the transcript, the approval dialog — are NOT_RUN. |
| §31 degraded | **PARTIAL.** The VM has no GPU-eligible presentation and the policy correctly chose text-only with a stated reason. The full ladder is unit-tested at every rung. |
| §32 no-model | **PASS.** Companion starts, UI does not crash, provider state says plainly that nothing is installed, no model downloaded, no remote activated. |
| §33 no-microphone | **PASS.** Speech reports unavailable with the first missing layer named; typed input preserved; no crash loop. |
| §34 renderer failure | **PARTIAL.** Safe mode and the three-failure counter are tested in process; a deliberately corrupted renderer in a VM is NOT_RUN. |
| §35 provider failure | **NOT_RUN.** |
| §36 update | **NOT_RUN** (see §16). |

## 37–38. Logging and diagnostics

The fault-redaction patterns moved to `companion/privacy.py` as
`DIAGNOSTIC_REDACTIONS`, used by both the runtime's fault records and the
diagnostics bundle. Two copies of a redaction list is one copy that falls behind.

`Export Bunny Diagnostics` writes one JSON document — readable in a text editor,
which is what "inspect before sharing" requires in practice. It declares what it
contains and what it excludes, and `uploaded: false` is a field. There is no
transport in the module.

**Open:** a 1,656,115,200-byte `speech-dispatcher.log` in `/run/user/$UID` — RAM
— filled the tmpfs on the qualification host and broke the next `podman build`.
Speech Dispatcher at its default `LogLevel 3` writes every line of every
response, and the voice provider asks for the full voice matrix once per
process. Bounded by a drop-in under `clients/`, which its own `speechd.conf`
already includes. **Not yet re-measured on a machine that has run for a day.**

## 39–40. Version identity and channel

One identity, from the build, visible everywhere. From the booted VM:

```text
GRUB menu        Bunny OS Alpha 0.1 (ostree:0)
systemd          Welcome to Bunny OS Alpha 0.1!
/usr/lib/os-release
                 NAME="Bunny OS"
                 PRETTY_NAME="Bunny OS Alpha 0.1"
                 VARIANT_ID=alpha
                 BUNNY_OS_BUILD_ID=8bb2b0d3b667.1786121034
                 BUNNY_OS_CHANNEL=alpha
                 ID=fedora  VERSION_ID=44   (kept exactly as the base wrote them)
release.json     releaseChannel=alpha  buildId=8bb2b0d3b667.1786121034
bunny-os companion identity
                 displayName="Bunny OS Alpha 0.1"  installed=true
image filename   bunny-os-0.1.0-alpha-8bb2b0d3b667.1786121034-x86_64.qcow2
```

`ID`, `VERSION_ID`, `PLATFORM_ID` and `CPE_NAME` are deliberately **not**
rewritten: dnf, SELinux policy and bootc key off them, and a downstream that
changed them would break updates in order to change a display string.

Two channels, `development` and `alpha`. The build id is derived from the commit
and `SOURCE_DATE_EPOCH`, so two builds of one tree get the same id — the
property a later reproducibility claim needs, and the reason it is not a counter.

## 41. Reproducibility implications

This branch makes **no reproducibility claim**. What it leaves for a
qualification phase:

* build inputs are unchanged in kind — the same base, the same lock machinery;
* **the package set changed**: eight packages added to the desktop set. A
  hermetic build needs its snapshot re-resolved and re-materialised before any
  candidate is manufactured;
* `/usr/lib/os-release` is a new generated path, declared in `GENERATED_ROUTES`,
  and it changes on every commit exactly as `release.json` does;
* the ISO path is blocked upstream (§15) and must be resolved before an
  installation medium can be qualified.

## 42. Test gates

Gate commit `8bb2b0d3b667737918c082dfe2fea1d491d2d556`. Results are in
`qualification/public-alpha/alpha-gates.json`; the collector reports every gate
with the count asked for, the count achieved, and `passed`/`failed`/`notRun`,
and `complete` is separate from `allPassed` so a partial run cannot read as a
whole one.

*(Gate figures are appended by the closing commit.)*

## 43. Performance

Boot figures are in §4. Interaction and renderer figures are **NOT_RUN** on
hardware; the llvmpipe renderer figures from the 3D phase stand unchanged and
are not repeated here as Alpha numbers.

## 44. Defect classification

| | Defect | Where |
| --- | --- | --- |
| **P0** | The companion never started at login on any built image | fixed, `3ee45ff` |
| **P1** | The image had a sound server and no player; Bunny could not speak or capture | fixed, `62b7ef9` |
| **P1** | An unexplained outbound connection on a default boot (gnome-software) | fixed, `bf5da4b` + `8bb2b0d` |
| **P1** | The installation medium cannot be built | **OPEN**, upstream (§15) |
| **P2** | `sshd` listening despite the preset; `passimd` advertising on the LAN | fixed, `bf5da4b` |
| **P2** | Five update timers contacting servers on their own schedule | fixed, `bf5da4b` |
| **P2** | `espeak-ng` and `speech-dispatcher` present only as Orca's dependencies | fixed, `62b7ef9` |
| **P2** | Unbounded Speech Dispatcher log in a RAM-backed tmpfs | fixed, `62b7ef9`; not re-measured |
| **P2** | `--text-only` was constructed and discarded; the window ignored it | fixed, `69c0f7f` |
| **P2** | The capability record reported three desktop capabilities unavailable on a machine where they worked | fixed, `43176be` |
| **P3** | `DefaultCharacterDecision.applied` meant "would change" in a dry run | fixed, `69c0f7f` |
| **P3** | The preservation test asked the filesystem a question about commits | fixed, `501d936` |
| **P3** | Two harness scripts reached Linux with CRLF | fixed, `09ace58` |
| **P3** | A unit's `Documentation=` points at `docs/IMAGE_FINALISATION.md`, which does not exist | **OPEN** |

**One P1 remains open** and it is not fixable in this repository: §15.

## 45. Exit criteria

| # | Criterion | State |
| --- | --- | --- |
| 1 | A bootable image exists | **met** |
| 2 | A supported installation path exists | **not met** (§15) |
| 3 | Fresh installation reaches login | **not met** — no installer medium |
| 4 | Companion autostarts without terminal interaction | **met** |
| 5 | Default character appears | **partial** — policy decides correctly; no frame observed |
| 6 | 3D selected adaptively | **partial** — unit-tested; no GPU |
| 7 | 2D/text fallbacks work | **met** in process; text-only chosen correctly in the VM |
| 8 | Typed interaction works | **partial** — the runtime accepts and runs a task; no window observed |
| 9 | Local provider interaction works | **not met** — no provider on the image |
| 10 | Push-to-talk when speech resources exist | **n/a** — no vosk |
| 11 | Voice output when audio exists | **partial** — the stack now ships; not exercised in the VM |
| 12–13 | Approval-mediated and reversible desktop action | **not met** in a VM |
| 14 | Offline local operation | **partial** — offline boots recorded |
| 15 | No-model fails gracefully | **met** |
| 16 | No-microphone fails gracefully | **met** |
| 17 | Renderer failure degrades safely | **partial** |
| 18 | Provider failure does not become remote | **met by construction**; not exercised |
| 19 | Suspend/resume coherent | **not met** |
| 20 | Reboot does not repeat tasks | **not met** — not exercised |
| 21 | Settings persist | **met** |
| 22 | Recovery and safe mode exist | **met** |
| 23 | Diagnostics export exists | **met** |
| 24 | No unexplained outbound traffic | **met** after the fixes; re-measured |
| 25 | Automated Alpha gates pass | see §42 |
| 26 | Real GPU validation recorded | **not met** |
| 27 | Physical-laptop validation recorded | **not met** |
| 28 | No P0/P1 open | **not met** — §15 |
| 29 | Feature scope frozen | **met** |
| 30 | No release/reproducibility claim made | **met** |

**`feature/public-alpha-integration` is not complete.** Eleven criteria are met,
nine are partial, ten are not met. The branch has done what it could do without
hardware and without an installation medium, and the two things it could not do
are named rather than approximated.

## Known limitations and NOT_RUN

* No installation medium (§15, upstream).
* No hardware GPU, no physical laptop, no suspend/resume, no multi-monitor, no
  display scaling, no screen-reader pass.
* No local AI provider and no speech-recognition library on the image, so the
  provider and speech halves of the success path are structurally unexercised —
  correctly reported unavailable, which is §9's and §32's supported branch.
* Upgrade and rollback not exercised.
* Every renderer figure is software rasterisation.
* The window itself was never *seen*. Everything about the companion window in
  this report is a statement about units, processes and files. §21's rule
  applies to more than GPUs: a headless boot proves a window started, not that
  anything appeared in it.
