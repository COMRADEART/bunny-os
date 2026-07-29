# ADR-008: Terminal integration

- Status: accepted
- Date: 2026-07-28

## Decision

Keep GNOME Terminal and the user's normal shell. Add an inspectable, editable, non-executing command proposal format with parsed compound-command classification, cwd, environment changes, sandbox/checkpoint flags, dry-run hint, permission flag, and cloud-history disclosure.

## Consequences

Unknown/shell-wrapped/substitution commands are high risk. Classification does not confer permission and execution requires Bunny capability and sandbox revalidation. A custom terminal emulator and invisible command execution are rejected.
