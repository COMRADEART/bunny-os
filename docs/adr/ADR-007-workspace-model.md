# ADR-007: Workspace model

- Status: accepted
- Date: 2026-07-28

## Decision

Use schema-1 private per-user JSON metadata with atomic writes and stable references to project, desktop workspace, Bunny thread/intent/plan/tasks, windows, terminals, recent files, permissions, sandboxes, and checkpoints. Bunny Core remains authoritative for referenced server objects. Credential-shaped metadata is forbidden.

## Consequences

Archive/detach cannot delete project data. GNOME monitor/workspace identifiers are hints and may be rebound after restart/hotplug. Direct Bunny SQLite access and a shared cross-user database are rejected.
