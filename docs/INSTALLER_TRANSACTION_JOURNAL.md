# Installer transaction journal

`installer/backend/transaction_journal.py` records each operation as `not_started`, `planned`, `validated`, `started`, `completed`, or `failed`. Transitions are monotonic. Destructive work cannot start before validation, and a destructive failure is never marked resume-safe. The export explicitly says rollback after destructive writes is unavailable.

Journal entries carry bounded descriptions and redacted history. Passwords, keys, tokens, user content, serials, and personal identifiers are never stored. Atomic mode-0600 writes support diagnosis and cleanup. Resume is allowed only for operations explicitly declared safe; partition changes are not represented as reversible.
