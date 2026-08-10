# Known limitations

## Voice interaction milestone additions

- Bunny Shell push-to-talk uses the canonical companion capture, recognition,
  assistant-action and TTS path. The Alpha image definition now declares
  Fedora's native Vosk runtime and bundles the reviewed small English model;
  Fedora image composition completed with the package/model postconditions
  satisfied. A headless exact-artifact QEMU boot reached `graphical.target`,
  started the companion runtime without restarts and reported local Vosk/TTS
  readiness. No model is downloaded automatically.
- This host could not exercise a visible GNOME/Mutter/Wayland session or a
  physical microphone/speaker. The QEMU guest exposed only PipeWire's virtual
  `auto_null.monitor`. Spoken `Open Files`, TTS audibility and speech
  interruption remain graphical hardware-acceptance blockers.
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
