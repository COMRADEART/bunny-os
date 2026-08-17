# Alpha feedback — the instrument, and the zero it currently holds

**Alpha testers: 0. Feedback records: 0.**

§21 says *"begin real Alpha usage"*. Phase 5 cannot: it has no testers, and
recruiting them is not an engineering act. What it can do — and what was
actually missing — is make sure the instrument can hold what §21 asks for when
someone does.

It could not. That is this document's one substantive finding.

---

## 1. The instrument that already exists

A local feedback importer has been in the repository since 2026-07-29:

* `schemas/beta-feedback.schema.json` — a per-report schema with 14 required
  fields
* `scripts/phase5.py import-feedback` — validates, **redacts before storage**,
  excludes user content, preserves source links, suggests duplicates, and
  performs **zero automatic closures and zero severity reductions**
* `make triage-report`, `make release-dashboard`

`BETA_FEEDBACK_REPORT.md`, written the same day, states the position plainly
and it has not changed: *"A zero-record ledger is not quality or reliability
evidence."*

Nothing in that needed rebuilding.

---

## 2. What was missing: the instrument could not name the product

§21 asks for feedback in five areas. Three of them are the subsystems that
distinguish this product, and **none of them had a component to be filed
under**.

The taxonomy was cut on 2026-07-29. The Companion runtime, the voice runtime,
the Trust prompt and App Capsules were all built afterwards. The component
enum went straight from `Bunny Desktop` to `Privileged broker`.

An alpha tester reporting *"Bunny did not hear me"* had two options:

* `Audio` — which is the sound stack, and a real audio defect and a speech
  runtime defect want different people looking at them
* `Bunny Core` — which is everything

**A feedback instrument that cannot name the thing being reported does not
return "unknown". It returns a misclassification that looks like data**, and
the resulting counts get quoted. That is the same failure shape as Phase 4's
false passes: a wrong answer in the shape of a right one.

Four components added — `Companion`, `Voice`, `Trust`, `App capsules` — in
both declarations (`operations/taxonomy.py` and the schema), bound together by
`tests/operations/test_feedback_taxonomy.py`, which also checks **order**,
because the importer's diagnostics quote positions.

That test lives in `tests/operations/`, which until Phase 5 was not discovered
by the reference suite at all. Both things were found in the same hour, and the
second is why the first had gone unnoticed.

---

## 3. §21's question set, mapped to fields that exist

Every question below lands in a field the schema already requires, so a report
answering them validates without further change.

### First boot — clarity, setup, trust, voice
`component: Installer` (the wizard) or `Boot`. `affectedWorkflow` carries which
of the ten steps. A trust-at-first-run question is `component: Trust`.

### Companion — usefulness, distraction, mode selection, responsiveness
`component: Companion`. "Distraction" is an `Enhancement` unless it prevents
work, in which case the severity criteria apply as written — the criteria are
in `operations/taxonomy.py` and are not restated per-report.

### Voice — recognition, latency, interruption, confidence
`component: Voice`. Recognition failures need `environment` filled in: room,
microphone, accent. A recognition report without an environment is not
reproducible and §21 says what happens to those.

### Permissions — understandable, too frequent, trustworthy
`component: Trust`. "Too frequent" is the one to watch: it is a design signal,
not a defect, and filing it as `High` would put a design conversation in a
defect count.

### Reboot — did everything return correctly
`component: Boot`, with `Companion` or `Voice` when the thing that did not
return is one of those. Persistence is a **PASS** in the VM across two reboots;
a tester contradicting that is a real finding and should be reproducible.

---

## 4. The rule that keeps the ledger honest

> §21: Do not turn anecdotal feedback into technical claims without
> reproduction.

The schema already enforces the distinction, and the enforcement is in two
fields that must not be collapsed:

* `reproducibility`: `always` | `intermittent` | `once` | `not_reproduced` |
  `unknown`
* `verificationStatus`: `unverified` | `reproduced` | `fix_pending` |
  `fixed_unverified` | `verified` | `closed`

**`not_reproduced` and `unknown` are different facts.** One means somebody
tried and failed; the other means nobody tried. A ledger that merges them can
report "we could not reproduce it" about a report nobody opened. The taxonomy
test asserts both survive.

This matters more than usual here, because Phase 4's own closing lesson was
about a hypothesis that survived one run and was written up as confirmed. An
alpha tester's single observation is exactly that shape.

---

## 5. What a tester must be told before they run it

Not a courtesy. Phase 4's §21 lists it, and the list is unchanged:

* **59 fixable vulnerability findings** (8 Critical, 28 High) inherited from
  `fedora-bootc:44`, none dispositioned by an independent review. *This is the
  single largest reason not to run it on anything that matters.*
* **No physical machine has ever booted it.**
* **No production signing key exists**; the artifact is development-signed.
* **Update and rollback are NOT_RUN.** A first install is qualified; upgrading
  and rolling back are not — so a tester should expect to reinstall rather than
  update, and should not keep anything on it they cannot lose.
* **The greeter is stock Fedora** and the desktop background did not load in
  the Alpha RC. The second is fixed in source and unqualified; the first is a
  recorded Alpha limitation.

---

## 6. Status

| | |
| --- | --- |
| Instrument | present, and now able to name the product |
| Testers | 0 |
| Records | 0 |
| Ledger | empty |

**No feedback finding appears anywhere in the Phase 5 report**, because there
is none. An empty ledger is not evidence of quality, and a phase that produced
one should say so in the same words the last one did.
