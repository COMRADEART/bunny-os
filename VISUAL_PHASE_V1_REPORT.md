# Bunny Desktop Visual Phase V1 report

> **VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE**

## Scope and branch

Work is isolated to `visual/bunny-desktop-v1`, based on
`54907c30255c79f834fca2b71760b17ad78fed96`. No release, qualification,
archive, stable, pilot, signing, image-publication, or evidence target was
changed. `main` was not modified or merged. The preview never selects itself as
the default session.

## Implemented

- A separately packaged `Bunny Visual Preview` Wayland/GNOME session entry,
  GNOME session definition, GNOME Shell mode, and guarded launcher. The mode
  inherits upstream `user` and enables only `bunny-desktop-v1@bunny-os.org`.
- A token-driven dark, light, and high-contrast design system covering colors,
  type, spacing, radii, motion, elevation, symbolic identity, focus, and
  reduced motion. Shell and GTK CSS are generated from the same token sources.
- A preview-only GJS desktop frame with Bunny launcher, workspace/focused-app
  context, visible privacy/task state, modular Quick Settings, categorized
  Bunny notifications, adaptive/auto-hide dock, overview rail, multi-monitor
  repositioning, overflow, keyboard focus, and favorite drag/drop.
- A keyboard-first `Super+Space` Command Palette backed by observed GNOME apps,
  open windows, workspaces, settings, recent-file state, diagnostics, approval,
  and platform power UI. Results disclose whether they open, switch, change,
  require approval, or open confirmation. Search text is never sent to a shell.
- Right-side Assistant and Approval panels. Assistant state separates user,
  assistant, proposal, execution, completion, failure, and approval-required
  roles/states. Approval cards expose component, operation, resources,
  privilege, network/data impact, reversibility, reason, expiration, and
  severity.
- GTK 4/libadwaita Control Center, Approval Center, Assistant, Diagnostics, and
  Welcome applications. Welcome works with Bunny disabled, local-only mode, no
  account, no cloud provider, and no internet; it saves only non-secret local
  preferences and never enables a service.
- First-class Normal, CompactLayout, and FocusMode variants. CompactLayout uses
  component-specific geometry rather than global scaling. FocusMode keeps an
  explicit exit, summon edge, accessibility entry points, approvals, failures,
  security/critical/system-error and battery-critical exceptions.
- Original Bunny mark, boot/Plymouth/bootloader sources, login/lock concept,
  six original wallpaper families, symbolic and application icon recipes,
  onboarding/empty-state illustration, and optional sound-language contract.
- Additive, non-root build/preview/test/a11y/screenshot/package/clean tooling and
  a deterministic non-release tar package.

## Functional status

The following paths execute on this development host:

- `visual-build`: JSON/CSS validation, 77 deterministic SVG renders, Python
  compile checks, and a 113-file package stage.
- `visual-test`: 34 visual tests plus five Visual V1 accessibility tests.
- `visual-a11y`: source-level accessibility audit and supported-viewport model.
- `visual-screenshot`: 18 deterministic, permanently labelled mock review
  scenarios.
- `visual-package`: deterministic prototype archive assembly with mock fixtures
  excluded and an embedded non-release notice.
- Welcome preference persistence is tested in an isolated temporary config
  directory and writes no credential, secret, telemetry opt-in, or provider
  connection.

GNU Make is unavailable on this Windows host. The nine Make targets are present
and source-tested; their exact `visual/tools/visual.py` handlers above were run
directly.

The GJS and GTK implementations are source-complete but were not launched in a
real GNOME/GDM environment on this Windows host. Their live runtime status is
therefore **unverified**, not claimed functional evidence. The packaged session
is selectable after installation on a compatible GNOME target by construction;
actual GDM selection remains a required Fedora/GNOME test.

## Explicit mock and concept-only work

- `BUNNY_VISUAL_MOCK_MODE=1` reads the development fixture and displays a
  permanent `VISUAL MOCK DATA` banner. Approval decisions are disabled in mock
  mode. The fixture is excluded from package staging.
- All 18 deterministic screenshots are mock review artifacts. They are not
  desktop-function proof and are not qualification evidence.
- Bootloader, Plymouth, startup/shutdown, recovery, login, and lock visuals are
  source concepts and installable preview assets; none is activated by this
  branch or package.
- Sound work is a bounded event-language specification. No placeholder sound is
  installed because a sound must not imply a result before backend truth.
- The demo storyboard and `wf-recorder` capture script are implemented. No
  recording is claimed because GNOME/Wayland and `wf-recorder` are unavailable
  on this host.

## Existing backend dependencies

- GNOME Shell, Mutter/Wayland, GNOME overview/search, application registry,
  workspaces, windows, platform power confirmation, system status, and GNOME
  Settings remain authoritative.
- The existing privacy-filtered Bunny per-session projection supplies task,
  provider, approval, activity, notification, and result state. Missing or
  invalid state is presented as unavailable.
- Approval submission depends on the existing fixed
  `/usr/bin/bunny-approval-decision` adapter contract. When that adapter is not
  installed, `Approve` and `Deny` are visible but disabled with an explanation;
  the visual layer never grants authority itself.
- Standard GDM authentication, accessibility, keyboard, network, power, and
  session selection remain upstream. No custom authentication exists here.

## Performance measurements

Latest deterministic measurement in `build/visual/performance.json`:

| Measurement | Result |
| --- | ---: |
| Asset generation + package staging | 396.55 ms |
| Wallpapers rendered | 48 SVGs |
| Review screenshots rendered | 18 SVGs |
| Package stage | 113 files |
| Prototype archive | 30,970 bytes |
| Continuous polling loops in visual state adapter | 0 observed by source test |
| Visual-layer network requests | 0 implemented |

This measurement is build/staging latency, **not** GNOME UI latency. Command
Palette under 150 ms, Quick Settings under 150 ms, Assistant under 250 ms, 60
FPS, idle CPU, GPU behavior, and multi-monitor animation performance require an
instrumented live GNOME run and are not claimed on this host.

## Accessibility results

- 39/39 Visual V1 source and accessibility tests pass.
- Dark, light, and high-contrast semantic text roles pass the automated 4.5:1
  token contrast baseline.
- Normal, CompactLayout, and FocusMode layout bounds pass for 1366×768,
  1920×1080, 2560×1440, and 3840×2160 at 200% logical scaling.
- Keyboard result navigation, Escape dismissal, visible focus CSS, neutral
  critical-approval focus, programmatic labels, reduced-motion zero durations,
  FocusMode exit, and critical notification exceptions pass source assertions.

The audit is intentionally labelled `source-level baseline; runtime AT-SPI/Orca
validation remains required`. Orca speech, screen magnifier, real 200% rendering,
touch hardware, keyboard traversal under Mutter, color-vision simulation, and
GDM pre-authentication accessibility were not available on this host.

## Known limitations

1. No compatible GNOME Shell/GDM runtime was available, so session startup,
   Shell API compatibility, live keyboard traversal, focus return, drag/drop,
   multi-monitor behavior, and visual timings remain unverified.
2. GNU Make was unavailable; target wiring was source-tested and each underlying
   Python command was executed directly.
3. `glib-compile-schemas` was unavailable. The source XML is staged in both the
   extension and system schema paths; a Fedora package build must compile it.
4. The approval decision adapter is not present in this checkout, so the visual
   decision controls correctly remain disabled.
5. FocusMode suppresses only non-critical Bunny activity. It deliberately does
   not intercept or suppress GNOME security and system notifications.
6. Boot and login visuals are not activated. Firmware remains vendor-owned and
   upstream GDM remains the authentication implementation.
7. Sound assets await hardware loudness/accessibility testing; only the event
   contract is delivered.
8. Review screenshots are generated SVG compositions, with local PNG renders
   used only for visual inspection. They are not captures of a live shell.
9. The recorded demo requires a nested GNOME/Wayland environment and
   `wf-recorder`; only its review-ready storyboard and capture script exist.
10. No release qualification, ISO, stable tag, pilot, production signing key, or
   evidence update is created or implied.

## Screenshots produced

Generated under ignored `build/visual/screenshots/`:

`empty-desktop`, `multiple-windows`, `workspace-overview`, `command-palette`,
`quick-settings`, `assistant-panel`, `approval-request`, `critical-approval`,
`notification-center`, `focus-mode`, `compact-layout`, `light-mode`, `dark-mode`,
`high-contrast`, `scaling-200`, `offline`, `bunny-disabled`, and
`provider-unavailable`.

Each has an SVG review artifact and this host also produced a local PNG copy for
inspection. Every artifact is visibly marked `VISUAL MOCK DATA`.

## Files changed

94 source paths are introduced or changed relative to the requested base,
grouped as follows:

- Root/build entry points: `.gitignore`, `Makefile`, and this report.
- Architecture: `docs/BUNNY_VISUAL_ARCHITECTURE.md`,
  `docs/BUNNY_SESSION_ISOLATION.md`, `docs/VISUAL_PHASE_V2_OPTIONS.md`.
- Session: all four `sessions/bunny-visual-preview*` sources.
- Shell: `shell/bunny-shell-extension/` metadata, schema, generated CSS, icon,
  state/fixed-action services, mock fixture, entry point, and nine components.
- Applications: five `apps/bunny-*` launchers/desktop files and
  `apps/common/bunny_visual/` runtime, presentation, and generated GTK CSS.
- Visual system: `visual/` brand, visual, interaction and accessibility guides;
  token files; logo, boot, login, wallpaper, icon, illustration and sound
  sources; mock boundary; screenshot scenarios; demo storyboard/capture script;
  build, render, layout, CSS-generation and a11y tools.
- Tests: seven `tests/visual/` sources and
  `tests/accessibility/test_visual_v1_accessibility.py`.

Generated build outputs remain under ignored `build/visual/` and are not source
changes.

## Branches affected

| Branch | Effect |
| --- | --- |
| `visual/bunny-desktop-v1` | Six deliberate Visual V1 commits; only affected branch |
| `main` | Unchanged; no merge performed |
| `feature/first-login-product-corrections` | Unchanged |
| Release, qualification, archive, stable, and pilot refs | Unchanged |

## Stop-state assessment

The preview session definition, design system, desktop frame, Command Palette,
Assistant and Approval surfaces, three layout modes, theme modes, keyboard
paths, accessibility baseline, representative review renders, package stage,
and reports are implemented. Branch push and draft visual-review PR are the
only repository-hosting actions after this report. Live GNOME/GDM, AT-SPI/Orca,
performance, schema compilation, and recorded-demo verification remain
explicit follow-up work and prevent any release-quality claim.
