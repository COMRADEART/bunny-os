# Installer reuse map

§3 asks what already exists before anything is built. This is that answer, from
reading the tree rather than from the previous phase reports.

The headline: **the decision layer is largely built and the presentation layer is
not.** Storage probing, plan validation, destructive-confirmation matching,
encryption planning, user-plan validation, the app catalogue and the setup
conversation itself are all real, tested code. What does not exist is a surface
that renders any of it, and an executor that would let a plan reach a disk.

Two facts set the shape of this phase:

1. **The graphical installer today is stock Anaconda Web UI.**
   `installer/config/iso.yaml` boots every entry with `inst.webui`, and
   `installer/config/bunny-os.conf` sets `webui = true`. Bunny's own
   `installer/frontend/app.py` is a 58-line live-session landing page whose four
   buttons — *Try*, *Install*, *Recovery tools*, *Hardware diagnostics* — have no
   `connect("clicked")` handler. Nothing in the tree launches the Bunny setup
   experience because there is no Bunny setup experience to launch.

2. **The backend deliberately cannot write to a disk.**
   `InstallerService._dispatch` raises `BackendUnavailable` on
   `installer.install.start` whenever `self._adapter is None`, and no adapter
   exists anywhere in the repository. The docstring is explicit that this is a
   design choice: *"A production live image must inject the reviewed Anaconda
   adapter; otherwise install.start fails closed before the first write
   boundary."* That gate is correct and stays; §44 requires the adapter behind it.

---

## KEEP — used as-is, not modified

| Component | Path | Why it survives untouched |
|---|---|---|
| Setup conversation | `installer/companion_flow.py` | Already the §4 journey as data, with §2's authority rule enforced rather than intended. `Stage.authority` is `companion`/`installer`/`user`; `may_proceed` returns `False` for a `user` stage until its named confirmation is present, and the Companion has no field through which it could override that. `__post_init__` refuses a user-authority stage that is skippable or that names no consequence. |
| Protocol validation | `installer/protocol.py` | Typed request parsing, replay-window enforcement (60 s), and `_contains_secret_field` recursively refusing `password`/`passphrase`/`recoverykey`/`token` anywhere in a payload. §14's "do not expose password content" is already structural. |
| Storage inventory | `installer/storage/models.py` | Strict `lsblk` parsing, serial redaction to `sha256:` prefixes, partition-path association checks, existing-OS detection incl. BitLocker. §11's "capacity, current usage, what will be erased" all come from `DiskInfo`. |
| Wrong-disk safety | `installer/storage/safety.py` | `assess_target` returns blockers for installation media, read-only, <40 GiB, unqualified sector size, RAID/multipath, mounted partitions. `confirmation_phrase` derives `ERASE /dev/xxx ABC123` from the disk's own identity, and `assert_confirmed` refuses anything else. This *is* §12. |
| Plan validation | `installer/plans/validation.py` | Required-field closure, target-identity-changed-after-probe detection, EFI/boot/system role requirement, LUKS2-only, recovery-key acknowledgement, UEFI-only. |
| Encryption planning | `installer/encryption/plans.py` | LUKS2, secret *references* (`fd:N` / `installer-secret:…`) never values, TPM2 requiring both a fallback password and an independent recovery key and an explicit PCR policy. §13's honesty requirement is enforced here. |
| User plan validation | `installer/users/validation.py` | Username/display-name rules, reserved names, `passwordSecretRef` required, autologin off, no extra groups. |
| Backend service | `installer/backend/service.py` | Peer-UID + session-token + nonce authentication, audit logging on every dispatch, fail-closed `install.start`. |
| App catalogue | `catalog/` (`registry.py`, `selection.py`, `entry.py`, `data/*.json`) | Exactly §19–§20. Entries already carry `cost`, `license`, `requiresAccount`, `trustStatus`, `sandboxCompatible`, `optionKind` (`commercial`/`open-source`), `networkCeiling`, `hardware`, and a curator-written `differences` field. The Microsoft 365 entry already states plainly that there is no Linux desktop build and that documents live on Microsoft's servers — §19's "do not imply feature equivalence" is a data field, not a hope. |
| Capsule permission model | `installer/applications/policy.py`, plus the Trust/Capsule layer from prior phases | §21: `broadFilesystemByDefault: False` and honest `"Not enforced by this package format"` labels already exist. |
| Design tokens | `shell/components/gnome-shell-extension/lib/design/tokens.js` → `shell/themes/tokens.json` | All four themes (`light`, `dark`, `highContrastDark`, `highContrastLight`), type ramp, spacing, radii, focus widths, motion durations incl. `reducedMs`, and contrast minimums. Already generated for Python consumers by `render_design_assets.mjs`. §24 is satisfied by consuming this, not by re-deciding it. |
| VM harness core | `build/scripts/vm-lib.sh`, `qmp-screendump.py`, `qmp-input.py`, `desktop_interaction.py` | Proven: QMP framebuffer capture that cannot be fooled by a compositor, virtio-tablet pointer injection, AT-SPI interaction. §42's "do not rely purely on coordinate clicks" is already how this works. |
| Story harness | `build/scripts/story.mjs` | Renders the real models through the real stylesheet in ~1 s. §35 asks for installer states *in this*, not for a new harness. |

## EXTEND — real, but insufficient for this phase

| Component | Path | What is missing |
|---|---|---|
| First-run application | `installer/first_run/app.py` | It renders a heading, a paragraph and Back/Next, and **collects nothing**. `COPY` names 13 steps; not one of them has a control. `FirstRunState.update()` — which does the validation, secret-refusal and whole-home-indexing refusal — is never called from the GUI. §28–§30 need real controls, and §45 cannot pass while the state document is written but never populated. It must also stop being a second wizard: it currently repeats language/region/keyboard, which §28 forbids. |
| First-run state | `installer/first_run/state.py` | Atomic write, secret refusal and whole-home-indexing refusal are all correct. Needs the fields this phase adds (theme, text scale, contrast, motion, Companion mode, selected apps) and needs the installer to seed it so first boot does not re-ask. |
| Live landing surface | `installer/frontend/app.py` | See REPLACE. |
| Storage planning | `installer/storage/planning.py` | `automatic_plan` produces the layout; it has no caller that reaches an executor. |
| Installation state | `installer/backend/state.py` | Has `start`/`fail`/`cancel` and a `public()` projection. Needs the real per-stage progress that §23 requires, mapped onto `PROGRESS_STAGES`, so the Companion narrates installer truth rather than a timer. |
| VM install harness | `build/scripts/vm-install-smoke.sh` | 24 lines that boot the ISO with `-serial mon:stdio` and print *"Completion must be recorded manually."* `vm-encrypted-install.sh` is 5 lines and refuses outright. §42 needs booting → navigating → confirming → completion → reboot → login, unattended. |
| Desktop VM driver | `build/scripts/desktop-drive.py`, `vm-desktop-story.sh` | Both boot an already-installed qcow2 and inject a probe with guestfish. Neither can drive an ISO. Extending is still right — the AT-SPI walk, screenshot cadence and marker discipline are proven — but ISO boots need the probe shipped *in* the live image rather than injected into it. |
| Kickstart | `installer/config/interactive-defaults.ks` | Correctly contains no `clearpart`/`autopart`/credentials. Needs the live-session hook that starts the Bunny setup surface instead of Anaconda's own UI. |

## REPLACE

| Component | Path | Why |
|---|---|---|
| Live landing surface | `installer/frontend/app.py` | Four dead buttons, `Adw.HeaderBar`, stock libadwaita styling, and a title reading *"Try or install Bunny OS"*. §5 asks for a light surface with the Companion dominant, minimal controls, and no dense technical form on first sight. Nothing here is worth keeping except the accessible-role habit. It becomes the §5 opening scene of the real setup application. |
| Web UI as the setup experience | `iso.yaml` `inst.webui`, `bunny-os.conf` `webui = true` | §50 forbids introducing a browser runtime for the setup wizard — and Anaconda Web UI *is* one, already booted by every GRUB entry. It stays available as the advanced/recovery path (§5 "Advanced / installation details"), but it is not the Bunny setup experience. |

## DEFER — explicitly out of scope for this phase

| Item | Reason |
|---|---|
| `install_alongside`, `replace_partition`, `manual` storage modes | `validate_plan` accepts them and `automatic_plan` can lay them out, but §11 asks for a clear and conservative storage UI. Erase-whole-disk plus encryption is the qualified path; the rest stay reachable through the advanced surface and are not journey-qualified here. |
| RAID / multipath targets | Already a hard blocker in `assess_target`. Not this phase's problem to solve. |
| TPM2 unlock | `EncryptionPlan` models it correctly and prior phases found that the "TPM GRUB reset" was shim's designed fallback path. Passphrase LUKS2 is what §53 Journey A qualifies. |
| Provider / cloud AI authentication | §33 is explicit that this must not be mandatory during OS installation and belongs after core system readiness. Stays in first-run, stays skippable. |
| `installer.recovery.prepare` | Returns `prepared: False` pending a production adapter that can verify recovery deployment. §47 will describe recovery honestly rather than pretend it exists. |
| Enterprise/fleet/OEM provisioning paths | §51 forbids expanding these here. |

---

## The two gaps that define the work

**Gap 1 — there is no Bunny setup surface.** Everything needed to render one
exists: the conversation (`companion_flow.py`), the design tokens
(`shell/themes/tokens.json`), the Companion presentation phases, the catalogue,
and the safety findings that populate a destructive-confirmation screen. None of
it has a renderer. This is the bulk of §5–§23.

**Gap 2 — no plan has ever reached a disk.** `install.start` fails closed by
design, which means every "installation" this repository has recorded was either
Anaconda Web UI driven by hand or a simulation. §44 is unambiguous that a static
setup UI does not complete this phase, so the Anaconda adapter behind that gate
is required, and the §42 harness has to prove it end to end on a disposable
virtual disk.

## One integration question the map surfaces

The design system renders **St CSS for GNOME Shell** (`renderStylesheet` in
`lib/design/stylesheet.js`), and the setup surface is a **GTK4** application.
St's stylesheet language is a subset of CSS and GTK4's is a different subset —
the two are not interchangeable. The honest structure is one token source with
two renderers: the existing St renderer, and a new GTK4 CSS renderer reading the
same `shell/themes/tokens.json`. That keeps §24's "reuse typography tokens,
semantic colors, spacing, radii, focus state" true in fact rather than by
assertion, and it is why `tokens.json` is already generated for Python
consumers.
