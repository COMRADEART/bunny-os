# Reproduction protocol

What the project does when it tries to reproduce a tester report. Defined
before any real report exists, so the process cannot be bent around an
inconvenient one. Attempts are recorded in
`qualification/phase12/reproductions.json` and validated by
`tools/alpha_ops.py`; the derived register joins them to findings.

## The ten steps, in order

1. **Preserve the original report.** It is already sealed in the intake;
   nothing in this protocol touches it.
2. **Verify artifact applicability.** Which artifact does the report bind
   to? An unbound report can still be investigated, but whatever is found
   binds to the artifact actually tested, not to the report's guess.
3. **Identify the tested artifact.** The reproduction names the artifact
   it runs on, by identifier, before it runs.
4. **Record the reproduction environment.** VM configuration or hardware
   sketch — enough that the attempt is itself reproducible.
5. **Record the hypothesis.** What are we expecting to see, and why.
6. **Execute the attempt.**
7. **Preserve the result.** Logs, measurements, screenshots — the
   attempt's own evidence, referenced from the attempt record.
8. **Classify reproducibility.** One of:

       NOT_ATTEMPTED   REPRODUCTION_QUEUED   REPRODUCED   NOT_REPRODUCED
       INSUFFICIENT_INFORMATION   ENVIRONMENT_DEPENDENT

9. **Do not rewrite the tester report.** Whatever the outcome, the
   tester's words stand. The attempt is *additional* evidence beside
   theirs, never a correction of it.
10. **Bind any technical finding to the artifact actually tested.**

## The critical rule

    NOT_REPRODUCED != INVALID

A report that nobody could reproduce remains valid user evidence with
its confidence stated. It is not closed, not downgraded, not archived
out of sight. The attempt record carries its own limitations — what was
not tried, what could not be matched about the tester's environment —
because "we could not reproduce it" is a statement about the attempt at
least as much as about the report.

## Successor artifacts

A reproduction on a successor artifact proves nothing about
`e906a48793d7` (and vice versa) unless the Phase 10 applicability engine
records that relationship explicitly. An attempt on a different artifact
is preserved with the finding but moves its reproducibility status only
for the artifact it ran on.
