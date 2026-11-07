# M1R Hyprland live integration

**Baseline:** `main@f1fa20533e00` (M1 Adaptive layouts merged)  
**Branch:** `cursor/m1r-hyprland-live-integration-ec9e`

## Verdict

**PARTIAL** — host source integration, unit evidence, and **PR-head CI (23 checks, 0 failures)** PASS; live Hyprland session, guest AT-SPI, and hardware remain **NOT_RUN** on this cloud host. Release gates unchanged (**NO-GO** / pilots **BLOCKED**).

## Post-merge CI (`f1fa2053`)

- Baseline `f1fa2053`: **22 success, 0 failed, 1 skipped** (`full-image-gate`).
- PR head `b1813c89`: **all 23 CI checks completed without failures** (subscription `github:ci:branch` on `cursor/m1r-hyprland-live-integration-ec9e`).

## Implemented

| Piece | Role |
|---|---|
| `bunny_shell/task_rail_runtime.py` | Authenticated `get_presentation_state` consumer; replay; disconnect; cursor retention |
| `bunny_shell/task_rail_gtk.py` | Accessible Focus/Studio surface + keyboard contract |
| `bunny-task-rail` | Launcher (`model`/`tree` headless modes for tests) |
| `adaptive_cli` `--apply` | Syncs rail show/hide with layout; hyprctl gaps when available |
| Spec reconciliation | `docs/ADAPTIVE_HYBRID_HYPRLAND_RECONCILIATION.md` |

## Security / a11y

- No invented percent; zero placeholder progress ignored
- No absolute Wayland placement claim
- Trust opened via existing `bunny-approvals` path; rail does not resolve approvals
- Stable accessible names asserted in host tests

## Rollback

Revert this PR. Layout state file is additive; Companion store untouched; Safe Shell / bunny-gnome untouched.

## Evidence labels

| Environment | Label |
|---|---|
| Host unit tests | PASS when green |
| Live Hyprland session / hyprctl apply | **NOT_RUN** without session |
| Guest AT-SPI photographs | **NOT_RUN** |
| Hardware mic/GPU/Orca | **NOT_RUN** |
| Screenshots of live rail | **NOT_RUN** on this host (no display) |
