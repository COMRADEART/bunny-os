# Beta operations

The controlled workflow is: feedback intake → triage → reproduction → severity classification → ownership → fix → regression test → beta update → verification → closure. Each transition is recorded; none is inferred from issue age or volume.

Imports accept local structured exports only. `make import-beta-feedback FEEDBACK_EXPORT=/trusted/export.json` validates the Phase 5 schema, excludes user content, redacts identifiers before storage, preserves source attribution, and creates duplicate suggestions. It never closes issues, reduces severity, contacts reporters, or publishes an update.

Every issue records a deterministic internal ID, source/source ID, affected version, component, severity plus confirmation status, reproducibility, environment, owner, target release, workaround, verification state, evidence links, and closure evidence. Private prompts, memories, documents, screenshots, clipboard data, credentials, Wi-Fi names, and persistent user identifiers are forbidden.

Only a maintainer may confirm severity, assign ownership, merge duplicates, accept a workaround, mark a fix verified, or close an issue. High-or-greater duplicate merges require human confirmation and preserve every original record.
