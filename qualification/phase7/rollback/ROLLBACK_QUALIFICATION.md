# Phase 7 rollback qualification

**PASS**, on the fourth run — and the first three runs are part of the
evidence, because they are what a harness with real verdict semantics looks
like from the outside.

## The claim

On a disk carrying the subject artifact (`e906a48793d7`, deploy commit
`1804c600`) with the Phase 5 update (`e501218f2fe0`, deploy commit
`18fd8a7d`) staged as the default, the product's own rollback path — `bootc
rollback` followed by a reboot — brings up the before-update deployment, and
the harness can prove which deployment actually booted.

## The four identities (§3)

| Identity | Value |
| --- | --- |
| Before-update deployment | `1804c600…` (`localhost/bunny-os-beta:e906a48793d7`, by origin refspec) |
| Update-target deployment | `18fd8a7d…` (`oci:/run/p5update/candidate:e501218f2fe0`) |
| Selected rollback target | `1804c600…` (from `ostree admin status` after `bootc rollback`) |
| Actually booted | `1804c600…` — agreed by three independent sources |

The three sources: the kernel's own `ostree=` argument (`/proc/cmdline`),
`bootc status --json` inside the booted system, and a per-deployment `/etc`
identity marker seeded offline before the journey — which also proves the
per-deployment `/etc` itself switched. "Machine reached healthy target" is
not among them.

## User state (§4)

`expectation.json` was written offline and committed **before any boot**
(`905df2ee` for run 1; re-cut per run as the harness was repaired, at
`3f24f1c7` for the passing run). All eight preserved markers — companion
mode, scale and position, voice configuration, Trust grants, two user-data
files, settings — are byte-identical after rollback; hostname and locale
match their recorded rules. Full table in `evidence/verdict.json`.

## The run history is the harness working

| Run | Verdict | Why |
| --- | --- | --- |
| 1 | NOT_RUN | a kernel SELinux message split the 300-byte cmdline marker across serial lines; the grader refused to guess |
| 2 | NOT_RUN | the same interleaving took the 2 KB single-line `bootc status` JSON |
| 3 | **FAIL** | Phase 5's leftover `bunny-p5-stage.service`, still enabled in the staged deployment's `/etc`, powered the machine off mid-`bootc rollback` |
| 4 | **PASS** | `dmesg -n 1` + short validated markers printed twice; the journey owns the boot |

Three harness defects, found by the harness's own refusal to pass. Run 3 in
particular is the exact class this harness was built against: a machine that
reached a healthy target while the thing being measured had not happened.
Each repair is a commit (`2c7426f3`, `55636756`, the p5-leftover fix) with a
constructed-log regression where one applies.

## What this does and does not qualify

Qualified: the deployment-switch rollback journey on the subject artifact
chain, in a KVM guest, with state preservation against a prior expectation.
Not qualified: rollback on physical hardware (external gate), rollback of an
encrypted installation, and any UI surface for rollback (`rollback-ui` stays
NOT_RUN in the accessibility matrix).

## Evidence

| Path | What |
| --- | --- |
| `expectation.json` | the run-4 expectation, committed before its boots |
| `evidence/boot-restage.log` | boot S: observed already-on-target, flipped nothing |
| `evidence/boot-rollback.log` | boot R: `bootc rollback`, exit 0, new order recorded |
| `evidence/boot-verify.log` | boot V: the before-update deployment, three sources |
| `evidence/verdict.json` | the graded result, PASS |
| `evidence/run-{1,2,3}-*/` | the failed runs' verdicts and expectations |

Reproduce: `prepare.sh` → commit `expectation.json` → `run-journey.sh`
(refuses to boot until the committed expectation matches). The grader is
`verdict.py`, unit-tested by `tests/release/test_rollback_verdict.py` over
fifteen constructed journeys.
