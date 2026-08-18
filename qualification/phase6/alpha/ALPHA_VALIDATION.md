# Alpha user validation

## Status: **NOT_RUN**. Testers: 0. Feedback records: 0.

Blocking condition 9 is unmet. §17 forbids converting *not executed* into
*passed by absence of failure*, and zero testers means this is unmet rather than
vacuously met.

---

## 1. What already exists, and is not rebuilt here

Phase 5 established the instrument and verified it can hold what is asked of it:
`schemas/beta-feedback.schema.json` (14 required fields), an importer that
**redacts before storage**, a taxonomy extended to cover the required question
set, and a written statement of what a tester must be told. See
`qualification/phase5/feedback/ALPHA_FEEDBACK_PLAN.md`.

Phase 6 adds the three things that plan predates: an artifact binding, a consent
record that discloses what this release class actually is, and the §15 triage
taxonomy.

---

## 2. The artifact this evaluation binds to

| | |
| --- | --- |
| Artifact | `e906a48793d7` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Medium | `bunny-os-0.3.0-live.e906a48793d7-x86_64.iso` |
| ISO digest | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |

§14: *"Do not mix feedback from multiple artifacts without labeling them."*
Every feedback record must carry the image digest the tester actually ran. Not
the version string, which two builds can share, and not the branch.

The Phase 5 build `e501218f2fe0` **must not** be given to testers. It carries no
journey evidence and has no installation medium.

---

## 3. The consent record — what a tester must be told first

Required before installation, and required as a stored record, not a
conversation.

1. **This is alpha software. It can lose your data.** Do not install it on a
   machine holding anything you need.
2. **It will never be updated.** Updates are `UNSUPPORTED` for this release
   class — `UPDATE_TRUST_ARCHITECTURE_DECISION.md`. There is no update
   mechanism, no trusted key, and no path to one in this release.
3. **Security fixes will not reach you.** The image carries 80 advisories from
   its base, 8 of them Critical, none of which can be remediated in the field.
   Remediation means reinstalling from a newer artifact.
4. **No independent security review has been completed.** The findings above
   have not been dispositioned by anyone independent of the project.
5. **No machine of this kind has been qualified.** No physical hardware
   qualification has ever run. Whether it works on the tester's machine is
   unknown, and finding out is the point.
6. **The artifact is unsigned.** It carries no signature of any kind — see
   `../signing/SIGNING_POSITION.md`. A tester cannot verify its authenticity by
   any means the project provides, only its digest against this document.
7. **What is collected**, and that reports are redacted before storage.

Items 2, 3 and 6 are new to Phase 6 and are the ones most likely to change
whether someone consents. Stating them is not optional.

---

## 4. Two evidence classes, kept apart

§14: *"Do not convert subjective feedback into objective performance claims."*

| Class | Example | May be used for |
| --- | --- | --- |
| **User feedback** | "it felt slow when the Companion appeared" | prioritisation, UX findings, a defect report |
| **Measured telemetry** | `gnome-shell` idle CPU 2.07 % over 30 s | a performance claim |

They are stored separately and never merged into a single figure. "Three of five
testers found onboarding confusing" is a feedback result; it never becomes "60 %
onboarding failure rate", which is a measurement nobody made.

The reverse is equally forbidden. A tester reporting that something felt fast is
not evidence that it was.

---

## 5. What is collected

Per `ALPHA_FEEDBACK_PLAN.md` §3, against the required question set: first
impression (clarity, polish, perceived performance, trust); onboarding
(understandable, confusing steps, completion, permission comprehension);
Companion (useful, distracting, responsive, appropriate, preferred rendering
mode); voice (recognition, latency, interruption, cancellation, permission
understanding); Trust actions (does the user understand what will happen, does
approval feel intentional, is denial understandable, is the outcome clear); and
persistence after reboot.

**Persistence deserves its own note.** The question is not only "did settings
return" but "did anything change that the user did not expect". A setting that
returns *different but better* is still a surprising state change and is
reported as one.

---

## 6. §15 — defect triage

Every finding is classified as exactly one of:

    RELEASE BLOCKER
    SECURITY
    DATA LOSS / CORRUPTION
    PRIVACY
    FUNCTIONAL DEFECT
    PERFORMANCE
    UX
    COSMETIC
    HARNESS / MEASUREMENT
    ENVIRONMENT

and records: reproduction, affected artifact (by digest), severity, evidence,
owner, disposition.

Machine-readable form: `triage-schema.json`.

**Four rules that do the work.**

* **`RELEASE BLOCKER`, `SECURITY`, `DATA LOSS / CORRUPTION` and `PRIVACY` are
  the four classes that make blocking condition 9 unmet while open.** The others
  are recorded and do not block.
* **`HARNESS / MEASUREMENT` is a real classification and is used.** This project
  has found six harness defects, four of which produced green results. A finding
  that turns out to be an instrument defect is reclassified, not deleted — the
  original report stays.
* **`ENVIRONMENT` requires a measurement, not an inference.** "Blocked on disk"
  was carried for a week on an untested claim about the host, and the disk was
  never the problem. An environment classification names what was measured.
* **A defect is never fixed silently.** §15: *"Do not fix a defect silently and
  erase the original report."* The report keeps its original text, its
  classification history and its disposition; a fix is an added disposition, not
  an edit to the finding.

---

## 7. What would close it

Testers, given the artifact named in §2, having consented to §3, returning
records that validate against the existing schema, with every
`RELEASE BLOCKER` / `SECURITY` / `DATA LOSS` / `PRIVACY` finding closed.

Recruiting them is not an engineering act, and Phase 6 does not present a
well-specified protocol as progress against a gate that needs people.
