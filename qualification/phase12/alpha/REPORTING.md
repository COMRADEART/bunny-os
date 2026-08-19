# How to report

One report = one JSON record (`TESTER_REPORT_SCHEMA.json`) plus any
attachments. Check it before sending:

    python3 VERIFY_TESTER_REPORT.py my-report.json

## What kinds of report exist

    SUCCESS                 it worked; say what you did and saw
    FAILURE                 it did not work; "I could not install it" is complete
    BUG                     something specific misbehaved
    PERFORMANCE             slow, laggy, hot, loud — subjective is fine
    COMPATIBILITY           your hardware or setup and the build disagreeing
    USABILITY               you could not find, understand, or trust something
    ACCESSIBILITY           assistive tech, contrast, text size, keyboard, focus
    SECURITY_OBSERVATION    anything that looked like a security problem
    GENERAL_FEEDBACK        everything else worth saying

You choose the type that fits your experience. You are **not** required
to classify anything technically, name a component, or assign a severity
— the project does that later, separately, and your original words are
never rewritten. If you also want to fill the structured `findings`
array with categories, you may; it is optional.

## The fields that matter

Every report carries: your `tester_id`, the `report_type`, when you ran
it (`submitted_at`), your artifact identity observation
(`ARTIFACT_VERIFICATION.md` — what *you* computed, or an honest
`MISSING`), a one-line `environment_summary` (VM + hypervisor, or a
PII-free hardware sketch), and three sentences in your own words:

    user_observation     what happened, as you experienced it
    expected_behavior    what you expected
    actual_behavior      what you got

Optional, when you have them: `journey` step notes, `reproduction_steps`
(only if you can — a report without them is still evidence),
`machine_label`, logs, screenshots, `accessibility_technology`,
`performance_measurement` (method + interval + raw values if you
measured something), `additional_context`.

## Attachments

Name each attachment in `attachmentDigests` with its SHA-256 — the
intake recomputes every digest from the ingested bytes and refuses a
mismatch, so nobody can swap your screenshot later. Before attaching
logs: **remove or mask anything that looks like a credential** —
passwords, tokens, keys. The intake scans every byte and rejects the
whole submission (nothing ingested) on a likely credential, naming the
class but never the value (`PRIVACY_POLICY.md`).

## What happens to your report

It is registered into the sealed Phase 9 intake as `INTAKE-NNN`,
preserved verbatim forever — accepted, incomplete, or rejected, the
decision and its reason are recorded. Corrections are revisions
(`INTAKE-NNN-R1`) beside the original, never over it. Accepted reports
flow into the derived Alpha finding register with your words intact;
`TRIAGE_POLICY.md` and `REPRODUCTION_PROTOCOL.md` say exactly what the
project may and may not do with them. Two things it may never do:
silently upgrade your unbound report into artifact evidence, or close
your report because someone else could not reproduce it.
