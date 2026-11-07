# M0 Architecture Delta — Bunny OS 2 Adaptive Hybrid Desktop

**Verdict:** `PARTIAL` — M0 audit and proposal complete; **no Adaptive Hybrid code changes started**. Explicit owner approval is required before M1+.

**Date:** 2026-11-07  
**Auditor host:** Ubuntu 24.04 cloud agent (`python3` only; `python` absent)  
**Design authority:** [`docs/Bunny_OS_2_Adaptive_Hybrid_Spec.md`](Bunny_OS_2_Adaptive_Hybrid_Spec.md) (ingested 2026-11-07 from owner upload; status *proposed design specification*, supplements source — does not supersede security/release/licensing)  
**Also consulted:** Adaptive Hybrid master prompt + concept UI / architecture images (non-authoritative visual intent only)  
**Earlier design baseline SHA named in spec/prompt:** `22e970d096d4867f986933fc86fb6768631fc30d` (2026-09-11)

---

## 1. Live repository state (read-only)

| Item | Value |
|---|---|
| Branch | `main` (clean; then docs-only branch `cursor/m0-adaptive-hybrid-delta-ec9e` for this deliverable) |
| `HEAD` / `origin/main` | `22e970d096d4867f986933fc86fb6768631fc30d` |
| Ahead/behind `origin/main` | `0 / 0` after `git fetch origin main` |
| Working tree at audit start | clean; no stashes |
| Match to named design baseline | **Exact match** — live `main` **is** the named baseline SHA |
| Open conflicting PR | [#62](https://github.com/COMRADEART/bunny-os/pull/62) `cursor/hyprland-desktop-customization-0493` — Hyprland as primary Bunny session (**OPEN**, mergeable; **not on `main`**) |

**Preservation note:** No destructive git cleanup was run. Demo `demos/10-product-vision/out/` is gitignored.

### Preference / assignment conflict (owner decision required)

Project preference store currently records: *“Use Hyprland for Bunny OS desktop customization.”* Sibling work opened PR #62 accordingly.

**Adaptive Hybrid M0–M6 assignment is GNOME/Mutter-authoritative:** retain Fedora GNOME 50 / Mutter Wayland, GDM base GNOME, Bunny Safe Shell; **do not start a custom compositor**. On current `main`, Hyprland is **absent**; GNOME Shell extension path is the live desktop chrome.

**M0 recommendation:** do **not** merge PR #62 into the Adaptive Hybrid track without an explicit owner decision that either (a) retires the Hyprland preference for this product direction, or (b) rewrites Adaptive Hybrid against a dual-session model (out of scope for the attached Adaptive Hybrid prompt). Until then, Adaptive Hybrid work targets GNOME paths only.

---

## 2. Release and qualification status (re-evaluated; not promoted)

From `README.md`, `STABLE_RELEASE_GO_NO_GO.md`, `QUALIFICATION_CANDIDATE_READINESS_REPORT.md`, and host demo report:

| Gate | Status |
|---|---|
| Source / host tests (this host, this SHA) | See §4 — host suites **PASS** |
| Qualification candidate | **BLOCKED** (3 of 14 prerequisites) |
| Stable release | **NO-GO** |
| OEM / Enterprise / Encrypted-sync pilots | **BLOCKED** |
| Physical hardware / Secure Boot / TPM / Orca runtime | **NOT_RUN** (unchanged) |
| Spoken voice e2e | **NOT_RUN** (`docs/AI_VOICE_PIPELINE_PLAN.md`) |
| Guest GNOME / AT-SPI Trust photographs | **NOT_RUN** (no Fedora 44 `image-builder` / shell-test QCOW2 on this host) |

These states are **not** promoted by M0. Historical evidence remains authoritative for what it measured.

---

## 3. Actual vs proposed component map

### 3.0 Spec reconciliation (design authority vs concept images)

[`Bunny_OS_2_Adaptive_Hybrid_Spec.md`](Bunny_OS_2_Adaptive_Hybrid_Spec.md) §3.1 / §10 is the design proposal. It **chooses** Fedora 44 bootc + GNOME/Mutter, existing **Python** CompanionRuntime, one canonical event store, existing 2D/3D renderer path, and four accessible token families. Owner sign-off is required before replacing GNOME/Mutter, moving core runtime to Rust, or changing the default humanoid identity (§9.2 / §10.4).

An earlier concept architecture image labeled “Bunny Core — Rust.” That image is **not** design authority. Live source and the written spec both defer any Rust Core rewrite. M0 defers to **current source + written Adaptive Hybrid Spec**.

Spec-proposed Adaptive Hybrid stack (§3.1):

```text
GNOME Bunny Shell and GTK clients
        → Versioned local UI and event projection
        → Canonical CompanionRuntime and task store
           ├→ Capability router and policy
           ├→ Executor + observer-only reviewers → tools/portals → broker → Fedora/GNOME
           └→ Character and voice presentation adapters → UI projection
```

**Actual `main@22e970d0` stack (source authority):**

```text
GNOME Shell 50 extension + GTK companion surfaces + humanoid character ladder
        ↕ (JSON-lines local IPC; closed CompanionProtocol ops)
CompanionGateway / CompanionService (Python)
        ↕
CompanionRuntime (sole task lifecycle) → events.py hash chain → store.py
        ↕
PresentationProjector (sole UI truth fold)
        ↕
capability/ router + approvals + ToolBroker + one executor lease
        ↕
bunny-system-broker (peer-verified UDS) + Polkit + portals + SELinux
        ↕
Fedora 44 bootc + systemd + GNOME/Mutter Wayland + GDM (+ Bunny Safe Shell)
```

| Spec / proposed concept | Actual authority | Delta |
|---|---|---|
| Bunny Shell + Humanoid | `shell/components/gnome-shell-extension/`, `companion/gtk_shell.py`, `companion/character/` | **Reuse** — polish layouts; do not rewrite |
| Versioned UI / event projection | `companion/protocol.py` + `companion/presentation.py` | **Reuse** — no second bus |
| CompanionRuntime (Python; Rust not chosen) | `companion/runtime.py` + services | **Keep Python**; Rust only with owner sign-off after profiling |
| Character / voice adapters | `CompanionGateway`, `companion/speech/`, `companion/voice/`, `companion/character/` | **Reuse**; push-to-talk default |
| Capability + approvals | `companion/approvals.py`, `capability/`, Trust surfaces | **Reuse** — no UI-owned permission switch |
| Tools / portals / broker | capsules, ToolBroker, desktop actions, broker `METHODS` | **Reuse** |
| Fedora bootc + GNOME | Phase 1 image + sessions | **Preserve**; Hyprland PR #62 conflicts with spec §10.1 |

**UI layout gap vs Adaptive Hybrid:**

| Proposed layout | Actual today | Gap |
|---|---|---|
| Desktop (familiar GNOME + compact Companion) | `LAYOUT_PROFILES = ['full','skeleton']` in `lib/layout.js`; companion modes `full/compact/minimal/text-only/off` | No named **Desktop / Focus / Studio** product layouts |
| Focus (one surface + collapsible task timeline) | `taskWorkspace.js` capsule steps; assistant panel/overlays; no authoritative collapsible **task rail** from presentation projection | **Build** Focus as presentation of same projection |
| Studio (expanded task workspace) | Capsule task workspace + launcher domains; not a first-class Studio mode | **Build** Studio as layout profile, same task IDs / cursors / approvals |
| Graphite Glass / Silver Liquid Glass | Four themes: `dark`, `light`, `highContrastDark`, `highContrastLight`; blur tokens exist; **no** glass-intensity control; **no** Graphite/Silver named styles | **Extend** `tokens.js` + regenerate |
| Task rail from canonical presentation | PresentationProjector exists; shell task UI partly capsule-shaped | Wire rail to presentation events, not a parallel progress invention |

---

## 4. Baseline test results (this host, this SHA)

Environment: Ubuntu 24.04, Linux 6.12, `/dev/kvm` present, **no** `qemu-system-x86_64`, **no** Fedora `image-builder`, display unset for demo screenshots.

| Command | Result | Notes |
|---|---|---|
| `python3 scripts/task.py audit` | **PASS** (exit 0) | 50 required documents present |
| `python3 scripts/task.py validate` | **PASS** (exit 0) | systemd unit analyze **skipped** (needs `BUNNY_VERIFY_SYSTEMD=1` on Fedora fixture) |
| `python3 scripts/task.py test` | **PASS** (exit 0) | 7455 + 206 installer tests; skipped 50 + 19 |
| `python3 scripts/task.py test-shell` | **PASS** (exit 0) | 432 tests, 2 skipped |
| `python3 scripts/task.py test-desktop-security` | **PASS** (exit 0) | 53 tests |
| `python3 demos/10-product-vision/run.py` | **PASS** host demo; **honest limits** | `guestBoot: NOT_RUN`; screenshots `0/20` (no display); units 46 PASS; `stableRelease: NO-GO`; `pilots: BLOCKED` |

**Do not claim:** guest GNOME session, AT-SPI Trust in Shell, spoken e2e, performance thresholds in `docs/PERFORMANCE.md`, or stable GO.

---

## 5. File-by-file reuse matrix (primary seams)

Legend: **Keep** = preserve contracts; **Extend** = Adaptive Hybrid work attaches here; **Do not** = forbidden rewrite / second authority.

### 5.1 Task / presentation authority — Keep

| Path | Role | Adaptive Hybrid action |
|---|---|---|
| `companion/states.py` | Lifecycle transitions | Keep |
| `companion/events.py` | Hash-chained event truth | Keep |
| `companion/store.py` | Durable store / recovery | Keep |
| `companion/presentation.py` | `PresentationProjector` | Keep; task rail **consumes** this only |
| `companion/approvals.py` | Approval gate | Keep |
| `companion/runtime.py` / `service.py` / `CompanionGateway` | Sole orchestrator + IPC gateway | Keep; typed/voice enter here |
| `companion/executor.py` / `coordination.py` / `reviewer.py` | One lease; observation-only reviewers | Keep |
| `tests/companion/test_integration_authority.py` (and related) | Single-authority AST gates | Keep / strengthen |
| `schemas/companion-*.schema.json` | Contracts | Keep; extend only with additive fields if needed |

### 5.2 Capability / security — Keep

| Path | Role | Action |
|---|---|---|
| `capability/` | One OS, hardware ceilings, no edition tiers | Keep |
| `services/bunny-system-broker/` | Exact `METHODS` / `POLICY_METHODS` | Keep; no new absolute Wayland / synthetic input methods |
| `selinux/`, `security/`, portals, Polkit | Deny-by-default MAC | Keep |
| `tests/security/` | Negative desktop security | Keep; run on every shell PR |

### 5.3 Shell presentation — Extend (M1/M2)

| Path | Role | Action |
|---|---|---|
| `shell/components/gnome-shell-extension/lib/layout.js` | Geometry solver; profiles `full`/`skeleton` | **Extend** with Desktop/Focus/Studio profiles; retain non-overlap tests |
| `shell/components/gnome-shell-extension/lib/desktopShell.js` | Live chrome | **Extend** layout switching without restarting tasks |
| `shell/components/gnome-shell-extension/lib/taskWorkspace.js` | Capsule step panel | Reuse patterns; add presentation-backed **task rail** |
| `shell/components/gnome-shell-extension/lib/taskState.js` | Phase→UI mapping | Keep aligned with presentation phases |
| `shell/components/gnome-shell-extension/lib/companionModes.js` | Size modes vs fidelity ladder | Keep distinction; map Focus compact Companion here |
| `shell/components/gnome-shell-extension/lib/topBar.js`, `bottomDock.js`, `commandSurface.js`, `sidebar.js` | Chrome | Polish; no permanent chatbot transcript |
| `shell/components/gnome-shell-extension/lib/design/tokens.js` | Sole token authority (schema 5) | **Extend** Graphite/Silver + glass intensity; regenerate via `build/scripts/render_design_assets.mjs` |
| `shell/themes/tokens.json`, extension `stylesheet.css` | Generated | **Do not** hand-edit |
| `shell/components/gnome-shell-extension/lib/trustPrompt.js`, `components/trust.js` | Trust / AT-SPI names | Keep accessible names; preserve focus order |
| `shell/components/gnome-shell-extension/lib/lockScreen.js`, Safe Shell session | Must not be obscured | Keep |

### 5.4 Character / renderer — Keep + refine (M3)

| Path | Role | Action |
|---|---|---|
| `companion/character/` (+ `three_d/`) | Package schema, ladder, OpenGL, GPU ledger | Keep; refine rig/motion with owner approval on identity |
| `tests/companion/test_three_d_isolation.py` | Import isolation | Keep green |
| Default character package / licence | Original humanoid | **Do not** silently replace |

### 5.5 Voice / models — Adapter only (M4)

| Path | Role | Action |
|---|---|---|
| `CompanionGateway.submit_task` | Sole input door | Keep |
| `companion/speech/`, `companion/voice/`, `docs/AI_VOICE_PIPELINE_PLAN.md` | Push-to-talk default; stages NOT_RUN on host | Keep policy; no continuous listen without separate approval |
| Bunny A / agent adapters | Versioned adapters | Review as adapters only — **not** a second planner |

### 5.6 Out of scope / blocked without owner

| Item | Why |
|---|---|
| Custom compositor / Hyprland as default (`PR #62`) | Conflicts with Adaptive Hybrid + Phase 1 architecture |
| Rust rewrite of Bunny Core | No measured hotspot + no owner agreement |
| Second event bus / UI-generated progress truth | Violates single lifecycle authority |
| Weakening NO-GO / NOT_RUN / skipped tests into PASS | Forbidden |
| Production keys / public release | Stop and ask |

---

## 6. Protected invariants

1. Exactly one task lifecycle + one persistent canonical event sequence; UI projects and replays.
2. No character view or shell code selects providers, approves actions, inspects raw model reasoning, or invokes OS commands.
3. `waiting_for_approval` and `error` outrank decorative work animation / celebration.
4. Success requires canonical `task_completed` (+ verified outputs), never progress chrome alone.
5. Renderer / model / GTK / extension failure must not kill user apps or block Safe Shell.
6. Browser / file / screen / mic / system ops use existing scope checks and user-mediated grants.
7. Reduced motion, high contrast, 200% text, keyboard-only, Orca remain first-class.
8. No unapproved cloud escalation; no continuous mic; no silent capture; no arbitrary root; no credential leakage; no auto-download of unreviewed model bytes.
9. `tokens.js` sole design-token authority; regenerate outputs.
10. Capability ceilings from hardware/policy — **no** Low/Balanced/High OS editions.
11. Deployment reversible; historical release evidence untouched.

---

## 7. Build / evidence blockers (honest)

| Blocker | Impact on Adaptive Hybrid |
|---|---|
| No Fedora 44 image-builder / digest-pinned shell-test QCOW2 on this host | M6 guest GNOME, GDM, Safe Shell, AT-SPI, multi-monitor, mic/speaker, suspend = **NOT_RUN** |
| QEMU binary absent (KVM device present) | Guest harness cannot run here |
| Spoken STT/TTS/model assets not in image | Voice e2e remains **NOT_RUN** |
| Stable **NO-GO** / pilots **BLOCKED** | Product polish PRs must not claim release readiness |
| Open Hyprland PR #62 vs GNOME Adaptive Hybrid | Owner decision before dual-path chrome |
| Companion motion token range `[300,420]` vs spec §5.1 `300–700` | Reconcile in M2 token change with tests |
| Concept UI shows different humanoid styling than default package | Spec §5.2 / §10.4: keep `bunny-humanoid-1` identity until owner-approved revision |

---

## 8. Milestone risks (M1–M6)

| Milestone | Smallest safe slice | Primary risk |
|---|---|---|
| **M1** Adaptive shell + interaction contract | Add layout profile enum + keyboard entry + presentation-backed task rail stub; written interaction contract doc | Overlapping layout rewrite breaking Safe Shell / lock / a11y |
| **M2** Graphite/Silver + glass intensity | Token extensions + regenerate + contrast/motion tests | Hand-edited CSS; blur cost on low GPU; HC must force opaque |
| **M3** Humanoid refinement | Mapper + isolation tests first; optional rig polish behind package version | Identity drift; completion without `task_completed`; renderer import leaks |
| **M4** Model/voice | Inventory + gateway-only path; keep PTT | Treating package presence as spoken PASS; second planner |
| **M5** Performance | Measure first on fixed tuple; then kill redundant polls/blur/idle GPU | Claiming `docs/PERFORMANCE.md` thresholds as current results |
| **M6** Qualification | Host gates + explicit NOT_RUN matrix for guest/hardware | Substituting host HTML screenshots for session evidence |

---

## 9. Prioritized implementation backlog

1. **Owner decision:** GNOME-only Adaptive Hybrid vs Hyprland preference / PR #62.
2. **M1 PR (proposed first implementation PR)** — see §10.
3. M2 token styles after M1 layout contract lands.
4. M3 character polish only with identity approval.
5. M4 voice/model adapter review (docs + inventory; no fake e2e).
6. M5 measure-then-tune.
7. M6 evidence matrix; do not invent PASS.

---

## 10. Proposed first implementation PR (after explicit approval)

**Branch name pattern:** `cursor/m1-adaptive-layouts-<suffix>`  
**Base:** `main` @ current SHA (today `22e970d0`)  
**Scope:** presentation layouts + interaction contract **only** — no token redesign, no character identity change, no broker method changes, no Hyprland.

### Exact files (expected)

| File | Change |
|---|---|
| `docs/ADAPTIVE_HYBRID_INTERACTION_CONTRACT.md` | **New** — request submit, event replay, task select, focus, window directives, attention priority, disconnect |
| `docs/M1_ADAPTIVE_SHELL_PLAN.md` | **New** — migration/rollback |
| `shell/components/gnome-shell-extension/lib/layout.js` | Add `desktop` / `focus` / `studio` profiles (map from/alongside `skeleton`/`full`); retain PANEL_KEYS non-overlap |
| `shell/components/gnome-shell-extension/lib/desktopShell.js` | Layout switch retaining task IDs / cursors |
| `shell/components/gnome-shell-extension/lib/taskRail.js` | **New** — collapsible rail from presentation projection fields only |
| `shell/components/gnome-shell-extension/lib/taskState.js` / `companionVocabulary.js` | Wire labels; no invented progress |
| `shell/components/gnome-shell-extension/extension.js` | Keyboard entry points + back to ordinary desktop |
| `tests/shell/test_desktop_layout.py` | Profiles at 1280×800, 1366×768, 1920×1080; 150%/200% scale |
| `tests/shell/test_task_rail_projection.py` | **New** — rail phases from fixtures; approval/error override; disconnect |
| `tests/companion/test_presentation_projection.py` | Assert shell does not invent phases |

### Tests to run before merge

```text
python3 scripts/task.py validate
python3 scripts/task.py test-shell
python3 scripts/task.py test-desktop-security
python3 scripts/task.py test-companion   # if layout touches presentation consumers
python3 scripts/task.py test-approvals
```

Guest/AT-SPI: mark **NOT_RUN** unless Fedora shell-test image exists.

### Rollback

Revert the PR; `skeleton`/`full` remain; Safe Shell / base GNOME unchanged; no broker or store migration.

---

## 11. Delivery format (M0)

| Field | Value |
|---|---|
| **Verdict** | `PARTIAL` — M0 complete per spec §9 exit (“read-only architecture delta and baseline measurement plan”); Adaptive Hybrid implementation **not** started; release remains independently **NO-GO** |
| **Repo/branch** | Base `main@22e970d096d4867f986933fc86fb6768631fc30d`; docs-only head on `cursor/m0-adaptive-hybrid-delta-ec9e` |
| **Design authority filed** | `docs/Bunny_OS_2_Adaptive_Hybrid_Spec.md` |
| **Implemented** | Architecture delta + reuse matrix + backlog only; no M1+ runtime changes |
| **Validated** | audit/validate/test/test-shell/test-desktop-security PASS; demo10 host PASS with guest/screenshots NOT_RUN |
| **Security / a11y** | No policy changes; Trust AT-SPI names untouched; desktop-security 53 PASS |
| **Performance** | **NOT_MEASURED** (thresholds remain acceptance targets) |
| **Risks / next** | Resolve Hyprland vs GNOME; approve §10 M1 PR scope before code |

---

## 12. Stop line

**Waiting for explicit approval** before any M1–M6 code that materially changes shell layouts, tokens, character identity, voice policy, or desktop session selection. Will not merge, release, alter approval policy, or weaken gates.
