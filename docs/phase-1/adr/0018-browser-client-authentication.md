# ADR 0018 — Browser-client authentication

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §24.4 · **Closes:** Phase 0 open question §22.12

## Context
Phase 1 exit criterion 6 requires that browser clients cannot exercise ambient host authority. Phase 0 §13 guarantee 12 makes the browser presentation-only. Phase 0 §18 option 2 takes a hostile-LAN stance.

**A confirmed live defect:** `src/app/websocket.ts` validates **neither `Origin` nor `Host`** on the upgrade handshake — the same defect class assigned a CVE in the MCP TypeScript SDK. The bearer token is currently the only control between a hostile web page in the user's browser and the local agent.

## Decision
Five deterministic changes, in priority order:

1. **Reject the WebSocket upgrade unless `Origin` exactly matches the expected loopback origin and port.**
2. **Reject unless `Host` is a loopback literal or `localhost` with the correct port.** Together, (1) and (2) close DNS rebinding and the hostile-page path.
3. **Pair a client-generated device key.** Initial pairing uses a 60-second, one-attempt exchange code confirmed in a trusted local Shell/terminal. It binds only the public key and identity; it does not grant a capability. Every later connection signs a fresh server nonce plus negotiated transcript hash.
4. **Never put exchange material in a URL, argv, log, stdout, or stderr.** The trusted launcher delivers/displays it out of band.
5. **Prefer a Unix domain socket or named pipe for native local clients**, but treat filesystem/DACL permissions as defence in depth rather than identity. Browser fallback uses the validated loopback WebSocket and the same device-key challenge.

Origin/Host validation and device-key proof are **non-negotiable regardless of transport.** Device authentication establishes identity only; Broker authorization remains effect-specific.

**"Bunny Box remote access" is closed as:** no open LAN listener by default, ever. Remote access means an explicitly user-established overlay network or an SSH tunnel — both of which move authentication to a layer designed for it. The local listener is treated as internet-facing, because on a shared network it is.

## Alternatives
- *Bearer token alone (today)* — rejected: it is the confirmed defect, and a token in a URL is a token in browser history, logs, and referrers.
- *mTLS* — rejected as the primary mechanism: the paired device-key challenge supplies cryptographic possession and transcript binding without operating a local certificate authority. Remote overlay/SSH authentication remains additive.
- *Binding to a LAN interface with authentication* — rejected: it makes the hostile-LAN boundary a configuration option rather than a default.

## Consequences
Bunny Box requires the user to make an explicit, informed choice to reach it from another machine, and that choice happens in a tool built for it rather than in Bunny.

## Risks
A Unix-socket transport is not directly available to ordinary browser code on every platform. Mitigated by keeping the validated, device-authenticated loopback WebSocket path as the fallback, not by relaxing validation. Pairing UX and key-store behavior require P16 testing.

## Validation required
P16 — zero successful upgrades from any foreign origin, zero successful requests with a non-loopback `Host`, zero exchange-material occurrences in URL/argv/log/output, zero nonce/transcript replay, and zero unconfirmed device pairing.

## Phase 0 principles satisfied
C4, Phase 0 §13 guarantee 12, Phase 0 §18 option 2, exit criterion 6.
