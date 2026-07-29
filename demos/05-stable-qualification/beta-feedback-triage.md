# Beta feedback triage

Create a synthetic schema-version-1 export with no real identity/content. Run `make import-beta-feedback FEEDBACK_EXPORT=/absolute/path/export.json`, inspect `build/out/phase5/issue-ledger.json`, and confirm identifiers are redacted, severity is unconfirmed, merge is unmerged, and automatic closure/reduction counts are zero.
