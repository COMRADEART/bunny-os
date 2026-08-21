# Phase 3 — User Journey, Persistence & Legacy Issue Closure

Recorded 2026-08-16/17. Branch `feature/bunny-companion-capsules-trust`,
opened at 0f4451c9 (the Stage 2 voice-release close). Binding artifacts at
commit **376acf0e**; every later commit touches harness, tests, docs or
qualification evidence only, so the image-side delta between the artifact
commit and the final tree is none. Full provenance, including digests and
what the two machine generations carried, is in
`qualification/phase3/PROVENANCE.md`.

The standard this phase was run to: a fresh user should be able to install
Bunny, log in, configure it, use the companion and voice, reboot, and return
to the same working environment — with every claim below backed by a record
in `qualification/phase3/` or named as open. Evidence first; claims second.

## 1. Old known issues, closed first (Part 1)

| Issue | Disposition |
| --- | --- |
| Presentation-pressure Linux suite failure | FIXED. The Stage 2 failure signature (steps 17/21) was reproduced deterministically by fault injection; the mechanism is an incidental renderer fault during the pressure slice. The slice now records the fault as evidence (`incidentalRendererFault`), heals through the real 15 s health hold, and retries once. Regression tests inject recurring faults. |
| Hysteresis-recovery failure | FIXED with the same investigation: the recovery path is exercised against the real `_HEALTH_RECOVERY_SECONDS` hold via the synthetic clock; the AdaptiveSelector's 3-sample/2 s hysteresis is asserted directly. |
| Encrypted first boot FAIL row | REPLACED WITH NEW EVIDENCE — see §2. The ISQ-20260801 FAIL record stands untouched. |
| Login never driven | CLOSED — see §3. |
| choices.json persistence unproven | CLOSED — §45 chain proven end-to-end, twice (investigation and binding). |
| Locale/hostname unproven | CLOSED at runtime — see §5. |
| Track 1b GitHub auth | NOT_RUN — AUTHENTICATION BLOCKED, see §12. |
| Inherited suite failures (SPDX, pins, ShellCheck, Windows oddities) | FIXED at phase opening; see §13 for the final suite state. |

No issue was closed by explanation where a fix was possible; the two
explanations in this phase (§10, §14) name exactly what remains.

## 2. Encrypted first boot, freshly qualified (Part 4)

Binding evidence on the 376acf0e artifacts:

- **journey-e** — unattended encrypted install driven through the shipped
  setup surface (`--passphrase`, `--device-name=warren`). The medium now
  emits the **full expectation document** itself (the expected-choices
  import fix, 4f6d7de3), so every mismatch gate was armed: findings [],
  language `en_GB.UTF-8`, keyboard `gb`, hostname `warren`, account
  present, root locked, `choices.json` on target.
  `qualification/installer-journeys/evidence/journey-e/`.
- **first-boot-e** — two encrypted boots of the installed disk on one
  overlay, passphrase typed at the real prompt, both reached
  graphical.target, findings [].
- The matrix row `encryption/luks-password-unlock` was flipped FAIL→PASS by
  `import_matrix_results.py` on exactly this evidence (commit 04e294f5);
  the old FAIL record is preserved at
  `qualification/installed-system/evidence/ISQ-20260801-encrypted-first-boot-001/`.

During the investigation generation the same journey also passed at
8eb1a9dc with a host-side full-expectation re-verification
(`investigation/journey-e/installed-full.json`), because the on-medium
expectation had silently fallen back to a reduced form on every earlier
journey — one of this phase's harness-honesty findings.

## 3. The first real login (Part 5)

login-1 (investigation) was the first time a person-shaped login ever
happened on an installed Bunny machine: boot → LUKS passphrase typed at the
prompt → GDM greeter → credentials typed → session opened — attested by the
machine's own journal (sessionOpened, gdmStarted, gnomeShell,
graphicalTarget, companionService), findings []. The binding machine
repeats it on the final artifact in login-f1..f4.

What that first login found is the heart of this phase — §7.

## 4. First-run choices driven and applied (Part 6)

Binding login-f1, fresh machine, first login of the created user:

- `applied.json` reads **11/11, zero failures** — appearance, accessibility,
  companion mode and captions (into the companion settings document via
  `bunny-os companion settings set` — the phantom GSettings schema is gone),
  privacy, and the autostart enablement asserted in the wants directory the
  unit actually installs into.
- The first-run wizard was **walked through all ten pages** by the probe's
  AT-SPI `activate` verb (skips chosen where a VM cannot honestly claim a
  microphone, audible sound, or a remote provider), `first-run-complete`
  written, and login-f3 confirms the wizard never runs again.
- Zero SIGSEGV: the `MemoryDenyWriteExecute` fix shipped in the unit.

## 5. Locale and hostname at runtime (Parts 8–9)

From the running system (probe `system` verb, login-1 and login-f1):
`localectl` reports `System Locale: LANG=en_GB.UTF-8`, `VC Keymap: gb`;
`hostnamectl` reports `Static hostname: warren`; `/etc/locale.conf`,
`/etc/vconsole.conf` and `/etc/hostname` carry the same values the setup
surface collected. The root causes fixed on the way (measured, not
guessed): localed is unreachable from anaconda module processes, and
en_GB.UTF-8 was unsupported on the target until `glibc-langpack-en` joined
the image — both now handled by the executor's read-back-verified handoff
placement.

## 6. Persistence across reboots (Parts 7, 10–11)

- **Settings**: login-2/f2 configured five values through the product CLI
  (scale 1.4, dock top-left, animationIntensity 0.6, speakingRate 1.2,
  reducedMotion true); login-3/f3 read all five back identically after a
  real reboot. The same values still held at login-7, five boots later.
- **Companion mode ×3** (Part 10): `3d`, `2d`, `prerendered` each set, each
  rebooted, each read back (login-4..7). One authoritative settings
  document, written only through its guarded read-modify-write.
- **3D capability loss/recovery** (Part 11): USER PREFERENCE ≠ HARDWARE
  CAPABILITY, measured: with `renderMode=3d` persisted, the product's own
  assessment was run in two *real* environments — the probe's display-less
  environment (eligible: `text-only`) and the session's actual Wayland
  socket (eligible: `full-3d`) — and the settings document was shown
  untouched by both. The product refuses simulation hooks
  (`REFUSED_OPERATIONS`), so no fake capability flip was invented; the
  in-process degradation/recovery ladder is covered by the Part 1
  fault-injection tests against the real controller.
- **First-run marker, choices.json, voice config**: held across every one
  of the eleven reboots of the investigation machine and all four binding
  boots.

## 7. What the first real login found (the defect ledger)

Product defects, all fixed and re-proven on the binding artifact:

1. **The Bunny desktop had never been shown to an installed user** (P0).
   GDM has no `DefaultSession` key — `gdm.schemas` was read to prove it —
   so the custom.conf default was a fiction and every user landed in stock
   GNOME, where the extension is deliberately inert without
   `BUNNY_SHELL_MODE`. Every pre-Phase-3 qualification had injected
   harness AccountsService records, which is how this stayed invisible.
   Fix: the installer writes the created user's AccountsService record
   (`Session=bunny`, 0600, read-back-verified; label inherited correctly —
   verified on the binding disk). 31c20f4d.
2. **bunny-first-run segfaulted at every login**: `MemoryDenyWriteExecute`
   on a GTK/Mesa unit kills llvmpipe's JIT. Proven by a within-boot A/B
   (greeter instance with the denial crashed; the fixed instance ran until
   session end). f810747e.
3. **The whole session-unit family started in the GDM greeter** (GNOME 50's
   ephemeral `gdm-greeter` user reaches graphical-session.target).
   `ConditionUser=!gdm-greeter`/`!gdm` on six units. f810747e.
4. **Companion setup choices went to a GSettings schema that exists
   nowhere** (`art.comrade.BunnyShell`); they now go to the settings
   document. `compact`/`minimal` presentation modes have no persisted
   representation and are recorded honestly as not applied. f810747e.
5. **The autostart assertion looked in `default.target.wants`** while the
   unit installs into `graphical-session.target.wants` — the enable had
   succeeded and the report still said absent. f810747e.
6. **The Bunny session never registered with GDM** but declared
   `X-GDM-SessionRegisters=true`, so GDM kept the greeter session (and its
   unit family) alive for the whole login. Flag removed; greeter reaped —
   verified before/after on the same machine. 956add5b.

Harness defects, fixed because a harness that lies is worse than none:

7. `journalctl -b -1` graded the *previous* boot's journal (login-2's PASS
   was login-1's evidence; identical PIDs were the tell). Now selects the
   newest entry's `_BOOT_ID`. 11c549ae.
8. The probe captured its user-bus environment once, pre-display; every
   later verb ran display-less (readiness said "compositor not ready" on a
   drawing desktop; every bridge action refused). Rebuilt per request.
   37e75566.
9. A requested journey that never ran still exited 0 (login-8). Now
   `journey-incomplete`, exit 7. 37e75566.
10. JSON answers were truncated before parsing (task-trace/companion-state
    on login-13). d7bb27d5.
11. The on-medium expected-choices import pointed at the wrong tree
    (4f6d7de3) — see §2.

## 8. The primary journey (Part 13)

Binding login-f4 (and investigation login-8d, where the Bunny desktop's
first assembly was photographed —
`qualification/phase3/investigation/screens/bunny-desktop-first-assembly.png`):

ask the assistant "Resize this to 100 pixels wide" → the task plans →
the **Trust prompt is drawn on screen** → **Allow is pressed** →
`holiday-resized.png` exists at 100×50 and the source and neighbour
digests are unchanged. The factual bridge ask answers ("Your Downloads
folder is empty"), Files launches from the dock, and the desktop stays
assembled. The full realistic chain — install → encrypted boot → GDM login
→ first-run → configure → use → reboot → same environment — is the
composition journey-e → first-boot-e → f1 → f2 → f3 → f4, every link
recorded.

## 9. Failure and recovery journeys (Part 14)

- **Permission denial** (login-9): same ask, **Deny pressed** on the real
  prompt; task blocked with "the request was declined"; no file created;
  digests unchanged.
- **Task failure** (login-10): corrupt image fixture, approval granted; the
  capsule task failed *contained* — no output, source and neighbour
  untouched, the failure recorded on the task.
- **Power cut during an operation** (login-12/13b): an action task was left
  parked at its approval and the machine was cut. Next boot: companion
  active with zero restarts, the store whole and enumerable (17 tasks),
  the interrupted task in an explicit `recovering` phase — not lost, not
  corrupted, not falsely successful — and a fresh ask ran to success.
- **Renderer capability loss/recovery**: §6.

## 10. The open defect this phase leaves (Part 14/20, FIX OR EXPLAIN)

**The ACPI power key does nothing in a Bunny session.** logind logs the
press and defers to the `handle-power-key` block held by gsd-media-keys,
whose handler — the same handler whose VM branch logs and powers off in a
stock GNOME session on the same machine — never runs. Reproduced on every
Bunny-session boot; independent of the greeter (persists after the
registration fix), of the first-run window (persists with the wizard gone),
and of the capsule runtime (denied-journey boot shows it too). The Bunny
sidebar's own Power entry has not been exercised. Until fixed, orderly
shutdown from inside a Bunny session needs the UI or `systemctl poweroff`.
Recorded in KNOWN_LIMITATIONS; every binding login story carries exactly
this one finding (`unclean-shutdown`) and nothing else.

## 11. Voice regression (Part 12)

The Stage 2 primary acceptance (`accept-all.sh`) was run twice: `phase3-a`
against the investigation image and `phase3-b` against the **binding**
image (41bd07c3…), both **exit 0**: boot, settle, desktop photograph,
audio devices, microphone and spoken "Open Files", engine verification,
spoken queries, interruption, performance, voice settings at 1920×1080,
Pocket→Kitten fallback, every-provider-unavailable, providers restored,
and offline (vosk transcript confidence 1.0; Pocket spoke the reply).
Stage 2 was not reopened; this is the regression gate it asked for.

## 12. Track 1b (Part 15)

**NOT_RUN — AUTHENTICATION BLOCKED.** Both credential paths were refused
by the session permission policy; no workaround was attempted and no
publication evidence exists. The exact operator commands that complete it
(token verified to carry `write:packages`) are recorded in
`qualification/phase3/track-1b/DISPOSITION.md`.

## 13. Full suites (Part 16)

Baseline: Stage 2 closed at 5734 Linux tests with 7 failures; all seven
were fixed at this phase's opening.

- **Windows host** (04e294f5): 5698 tests — 1 failure + 7 errors, all
  PRE-EXISTING + ENVIRONMENTAL (POSIX-shell quoting tests hit WinError 2;
  the TTS provenance byte total shifts with Windows zlib/libm), all pass
  on the Linux reference target. **NEW: none.**
- **Linux reference target** (ext4 hardlink clone, user `bunny`,
  04e294f5): **Ran 5737 — OK, 24 skipped**, plus the installer sub-suite
  **Ran 172 — OK**; exit 0. Zero failures, zero errors
  (`qualification/phase3/suites/linux-suite-04e294f5.log`). Delta from
  baseline: the seven Stage 2 failures FIXED, nothing NEW.

Per-failure classification with no ambiguity class:
`qualification/phase3/suites/CLASSIFICATION.md`.

## 14. Storage (Part 18)

MONITORED, NOT A RELEASE GATE. During the final suite run the **host** C:
drive reached 100 % and the WSL VHDX could no longer grow, which killed
every WSL client mid-suite (the recorded failure signature). ~22 GiB of
superseded working disk images inside WSL were reclaimed — each only after
its graded records were staged into `qualification/phase3/` — and the
suite was re-run. No evidence was deleted; the binding machine, the
binding journey disk, and every staged record remain. The host drive
remains near-full and is the operator's to resolve; the WSL VHDX cannot be
compacted without elevation.

## 15. Scope (Part 19)

Not expanded. No new companion features, no new capsule types, no renderer
work beyond the measured defects, no voice features. The one new product
surface is the installer's AccountsService write — the minimal supported
mechanism for a defect this phase measured. `compact`/`minimal` modes and
the second-user session default are recorded as limitations, not designed
here.

## 16. Evidence map (Part 17)

- `qualification/phase3/PROVENANCE.md` — commits, digests, machine
  generations, what was injected where.
- `qualification/phase3/investigation/` — the 19 defect-finding runs, the
  8eb1a9dc journey/first-boot, the rehearsal journey records, landmark
  screenshots (stock GNOME before the session fix; the first Bunny-desktop
  assembly; both Trust prompts).
- `qualification/phase3/binding/` — journey-e, first-boot-e, login-f1..f4,
  screenshots.
- `qualification/installer-journeys/evidence/{journey-e,first-boot-e}/` —
  the canonical copies the matrix importer binds.
- `qualification/phase3/suites/` — both suite logs + classification.
- `qualification/phase3/track-1b/DISPOSITION.md`.
- Voice run artifacts live on the builder
  (`/root/bunny-ops/e2e/runs/phase3-{a,b}`, logs `voice-phase3-{a,b}.log`).

## 17. Release-gate checklist (Part 20)

| Gate | State |
| --- | --- |
| Fresh encrypted install, driven | PASS (journey-e, binding) |
| Encrypted first boot ×2 | PASS (first-boot-e, binding) |
| Real GDM login | PASS (login-1, f1) |
| User lands in the Bunny session | PASS (f1 — installer-seeded record) |
| First-run applies every collected choice | PASS (f1: 11/11) |
| First-run wizard completes and never returns | PASS (f1 walk + f3 marker) |
| Locale/hostname at runtime | PASS (§5) |
| Configuration survives reboot | PASS (f2→f3; ×3 modes in 4..7) |
| Companion ask → Trust prompt → granted action | PASS (f4, 8d) |
| Denial and failure contained | PASS (9, 10) |
| Power-cut recovery | PASS (12/13b) |
| Voice primary acceptance on the artifact | PASS (phase3-b) |
| Power key in the Bunny session | **KNOWN FAILING — open defect (§10)** |
| Track 1b publication | NOT_RUN — AUTHENTICATION BLOCKED |

## 18. Honest residuals

Beyond §10: the wizard occludes the character while open (design
question); a second user account lands in stock GNOME; `compact`/`minimal`
modes have no persisted representation; the snapshot does not yet pin
`glibc-langpack-en`; anaconda module processes read only the main
anaconda.conf; and why Journey A's locale.conf was empty rather than
containing anaconda's own C.UTF-8 fallback was never conclusively
established — the executor placement makes the outcome independent of it.

## 19. Closing state

Linux reference suite at 04e294f5, re-run after the storage incident from
a fresh `git clone --local` copy owned by `bunny`: **Ran 5737 — OK (24
skipped)**, installer sub-suite Ran 172 — OK, exit 0
(`qualification/phase3/suites/linux-suite-04e294f5.log`).

Every part of the directive has a disposition above; every PASS names its
record; the two non-PASS dispositions (§10, §12) say exactly what remains.
