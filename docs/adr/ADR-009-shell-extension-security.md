# ADR-009: Shell extension security

- Status: accepted for image-owned extension; runtime qualification pending
- Date: 2026-07-28

## Decision

Ship one source-controlled extension under `/usr/share`, pinned to GNOME Shell 50, with fixed launch vectors and no root/network/provider access. The extension runs only when `BUNNY_SHELL_MODE=normal`; Safe Shell is a no-op. User services use restart/resource limits and the base GNOME session remains selectable.

Third-party extensions/plugins are not auto-installed. Future sources require signature/trust provenance, exact compatibility, explicit enablement, inventory, crash-loop disable, and safe-mode exclusion.

## Consequences

GNOME updates can break the extension, so nested Shell and full VM tests are required for every base rebase. Downloaded arbitrary shell code and a self-updating extension channel are rejected.
