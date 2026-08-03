# Screenshot review artifacts

Scenario specifications live in source control. Deterministic renders are
written to `build/visual/screenshots/` by `make visual-screenshot`; they are
review artifacts, not functional proof or release evidence.

Each rendered scenario is paired with structural and accessibility assertions
in `tests/visual/` and `tests/accessibility/`.
