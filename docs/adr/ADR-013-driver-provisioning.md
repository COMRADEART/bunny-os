# ADR-013: Driver and firmware provisioning

- Status: accepted design; hardware qualification pending
- Date: 2026-07-28

## Decision

Use Fedora's kernel, Mesa, linux-firmware, CPU microcode, fwupd, NetworkManager, BlueZ, and PipeWire packages from reviewed Fedora repositories. Intel and AMD in-tree/open drivers are the default. VirtIO and software-rendering paths are test fixtures.

NVIDIA proprietary drivers are not bundled in the Phase 3 beta candidate. Exact device, supported branch, repository/redistribution policy, kernel ABI, Wayland, Secure Boot module signing/MOK, rollback, and safe-graphics tests are prerequisites for any later experimental opt-in. Bunny never downloads firmware or drivers from arbitrary vendor URLs.

## Consequences

Hardware presence is not support evidence. Preflight reports `supported`, `supported_with_limitations`, `experimental`, `unsupported`, or `unknown` from an evidence table and records missing firmware. Physical support claims require redacted per-device execution records.
