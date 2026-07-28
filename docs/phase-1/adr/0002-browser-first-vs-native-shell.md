# ADR 0002 — Browser-first vs native-shell-first, and the UI technology

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §16.2 · **Closes:** Phase 0 open question §22.4

## Context
Phase 0 left the UI technology for the task surface open, including whether the Bunny Box web client and desktop app share one implementation. Phase 0 §14 fixes the ordered task list as authoritative and the spatial view as a projection; C13 requires one deterministic Task Surface Model projection and screen-reader parity, with WCAG 2.2 AA as a Phase 1→2 gate. “Semantic Twin” is retired as an ambiguous name: the TSM is derived from domain state, while Bunny Shell owns platform accessibility mapping, localization, focus and narration.

## Decision
**One implementation: a web application, hosted in a Chromium-based desktop shell for the desktop form and served over the existing HTTP/WS front for Bunny Box.** Rendering is DOM-first; any spatial or canvas projection is an additive layer inside the same page. The terminal client remains a separate, permanently supported implementation.

D15 does **not** bind the UI layer, with one carve-out: the protocol client (transport, framing, TSM store, event replay) stays dependency-free.

## Alternatives
- *A system-webview shell (Tauri, Wails)* — **disqualified on accessibility, not on memory.** Its own documentation disclaims knowability of the WebKitGTK version across Linux distributions, which makes the assistive-technology behaviour of the shipped product unknowable at build time. That is disqualifying when WCAG 2.2 AA is a release gate.
- *A native task surface per platform* — rejected: three accessibility implementations, no sharing with Bunny Box, and no path to Mode B.
- *Terminal-only for V1* — rejected: it would defer the plan and approval surface indefinitely, and §16.1 establishes that this surface does not exist on the wire today.

## Consequences
Higher baseline memory than a webview shell; P22 sets a T1 budget of ≤250 MB idle RSS and ≤2 s cold start on low-power hardware. One shared client implementation still requires distinct platform accessibility integrations. Bunny Box and the desktop app cannot diverge, which is the point.

## Risks
Chromium is a large adopted dependency with its own update burden. Mitigated by C15's logic — it is rented rather than built, and the alternative is three accessibility implementations this project cannot maintain.

## Validation required
P9 (a TSM-authoritative client absorbs a live turn's event rate), P22 (footprint on low-power hardware).

## Phase 0 principles satisfied
C13 (accessibility as architecture), C10 (task surface authoritative), C15, D11.
