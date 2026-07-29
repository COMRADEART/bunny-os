# Bunny desktop search

Bunny Search is local, per-user, metadata-only search. The entire home directory, filesystem root, parent directories, content, clipboard, credentials, and cloud services are excluded by design. Nothing is uploaded.

A user must add each existing directory explicitly. The index records only name, absolute/relative path, type, root, and modification timestamp. Symlinks are skipped; common repositories/build caches and private-key formats are excluded. The index is capped at 20,000 entries and reports truncation. Encryption state is `unknown` unless a future trusted OS API can establish it; the UI must not infer encryption from a path.

Removing a location immediately removes its entries from the stored index. Rebuild deterministically drops deleted files. If indexing fails, launcher application results, Files, and direct workspaces remain available.

```text
bunny-search status
bunny-search locations
bunny-search add /home/alice/Projects/bunny
bunny-search remove /home/alice/Projects/bunny
bunny-search rebuild
bunny-search query report
```

The periodic user timer has no network address family, bounded memory/tasks/time, and read-only home protection except systemd-managed Bunny configuration/state/cache directories.
