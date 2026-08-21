# Phase 7 head certification

Run as `bunny` from the ext4 clone, per the reference-target runbook, by
`qualification/phase7/verify-at-head.sh` — commit asserted, test-count floor
asserted, one run at a time under the lock.

| Attempt | Commit | Discovered | Run 1 | Run 2 | Result |
| --- | --- | ---: | --- | --- | --- |
| 1 | `60d7531b` (the report commit) | 6072 | FAILED (3) | FAILED (3) | **caught its own tree**: the three portability validators flagged shellcheck findings in Phase 7's new harness scripts (SC2164, SC2001, SC2295) |
| 2 | `e65e3df0` (findings fixed) | 6072 | **0 failures** | **0 failures** | **CLEAN** |

The first attempt is kept, not discarded: a certification that has never
failed on a real defect is a certification nobody has tested. The three
findings were tooling style/robustness in scripts committed by this phase;
no evidence or product code changed between the attempts
(`git diff 60d7531b..e65e3df0` touches two harness scripts only).

The floor is 6030 — Phase 6's count — and the head discovers 6072: the
42 new tests are the Phase 7 gates and graders (frozen evidence, script
executability, rollback verdict, recovery verdict), which therefore run in
every future certification.

Note for readers of attempt 1's log: the `--- installer sub-suite ---`
section reports `tests/installer` as not importable under the sub-suite
invocation; the directory is one of the known undiscovered test directories
(no `__init__.py`) and is equally outside both attempts' counts. The
authoritative number is the discovered count above.
