# Adaptive Hybrid Spec ↔ ADR-031 / Hyprland reconciliation

**Status:** Accepted for implementation authority on `main`  
**Date:** 2026-11-07  
**Parent:** M1R Hyprland live integration  
**Inputs:** `docs/Bunny_OS_2_Adaptive_Hybrid_Spec.md`, `docs/adr/ADR-031-hyprland-desktop-customization.md`, project preference (Hyprland)

## Conflict

The Adaptive Hybrid Spec (§10.1) chose Fedora 44 bootc + **GNOME/Mutter** as the foundation and required owner sign-off before replacing Mutter. ADR-031 and merged PR #62 made **Hyprland** the primary Bunny session (`bunny`), with transitional `bunny-gnome` and Safe Shell on GNOME.

## Resolution (owner preference + merged main)

| Concern | Authority now |
|---|---|
| Primary customization compositor | **Hyprland** (ADR-031, `bunny` session) |
| Adaptive Hybrid Desktop/Focus/Studio | Implemented on **Hyprland** chrome + GTK task rail |
| Task / presentation / approval truth | Unchanged: CompanionRuntime + PresentationProjector |
| Safe Shell / recovery | **GNOME** Safe Shell unchanged |
| Transitional GNOME Bunny | `bunny-gnome` remains selectable |
| Spec prose that says “GNOME/Mutter foundation” | **Superseded for primary session** by ADR-031; Spec remains design authority for layouts, rail semantics, a11y, and security invariants |

## Non-negotiables retained from the Spec

- One canonical event store and PresentationProjector
- No invented progress; no UI-owned approvals
- No absolute Wayland placement claims
- Deny-by-default Trust; broker allowlist unchanged
- Character may be disabled; Files/Terminal/Settings work without Companion
- Guest/hardware evidence stays `NOT_RUN` until measured

## Follow-ups

- Optional later edit of Spec §10.1 wording to cite ADR-031 explicitly (doc-only)
- When to retire `bunny-gnome` remains an open product decision (`docs/HYPRLAND.md`)
