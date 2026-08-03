# Bunny OS Visual Phase V2 report

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

## Scope and safety boundary

This branch is an additive visual and interaction prototype based on main commit
`3ca74d937ccada6043b0f10fbe3c7baebe35584f`. It does not change a
qualification target, release gate, stable status, production key, image
publication path, historical evidence record, or the default GNOME session.
The package is a review tarball, not an RPM, ISO, qualified image, or release
artifact.

## Implemented

- An independently selectable `Bunny Desktop Preview` GNOME/Wayland session;
  the existing GNOME session remains available and the preview is never made
  default.
- One shared GNOME Shell action, state, approval, privacy, and settings model
  with live `regular`/`character` presentation switching through GSettings.
- A token-driven dark, light, and high-contrast system; eight static ribbon
  wallpapers; generated GNOME and GTK CSS; Normal, Compact, and Focus layouts.
- Top bar, adaptive dock, fixed-action Command Palette, tabbed system panel,
  Quick Settings, Regular Assistant, Character Assistant, approval, privacy,
  activity, and responsive presentation components.
- GTK 4/libadwaita Control Center, Assistant, Approval Center, Welcome, and
  Diagnostics applications.
- One canonical 14-pose guide set with truthful state guards, lazy loading, a
  three-entry cache, bounded placement, and semantic/decorative accessibility
  behavior.
- Five deterministic, character-free boot/authentication concepts and 26
  deterministic desktop review scenarios.
- Mock-free deterministic staging and a non-release prototype tarball containing
  111 files plus a manifest of per-file SHA-256 digests.

## Functional

The direct Python entry point supports setup, deterministic build, nested/live
preview preflight, tests, accessibility audit, screenshots, package, and clean.
The 31 deterministic tests exercise architecture, defaults, shared actions,
mode-state guards, package isolation, assets, applications, accessibility,
security, and performance contracts. Screenshot generation, token/CSS checks,
wallpaper generation, system-concept generation, package staging, and package
inspection execute on this host.

The shell and GTK implementations are executable source paths, but “functional”
here does not mean live GNOME qualification: this Windows host cannot execute
GNOME Shell, GDM, GTK/libadwaita, Wayland, or the native approval adapter.

## Mocked

- All 26 screenshot scenarios run under the explicit
  `BUNNY_VISUAL_MOCK_MODE=1` contract and permanently display
  `VISUAL MOCK DATA`.
- Screenshot network, Bluetooth, audio, update, provider, approval, privacy,
  and task states are deterministic projections for visual review.
- Mock decisions are inert, screenshots are not functional evidence, and
  `mock-state.json` plus screenshot artifacts are excluded from the package.

## Concept only

- Boot splash, shutdown, login, lock screen, and session selector are
  deterministic SVG concepts. They are not installed as Plymouth, bootloader,
  GDM, or lock-screen themes and never contain the guide character.
- `Visual Phase V3 — native Bunny Wayland shell feasibility prototype` is an
  optional future investigation only. No compositor work began in V2.

## Not tested

- A real GNOME Shell, GDM, Wayland, GTK 4/libadwaita, systemd user, or dconf
  session.
- Live mode switching, real monitor hot-plug, drag-and-drop, dock overflow,
  fractional scaling, graphics-driver behavior, and actual panel latency.
- Live Orca, magnifier, keyboard traversal, color-vision review, microphone,
  camera, screen-share, VPN, Bluetooth, media, power, or battery integrations.
- A real approval backend, package transaction, provider, network service,
  installation, RPM, ISO, boot, shutdown, login, lock, or release pipeline.

## Test results

| Area | Result | Interpretation |
| --- | ---: | --- |
| Visual/architecture/application/package tests | 21/21 pass | Deterministic source, state, asset, render, and staging checks |
| Accessibility tests | 4/4 pass | Deterministic contracts and audit execution |
| Shell security/performance tests | 6/6 pass | Fixed actions, inert mock approvals, no polling, bounded loader |
| Accessibility static audit | Pass | Seven checks pass; all four logical viewport cases fit |
| Performance static audit | Pass | Event-driven state, lazy loading, bounded cache, no continuous animation |
| Deterministic screenshots | 26/26 current | Visual mock artifacts only |
| Deterministic system concepts | 5/5 current | Character-free visual concepts only |
| Package inspection | Pass | 111 files; no mock state or screenshot entry; notice present |

The accessibility viewport audit covers 1366×768, 1920×1080, 2560×1440,
and 3840×2160 at 200% (1920×1080 logical). It reports
`liveOrcaTested: false` and `realGnomeSessionTested: false`.

## Performance measurements

- Static performance audit: 3.396 ms on this host; all five structural checks
  passed.
- Deterministic build and 111-file staging pass: 723.884 ms on this host.
- Instrumented targets are Command Palette and Quick Settings under 150 ms,
  Assistant under 250 ms, and visual-mode switching under 300 ms.
- Live panel latency and idle CPU were not measured. The target values are not
  claimed as achieved until a real Linux/GNOME run records them.

## Screenshot inventory

Regular Mode:

`regular-empty-desktop`, `regular-command-palette`,
`regular-quick-settings`, `regular-assistant-ready`, `regular-approval`,
`regular-privacy-local-only`, `regular-focus-mode`,
`regular-compact-layout`, `regular-light-theme`, `regular-high-contrast`,
`regular-offline`, `regular-error`.

Character Mode:

`character-welcome`, `character-assistant-ready`, `character-thinking`,
`character-explaining`, `character-requesting-approval`,
`character-task-running`, `character-task-completed`, `character-warning`,
`character-error`, `character-offline`, `character-privacy-mode`,
`character-compact-layout`, `character-focus-mode`,
`character-200-percent-scaling`.

Regular renders contain no character image element. Character renders contain
at most one guide; Compact, Focus, and 200% scenarios suppress it. The approval
scenario retains separate Inspect, Deny, and Approve controls.

## Files changed

The V2 branch changes 151 files: 91 under `visual-v2/`, 25 shell extension
files, 15 application files, 9 tests, 4 session files, 4 V2 architecture/future
documents, plus this report, `.gitignore`, and `Makefile`. Historical Visual V1
sources and release/qualification evidence remain unchanged.

## Commands run

```text
git fetch origin main
git worktree add -b visual/bunny-desktop-v2-dual-mode ... origin/main
python visual-v2/tools/render_wallpapers.py --check
python visual-v2/tools/render_system_concepts.py --check
python visual-v2/tools/render_screenshots.py --check
python visual-v2/tools/visual_v2.py test
python visual-v2/tools/visual_v2.py a11y
python visual-v2/tools/visual_v2.py screenshots
python visual-v2/tools/visual_v2.py build
python visual-v2/tools/visual_v2.py package
node --check <each shell/bunny-desktop-v2 JavaScript file>
python -m compileall apps/common/bunny_visual_v2 visual-v2/tools tests/visual_v2 tests/accessibility_v2 tests/shell_v2
git diff --check
```

## Required test-status answers

| Question | Answer |
| --- | --- |
| Was a real GNOME/GDM session tested? | No. The host is Windows. |
| Was Regular Mode tested? | Yes, structurally and through deterministic review/tests; not in a live GNOME session. |
| Was Character Mode tested? | Yes, structurally and through deterministic review/tests; not in a live GNOME session. |
| Was mode switching tested? | Yes at source/state-contract level without restart; not live in GNOME Shell. |
| Are character assets redistribution-cleared? | No. Redistribution remains blocked pending an explicit rights decision. |

## Known limitations

The package has not been installed or booted. Native shell/application behavior,
accessibility, responsiveness, and target latency still require a disposable
Linux GNOME test matrix. The approval adapter and observed state projection need
live backend integration. Character asset redistribution is not cleared. These
limits prevent any release, qualification, ISO publication, or merge claim.
