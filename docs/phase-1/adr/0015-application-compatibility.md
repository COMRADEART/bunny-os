# ADR 0015 — Application compatibility

**Status:** Proposed — pending Phase 0 amendment A15 · **Date:** 2026-07-26 · **Spec:** §20.5, §21

## Context
D1 makes intent an authoritative layer *over* applications, never a replacement, with escape to manual control permanent. Wayland deliberately restricts screen capture and input injection, and every production Linux computer-use stack shipping today falls back to `ydotool` writing to `/dev/uinput`.

## Decision
**A three-tier ladder with a constitutional floor.**

- **Tier 1 (default):** read the AT-SPI accessibility tree with query pushdown. **Act on elements by role and name, never by pixel coordinates.**
- **Tier 2 (explicitly granted):** `xdg-desktop-portal` ScreenCast over PipeWire for visual understanding. The portal's `persist_mode` plus `restore_token` are enforcement artifacts bound to Bunny's C2 grant; they never substitute for the authoritative Grant Ledger record.
- **Tier 3 (separately granted):** input via RemoteDesktop `ConnectToEIS` and libei, so the compositor attributes and can block every event.

**The proposed floor, conditional on A15:** model-directed Bunny never writes to `/dev/uinput`, installs or connects to `ydotoold`, instructs the user to join the `input` group, or receives generic privileged execution. Any process that can reach that socket can synthesize arbitrary input — an unbounded authority and a C2 violation by construction. Direct user Manual Control remains available and returns no continuation token to the agent.

**Bunny does not attempt window embedding.** Applications launch as ordinary session children. The ordered task list, not a window layout, is the interface.

## Alternatives
- *Coordinate-driven automation* — rejected: unverifiable, unattributable, silently breaks on layout change, and produces audit records that cannot be checked.
- *Permit `/dev/uinput` behind a grant* — rejected: the capability cannot be scoped, so a grant over it is not meaningfully bounded.

## Consequences
Bunny's supported-compositor list is **explicit and enforced by capability negotiation**, not assumed — portal input support is merged in the major desktops with open issues elsewhere. Where only a coordinate path exists, the capability is not offered.

## Risks
The proposed refuse-list floor is what pulls the compositor question forward (§20.4, R-5). This Phase 1 proposal records that consequence rather than pretending A15 is already authority; deferral leaves the dependent application-control branch disabled.

## Validation required
P26 (end-to-end AT-SPI target identity and action completion across named toolkits), P27 (portal authorization and restore-token behavior across reboot, revocation, and compositor restart).

## Phase 0 principles satisfied
C2, C4, D1, D16, §7 (manual takeover).
