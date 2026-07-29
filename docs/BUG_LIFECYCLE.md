# Bug lifecycle

Allowed verification states are `unverified`, `reproduced`, `fix_pending`, `fixed_unverified`, `verified`, and `closed`. A report starts unverified. Reproduction requires a disposable environment record. A patch changes the state to fixed-unverified only after a regression test exists. Verification must run against the exact candidate commit/artifact. Closure requires retained source records and evidence.

Severity may increase when evidence warrants it. Automatic severity reduction is prohibited. Duplicate detection is advisory, never destructive: originals remain immutable and their evidence links survive a confirmed merge. A reopened issue keeps its original ID and closure history.

Blocker/Critical issues stop candidate promotion. High issues affecting common supported installation stop stable release. Security and privacy embargo records use restricted storage, minimum membership, signed patch provenance, and the security-release procedure.
