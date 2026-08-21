# Known limitations

## Voice interaction milestone additions

- Pocket TTS is the configured default output provider, with packaged local
  model/voice assets, a CPU-only PyTorch worker, optional Kitten Nano INT8 and
  deterministic eSpeak/Speech Dispatcher fallback. Both neural engines have now
  been run: on the Fedora 44 reference host each produces real audio through
  the real worker and the real registry, and each is recognised back by the
  bundled Vosk model at word error rate 0.00. Pocket measures real-time factor
  0.56–0.59 and Kitten 0.17–0.19, unchanged when the worker is pinned to two
  cores. Doing so found four defects in Kitten's phonemization, every one of
  which produced fluent, confident audio that was not the requested sentence;
  see `POCKET_TTS_MILESTONE_REPORT.md`.
- A `shell-test` image was built at commit `4d7e9a4` against a relocked
  543-package snapshot, and the voice stack was exercised inside that image:
  the expanded PyTorch runtime, both models and the worker launcher are
  present, Pocket reports READY, the registry selects Pocket with no preference
  expressed, and both engines synthesise audio that is recognised back at word
  error rate 0.00. The engine therefore works on a real Bunny OS image and not
  only on a staging host.
- What has still not happened is driving it through a booted graphical session.
  No spoken `Open Files` run, no settings-UI validation at 1920×1080 or
  1366×768, and no observation of the character's TALKING state against real
  playback. A VM also cannot present a real microphone without the null-sink
  and loopback arrangement used elsewhere in this project. Until those exist
  the TTS milestone is not a PASS, regardless of source-test results.
- Pocket streaming is not implemented. `supports_streaming` is declared `False`
  rather than simulated by cutting a finished WAV into pieces, so time to first
  audio is whole-utterance synthesis time: 0.94s for "Files is open." and about
  2.2s for a typical sentence on the reference host.
- Making Pocket the default costs roughly 1.1 GiB uncompressed — 865 MiB of
  runtime, model and prepared voice, of which 651 MiB is the expanded PyTorch
  CPU wheel, plus about 260 MiB of newly named Fedora packages. Kitten alone
  would cost about a tenth of that. This is a large amount for the modest
  hardware Bunny targets and is recorded rather than absorbed.

- Bunny Shell push-to-talk uses the canonical companion capture, recognition,
  assistant-action and TTS path. The Alpha image definition now declares
  Fedora's native Vosk runtime and bundles the reviewed small English model;
  Fedora image composition completed with the package/model postconditions
  satisfied. A headless exact-artifact QEMU boot reached `graphical.target`,
  started the companion runtime without restarts and reported local Vosk/TTS
  readiness. No model is downloaded automatically.
- This host could not exercise a visible GNOME/Mutter/Wayland session or a
  physical microphone/speaker. The QEMU guest exposed only PipeWire's virtual
  `auto_null.monitor`, which Bunny classifies as an output monitor rather than
  a microphone. Spoken `Open Files`, TTS audibility and speech interruption
  remain graphical hardware-acceptance blockers.
- 1920×1080 and 1366×768 pass static layout/source tests only; no current visual
  screenshot acceptance run exists.
- Wake-word capture is deliberately disabled and cannot be enabled by settings.

- An unsigned Alpha OCI, QCOW2 and raw artifact has been composed with Fedora's
  unified `image-builder` under WSL. It has not been installed or accepted as
  release media.
- Consequently installation, visible first-login/GNOME interaction, physical audio, suspend, update staging, rollback, recovery boot, Secure Boot, disk encryption, and hardware behavior are unvalidated.
- The Bunny 0.2.0 integration is an explicit schema-described placeholder. Upstream reports did not qualify a signed Linux desktop artifact.
- Release base digest, Fedora repository snapshots, update public keys, registry signature policy, key ceremony, and artifact signing are not provisioned. Developer updates are disabled.
- Repeated builds and bit-for-bit/semantic reproducibility comparison have not run.
- SELinux stays enforcing with Fedora policy; the Bunny-specific policy compiles in CI but is not installed until AVC qualification.
- Recovery is an in-deployment console plus QCOW2 profile definition, not independent signed rescue media. The one-shot BLS `nomodeset` safe-graphics prototype is unqualified; signed configuration backup restore and full re-image are not automated.
- LUKS2/TPM unlock is architecture only; there is no custom installer in Phase 1.
- Only x86-64 is targeted. NVIDIA proprietary drivers, remote access, shared models, ARM64, consumer profile, custom shell/compositor, app store, and consumer branding are out of scope.

## Phase 2 additions

- Bunny Shell source, schemas, GNOME integration, tests, image definitions, themes, and demos exist, but no Phase 2 image was built or booted on this host.
- Fedora 44 GNOME Shell 50 compatibility is source-pinned and JavaScript-parsed, not runtime-tested.
- No GDM Bunny/Safe Shell login, GTK surface, extension, portal, lock/suspend, notification, multi-monitor, HiDPI, gesture, camera/microphone, battery, or accessibility session was observed.
- Bunny Core remains an explicit placeholder, so real tasks/plans/approvals/provider state and authenticated summary delivery were not exercised.
- Workspace-to-GNOME virtual desktop/window movement is schema/API scaffolding, not a runtime-qualified window controller.
- Optional tiling, clipboard history UI, full quick-settings toggles, and notification action execution are not enabled; stable GNOME facilities remain available.
- Host performance numbers cover small deterministic Python operations only, not graphical responsiveness or idle resource use.
- `image-builder` CLI and Fedora 44 package names must be reconfirmed on the actual pinned builder before accepting an artifact.

## Phase 3 additions

- Host-tested installer protocol, storage/encryption planning and safety, live/beta build definitions, first-run and application policy exist, but no production destructive Anaconda adapter or artifact/runtime evidence exists.
- No ISO/raw/QCOW2, UEFI/LUKS/Secure Boot/TPM, installation, upgrade, rollback, recovery, application runtime, accessibility, or hardware test ran.
- Alongside mode is limited to verified unallocated space. Legacy BIOS, ARM64, RAID/multipath/LVM reuse, resize, proprietary NVIDIA, stable channel, production OEM/unattended, and public-store operation are unsupported.
- Media signing hooks produce no release evidence until a signed manifest is embedded/proven in a built ISO and verified by negative tests.

See `docs/KNOWN_ISSUES.md` and `PHASE_3_REPORT.md`. Unexecuted checks remain blockers, never passes.

## Phase 5 additions

- The repository has no Phase 4/public-beta source reports or runtime evidence; Phase 5 cannot infer a beta population, reliability, issue distribution, or trends.
- Operations schemas/tooling/tests and stable guides exist, but no real issue was ingested, reproduced, fixed, updated, verified, or closed.
- Stable RC build/sign/verify entry points are fail-closed scaffolds; no candidate or publication exists.
- Every installed/VM/hardware/privacy/accessibility/soak/support approval remains blocked. `NO-GO` is authoritative.


## User journey qualification additions � 2026-08-16

The first real logins ever driven (installed machine from a journey-E
encrypted install, GDM greeter, typed credentials) found and fixed: a
first-run SIGSEGV (MemoryDenyWriteExecute on a Mesa-rendering GTK unit), the
whole bunny session-unit family starting inside the GDM greeter, companion
setup choices written to a GSettings schema that exists nowhere, an autostart
assertion aimed at the wrong wants directory, and � largest � the Bunny
session that no installed user had ever received: GDM has no DefaultSession
key, so the custom.conf default was a fiction and every user landed in stock
GNOME with the Bunny desktop inert. The installer now writes the created
user's AccountsService record (Session=bunny). What remains open:

- ~~**The ACPI power key does nothing in a Bunny session.**~~ **FIXED in
  Phase 4.** Not a power-key defect at all: the desktop was built during
  gnome-shell's startup and dismissed the login overview before
  overviewControls' `runStartupAnimation` had its first allocation, leaving
  `ensureAllocation()` unsettled for ever. `startup-complete` therefore never
  fired, `Main.actionMode` stayed `NONE`, and windowManager's
  `_filterKeybinding` dropped **every** keybinding in the session — the power
  key, the media keys and the desktop's own shortcuts alike. The desktop now
  waits for `startup-complete` before it is built, and the overview dismissal
  is guarded. Measured across eleven boots in
  `qualification/phase4/power-key/`.
- ~~**Only the installer-created user gets the Bunny session.**~~ **FIXED in
  Phase 4.** accounts-daemon user templates seed `Session=bunny` for every
  account the daemon creates — the Users panel's and gnome-initial-setup's
  `CreateUser`, which is what an OEM device uses. An account made with
  `useradd` from a shell is still never templated (measured); the greeter
  still offers Bunny to it.
- ~~**`compact` and `minimal` companion modes have no persisted
  representation.**~~ **FIXED in Phase 4.** `character.companionMode`
  carries the chrome-density axis; `off` remains `character.visible` and
  `text-only` remains the accessibility preference, with
  `Settings.presentation_mode()` the one resolver back to the wizard's
  five-way answer.
- **The first-run window covers the character.** The desktop character is a
  full-body figure on a centre-stage dais, and the centred first-run wizard
  occludes everything but its shoes. Rendering is correct (decided by
  cropping the photograph); whether the wizard should sit centre-stage over
  the character is a design question, recorded rather than judged here.
- **The package snapshot does not yet pin glibc-langpack-en.** The Phase 3
  image installs it from the network (the retained snapshot predates the
  dependency); the next snapshot refresh should fold it in.
- **Anaconda module processes read only /etc/anaconda/anaconda.conf.** The
  medium's conf.d drop-in is read by the main process alone, which is why the
  target-path redirection lives where it does; module-side path assumptions
  would regress silently if that file moved.
