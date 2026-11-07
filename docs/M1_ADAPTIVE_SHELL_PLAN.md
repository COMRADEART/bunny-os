# M1 Adaptive shell — Hyprland path

## Decision

Hyprland PR #62 is merged and project preference selects Hyprland for desktop customization. M1 implements Adaptive Hybrid **Desktop / Focus / Studio** on that primary session. GNOME Shell extension layouts are **not** the M1 delivery surface; `bunny-gnome` and Safe Shell remain available unchanged.

Unresolved product docs that still say “GNOME/Mutter only” (Adaptive Hybrid Spec §10.1 wording vs ADR-031) are tracked separately as *Reconcile Adaptive Hybrid with Hyprland*. This milestone does not rewrite the Spec; it implements against live `main` + preference.

## Scope

| In | Out |
|---|---|
| Pure layout solver + retained task cursor state | Token Graphite/Silver redesign (M2) |
| Presentation-backed task rail model | Character identity changes (M3) |
| `bunny-adaptive-layout` CLI + Waybar module + keybinds | Broker / approval policy changes |
| Interaction contract doc | Guest AT-SPI / spoken e2e claims |
| Host unit tests | Hermetic package-lock refresh |

## Migration

1. Image already installs `shell/components/hyprland` → `/usr/share/bunny-shell/hyprland`.
2. `shell/services/bin/bunny-adaptive-layout` installs via existing `shell-commands` glob to `/usr/bin`.
3. No store schema migration; new state file `~/.local/state/bunny-shell/adaptive-layout.json` (XDG).

## Rollback

Revert this PR. Hyprland session returns to prior keybinds/Waybar; no Companion store impact; Safe Shell untouched.

## Evidence labels

| Check | Label |
|---|---|
| Host unit tests for layout/rail/CLI | PASS when green |
| `hyprctl keyword` apply on this cloud host | **NOT_RUN** unless Hyprland session present |
| Guest GNOME/Hyprland AT-SPI | **NOT_RUN** without shell-test QCOW2 |
| Stable release / pilots | Unchanged **NO-GO** / **BLOCKED** |
