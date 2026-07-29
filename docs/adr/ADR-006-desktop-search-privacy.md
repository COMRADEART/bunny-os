# ADR-006: Desktop search privacy

- Status: accepted
- Date: 2026-07-28

## Decision

Index only explicitly approved directories and metadata (name/path/type/mtime), locally and per user. Reject the entire home/root/parent paths, skip symlinks and sensitive/build patterns, cap entries, default to no locations, never upload, and purge a removed root immediately. Encryption is reported `unknown` until evidenced.

## Consequences

Search is less comprehensive than full-home content indexers but has an inspectable boundary and deterministic deletion. Application launch and direct workspace access do not depend on the index. Full-content, cloud, and Bunny database indexing are rejected for Phase 2.
