# CI portability baseline

Every GitHub Actions failure observed against the qualification-evidence candidate
commit, recorded before any of them was repaired.

| Field | Value |
| --- | --- |
| Candidate commit | `9dc7e33f66a270150dfc2c1c9950b1e974a3c2ae` |
| Branch | `feature/qualification-evidence-closure` |
| Working tree at capture | clean |
| Runs inspected | 30550930290, 30550930395, 30550930414 (all `pull_request`, PR #3) |
| Runner | `ubuntu-24.04` hosted, Python 3.13.14, ShellCheck 0.11.0 |
| Captured | 2026-07-30 |

Job outcomes as found:

```text
Qualification evidence closure (30550930290)
  FAIL  Two-person development signing drill
  FAIL  Qualification evidence suites
  FAIL  Per-CVE reachability framework
  PASS  Ten CI protections
  FAIL  Gate state

Release blocker closure (30550930395)
  FAIL  Blocker closure test suites
  PASS  Vulnerability report generation, Deterministic build checks,
        Stable evidence validation, Pilot gate closure assertion,
        Development signing drill, Package minimisation,
        Recovery image validation, Release manifest validation, Licence gate

Bunny OS Phase 1 and 2 (30550930414)
  FAIL  host-gate
  FAIL  phase7-gate
  FAIL  systemd-units
  FAIL  gnome-integration
  PASS  installer-gate, selinux-policy, operations-gate
  SKIP  full-image-gate
```

Five of these eight failing jobs are the same defect seen through five job
definitions. The table below is keyed by defect, not by job.

---

## F1 — Report output path outside the repository raises `ValueError`

| | |
| --- | --- |
| Workflow | `.github/workflows/qualification-evidence.yml` |
| Job | `Two-person development signing drill` |
| Step | `Run the drill with two separate development keys` |
| Local reproduction | **Reproduced.** `python scripts/two_person_drill.py --out "$env:TEMP\...\drill.json"` fails identically on Windows. |
| Affects evidence integrity | **No.** The drill's nine checks all reported PASS and the record was written correctly before the crash. Only the closing progress message failed. |

Exact error:

```text
  PASS     disagreement-refusal: signer B refusing blocks the authorisation: ...
Traceback (most recent call last):
  File "scripts/two_person_drill.py", line 387, in <module>
    raise SystemExit(main())
  File "scripts/two_person_drill.py", line 377, in main
    print(f"\nwrote {args.out.relative_to(ROOT)}")
  File ".../pathlib/_local.py", line 385, in relative_to
    raise ValueError(f"{str(self)!r} is not in the subpath of {str(other)!r}")
ValueError: '/home/runner/work/_temp/two-person-signing-drill.json' is not in the
subpath of '/home/runner/work/bunny-os/bunny-os'
```

**Root cause.** `Path.relative_to` is a *partial* function: it raises when the
path is not under the root. The drill uses it to shorten a filename for a
progress line, but the CI step deliberately writes outside the repository
(`$RUNNER_TEMP`) so that a drill artifact can never be mistaken for a committed
one. The display idiom and the output policy contradict each other, and the
display idiom wins by crashing after the work is complete.

The same idiom appears at 33 call sites. They are not all display: some enforce
that a key, an evidence file or a review artifact stays inside a trusted
directory, and there `relative_to` raising *is* the security check.

**Proposed fix.** Add `display_path(path, root)` returning a repository-relative
string when possible and an absolute string otherwise. Classify all 33 sites and
apply the fallback only to the display-only ones. Leave every boundary check
raising.

**Regression test required.** Output inside the repository, in `/tmp`, in a
Windows temporary directory, at a relative path, through a resolved symlink; and
a security-sensitive path still rejected.

---

## F2 — ShellCheck SC1091 fails the build on `/etc/os-release`

| | |
| --- | --- |
| Workflows | `qualification-evidence.yml`, `release-blocker-closure.yml`, `phase1.yml` |
| Jobs | `Qualification evidence suites`, `Blocker closure test suites`, `host-gate`, `phase7-gate` |
| Step | `python scripts/task.py validate` (all four) |
| Local reproduction | **Reproduced** under Fedora WSL 44, ShellCheck 0.11.0. Not reproducible on the Windows host, which has no `shellcheck` and takes the `SKIP` branch. |
| Affects evidence integrity | **No.** The script's output is unaffected; only the linter refuses it. |

Exact error:

```text
In scripts/reproducibility/collect-builder-record.sh line 63:
  "operatingSystem": "$(. /etc/os-release 2>/dev/null && echo "${ID}-${VERSION_ID}" || echo unknown) $(uname -r)",
                          ^-------------^ SC1091 (info): Not following:
                          /etc/os-release was not specified as input (see shellcheck -x).
```

**Root cause.** `scripts/reproducibility/collect-builder-record.sh` is new in the
candidate commit and sources `/etc/os-release` to read `ID` and `VERSION_ID`.
ShellCheck cannot follow a source of an absolute runtime path, emits SC1091, and
`scripts/task.py validate` runs `shellcheck` with no severity floor, so an
`info` finding is fatal. This is why four jobs across three workflows fail at the
same step; the host that produced the candidate commit has no ShellCheck
installed and printed `SKIP` instead.

Sourcing also leaks every variable in `/etc/os-release` into the script's scope,
which is why the shell that sources it happens to be a command substitution
subshell — a detail load-bearing for correctness that nothing asserts.

**Proposed fix.** Stop sourcing. Parse the two fields with `sed`, which removes
the SC1091 finding at its cause rather than suppressing the symptom, keeps the
`unknown` fallback when the file is absent, and confines the parsed values to two
named variables. No `SC1091` directive is added anywhere.

**Regression test required.** ShellCheck must pass over the script with no
suppression; the script must emit `unknown` for a missing `/etc/os-release` and
must not source it.

---

## F3 — Pull-request jobs run against a synthetic merge commit

| | |
| --- | --- |
| Workflows | all three |
| Job | every `pull_request`-triggered job |
| Step | `actions/checkout@v4` (implicit) |
| Local reproduction | **Not reproducible locally by construction** — a synthetic merge commit exists only in the CI event. Reproduced in tests with a fabricated merge ref. |
| Affects evidence integrity | **Yes, latently.** No committed record is currently bound to a merge ref, but nothing prevents it. |

No error message: this is a latent defect surfaced while diagnosing F4, not a
red step.

**Root cause.** `actions/checkout@v4` on a `pull_request` event checks out
`refs/pull/N/merge` — a commit GitHub creates by merging the PR head into the
base. `git rev-parse HEAD` in that job returns a SHA that exists in no branch and
will never be pushed. Four scripts call `git rev-parse HEAD` and stamp the result
into evidence as `sourceCommit`:

```text
scripts/reachability.py:112
scripts/release.py:142
scripts/build_evidence_record.py:239
scripts/write_qualification_reports.py:225
scripts/reproducibility/collect_builder_record.py:185,256
```

Each reimplements the same rule. Running any evidence generator in a PR job would
mint a record describing a commit nobody can check out, and the record would look
well-formed.

**Proposed fix.** One resolver, `resolve_commit_context()`, returning
`CHECKOUT_COMMIT`, `PR_HEAD_COMMIT`, `MERGE_TEST_COMMIT`, `CANDIDATE_COMMIT` and
`EVIDENCE_COMMIT` as distinct fields. Integration tests may run on the merge
ref; committed-evidence regeneration must use the declared `candidateCommit`;
independent builds must be given an exact 40-character commit as input.

**Regression test required.** Local branch checkout, detached exact commit, PR
synthetic merge, PR head, evidence commit after candidate, wrong candidate,
missing candidate, and evidence accidentally bound to a merge ref.

---

## F4 — Committed CVE findings do not regenerate

| | |
| --- | --- |
| Workflow | `.github/workflows/qualification-evidence.yml` |
| Job | `Per-CVE reachability framework` |
| Step | `Findings regenerate identically from committed evidence` |
| Local reproduction | **Reproduced.** `python scripts/reachability.py generate-findings` then diff against `HEAD` shows the same fields differing. |
| Affects evidence integrity | **Yes.** The check that proves the committed findings follow from the committed evidence is not currently proving it. |

Exact error:

```text
security/reachability/findings/CVE-2020-27815.json does not regenerate from
committed evidence
```

The step reports only the first filename. All 25 records differ. Classifying
every differing field, rather than widening the ignore list until the step goes
green:

| Field path | Committed | Regenerated | Classification |
| --- | --- | --- | --- |
| `generatedAt` | `2026-07-30T11:24:44.947976Z` | `2026-07-30T14:34:32.964210Z` | **Generation metadata** — wall-clock of the generator run. Cannot affect a conclusion. |
| `sourceCommit` | `80df25b09f6578276d18c8a82f15c47dd8959740` | `9dc7e33f66a270150dfc2c1c9950b1e974a3c2ae` | **Commit identity** — must be resolved through `candidateCommit`, not ignored. |
| `desktopActivationEvidence[0]` | `...over every shipped .desktop at 80df25b09f65: no match` | `...at 9dc7e33f66a2: no match` | **Commit identity** carried inside a semantic-evidence string. The measurement (`no match`) is identical; only the embedded short commit moved. |

No field is unstable ordering, and none is a bug in the analysis itself.

**Root cause.** `scripts/reachability.py:109 source_commit()` returns
`git rev-parse HEAD`. The 25 records were generated while `HEAD` was `80df25b`
and were then committed, which advanced `HEAD` to `9dc7e33`. The act of
committing the evidence invalidated it. This is the same self-invalidating
binding that `scripts/release.py:160 candidate_commit()` was written to fix for
release evidence; the reachability generator never adopted it.

Consequently the CI step is not currently testing what it claims. It would report
the same failure for an honest record and for a tampered one, and the message
distinguishes neither.

**Proposed fix.** Resolve the generator's commit through the declared
`candidateCommit` via the F3 resolver, so a record regenerates identically for as
long as it describes the same candidate. Keep `sourceCommit` in the comparison.
Emit a structured field-path diff on failure. Document the invariants in
`docs/CVE_REGENERATION_INVARIANTS.md`.

**Regression test required.** Only `generatedAt` may differ; a changed carrier
object, package, advisory, disposition or candidate commit each fail; reordered
sets and maps do not fail; a true semantic difference is never ignored.

---

## F5 — `repositoryValidation: FAIL` reports nothing usable

| | |
| --- | --- |
| Workflow | `.github/workflows/qualification-evidence.yml` |
| Job | `Gate state` |
| Step | `Source gate passes` |
| Local reproduction | **Reproduced** wherever F2 reproduces; the source gate shells out to the same validator. |
| Affects evidence integrity | **No,** but it conceals defects that do. |

Exact error:

```text
source gate: FAIL
  ok      baselineRecorded
  ok      licenceGatePassed
  ok      minimisationComplete
  ok      qualificationSuitesPass
  ok      sourceSuitesPass
  FAIL    repositoryValidation: every JSON document parses, every schema is well
          formed, every Python file compiles
exit code 2
```

**Root cause.** `repositoryValidation` collapses ten independent validators —
JSON parsing, schema validation, Python compilation, shell syntax, ShellCheck,
desktop entries, XML/SVG, licence headers, workflow YAML and committed-evidence
consistency — into one Boolean. The failing check here was ShellCheck on one
line of one file; the reported description names JSON, schemas and Python, none
of which failed. Anyone reading the gate output alone would look in the wrong
three places.

The exit code is correct (2, a fail-closed refusal). Only the diagnosis is
unusable.

**Proposed fix.** Report the ten validators separately with the exact failing
validator and file. Emit
`build/out/qualification/repository-validation.json`. Do not change the gate's
verdict or its exit code.

**Regression test required.** A single failing validator must be named
individually and must not mark the other nine as failed.

---

## F6 — `systemd-analyze verify` rejects units whose binaries are not installed

| | |
| --- | --- |
| Workflow | `.github/workflows/phase1.yml` |
| Job | `systemd-units` (container `fedora:44`) |
| Step | `Verify installed-form units and record offline security reports` |
| Local reproduction | **Reproduced** in a `fedora:44` container. |
| Affects evidence integrity | **No.** |
| Pre-existing | **Yes** — also failed at `3adb0253` (PR #1) and `79bb99dd` (PR #2), before this branch existed. Not a regression from the candidate commit. |

Exact error:

```text
bunny-installer-backend.service: Command /usr/libexec/bunny-installer-backend is
not executable: No such file or directory
bunny-live-session.service: Command /usr/libexec/bunny-live-session is not
executable: No such file or directory
bunny-policy-agent.service: Command /usr/libexec/bunny-policy-agent is not
executable: No such file or directory
bunny-first-run.service: Command /usr/bin/bunny-first-run is not executable:
No such file or directory
```

**Root cause.** `systemd-analyze verify` resolves each `ExecStart=` against the
filesystem it is run on. The units are correct; the four programs they name are
installed by the image build into `/usr/libexec` and `/usr/bin`, and a bare
`fedora:44` container has neither. The job asserts a property of an *installed
system* while running on an *uninstalled* one.

**Proposed fix.** Install the repository's own programs to the paths the units
declare before verifying, so the check tests the units against the layout the
image actually produces. Do not pass `--no-man` style suppressions or drop the
`ExecStart` check: the point of the job is that a unit naming a program that will
not exist must fail.

**Regression test required.** A unit naming a program the build does not install
must still fail verification.

---

## F7 — `desktop-file-validate` rejects `DesktopNames` in session entries

| | |
| --- | --- |
| Workflow | `.github/workflows/phase1.yml` |
| Job | `gnome-integration` (container `fedora:44`) |
| Step | `Validate GNOME 50 extension, schemas, and desktop entries in Fedora 44` |
| Local reproduction | **Reproduced** in a `fedora:44` container. |
| Affects evidence integrity | **No.** |
| Pre-existing | **Yes** — also failed at `3adb0253` and `79bb99dd`. Not a regression from the candidate commit. |

Exact error:

```text
/src/shell/session/bunny-safe.desktop: error: file contains key "DesktopNames" in
group "Desktop Entry", but keys extending the format should start with "X-"
/src/shell/session/bunny.desktop: error: file contains key "DesktopNames" in
group "Desktop Entry", but keys extending the format should start with "X-"
```

**Root cause.** `shell/session/*.desktop` are GNOME **session** files, not
application launchers. `DesktopNames` is a required key for a session entry and
is defined by the GNOME session specification. `desktop-file-validate` implements
only the freedesktop Desktop Entry Specification, where the key is unknown. The
job validates two different file kinds with one validator that understands one of
them.

**Proposed fix.** Validate session entries against the session rules — presence
of `DesktopNames`, `Name`, `Exec`, `Type=Application` — and run
`desktop-file-validate` over the application launchers only. Removing
`DesktopNames` would break the session; adding `X-` would break it silently.

**Regression test required.** A session entry missing `DesktopNames` must fail;
an application launcher carrying an unknown non-`X-` key must still fail.

---

## F8 — CI cannot distinguish a crash from a correct refusal

| | |
| --- | --- |
| Workflows | all three |
| Job | every job invoking a protected gate |
| Local reproduction | **Reproduced** by pointing a gate at a missing evidence file: it exits non-zero and the job reads that as a correct refusal. |
| Affects evidence integrity | **Yes, latently.** A protected gate is supposed to be verified as refusing; a crash currently satisfies that verification. |

No error message: this defect is only visible when something else breaks.

**Root cause.** Several assertions accept any non-zero status as proof that a
gate refused. `scripts/release.py` documents exit 2 as *evaluated and refused*
and exit 1 as *failed to evaluate*, but the workflows do not all hold that line —
and a Python traceback exits 1, as does a missing file, a syntax error and an
import failure. A job asserting "the stable gate still reports NO-GO" would go
green if `release.py` failed to parse.

**Proposed fix.** Assert the exact documented exit code at every call site, treat
0 as an unexpected approval and anything other than 0 or 2 as a crash, and report
the three cases distinctly.

**Regression test required.** A gate that crashes must not be accepted as a
correct refusal.

---

---

## Defects found by running the hosted builder

`.github/workflows/independent-builder.yml` had never been executed. Four defects
were found by running it, none of which was visible by reading it. They are
recorded here in the same form as the rest, because "the workflow is committed"
and "the workflow works" are different claims and only the second is evidence.

### F9 — The pinned base-image digest no longer exists

| | |
| --- | --- |
| Run | 30558573550, job `Hosted independent build` |
| Step | `Build the normalised OCI archive` |
| Local reproduction | **Not reproducible locally** — the local builder has the layers cached. That *is* the finding. |
| Affects evidence integrity | **Yes.** |
| Pre-existing | Yes — the digest was pinned in Phase 6. |

```text
Error: creating build container: unable to copy from source
docker://quay.io/fedora/fedora-bootc@sha256:fb71f099…: reading manifest
sha256:fb71f099… in quay.io/fedora/fedora-bootc: manifest unknown
```

**Root cause.** `quay.io/fedora/fedora-bootc:44` is rebuilt daily and old digests
are garbage collected. Confirmed against the registry with `skopeo`, not inferred
from the build failure: the pinned digest returns `manifest unknown`, and the
current `:44` tag resolves to `sha256:c466de53…`, built the same morning.

The local Fedora builder built against the dead digest on that same day, because
podman had the layers in its store. A build that appears to reproduce may only be
reachable from one machine's cache, and that is invisible from the machine that
has it.

**Fix applied.** None to the repository. The base is a workflow *input*: the
currently published digest was supplied for the next dispatch and the local
builder rebuilt against the same one, so both halves of the comparison share a
base. The digest check was not relaxed and the base was not unpinned.

**Regression test required.** None possible — this is an upstream retention
policy, not a repository defect. Recorded in `KNOWN_LIMITATIONS.md` with what
would remove it: mirroring the base under this project's control.

### F10 — `crun` refuses the OCI spec version Ubuntu's podman writes

| | |
| --- | --- |
| Run | 30558894088 |
| Step | `Build the normalised OCI archive`, after 32 minutes |
| Local reproduction | Not applicable — Fedora ships a matched podman/crun pair. |
| Affects evidence integrity | **No.** |

```text
error running container: from /usr/bin/crun creating container for
[/bin/sh -c /usr/bin/python3 …install-packages.py…]: unknown version specified
did not get container create message from subprocess: EOF
```

**Root cause.** Ubuntu 24.04's `podman` 4.9.3 and its `crun` disagree about the
OCI runtime specification version. `runc`, also packaged by Ubuntu, accepts it.

**Fix applied.** `runc` installed and selected in `/etc/containers/containers.conf`.
This changes which program starts the build container; it changes nothing about
what is built.

**Regression test required.** The runner's OCI runtime and its version are now
recorded in `runner-environment.txt`, so the difference from the local Fedora
builder is visible in the evidence rather than implicit.

### F11 — Podman fell back to the `vfs` storage driver

| | |
| --- | --- |
| Run | 30558894088 |
| Step | `Build the normalised OCI archive` |
| Affects evidence integrity | **No**, but it made the job unaffordable. |

No error. The symptom was in the timings: each `COPY` of a source directory took
2 minutes 24 seconds, and the build had spent 32 minutes copying directories
before it failed for an unrelated reason.

**Root cause.** With no configured storage driver podman selected `vfs`, which
copies the entire image for every layer instead of stacking them. The runner's
ext4 root supports `overlay`.

**Fix applied.** `driver = "overlay"` in `/etc/containers/storage.conf`, and the
driver in use is recorded in the runner environment.

### F12 — The storage driver cannot be changed under an initialised store

| | |
| --- | --- |
| Run | 30561595976 |
| Step | `Configure the container runtime and storage driver` |
| Affects evidence integrity | **No.** |

```text
Error: database graph driver "" does not match our graph driver "overlay":
database configuration mismatch
```

**Root cause.** The `ubuntu-24.04` runner image ships an already-initialised
container store whose recorded graph driver is empty. Podman refuses to change
drivers under an existing database.

**Fix applied.** The store is removed before the driver is configured. It holds
nothing this build needs — the base image is pulled by digest — and starting from
an empty store is what `BUNNY_CACHES_DISABLED=1` asks for anyway.

---

## Summary

| Defect | Jobs failed | Evidence integrity | Pre-existing |
| --- | --- | --- | --- |
| F1 output path | 1 | No | No |
| F2 ShellCheck | 4 | No | No |
| F3 merge commit | 0 (latent) | Yes | Yes |
| F4 CVE regeneration | 1 | Yes | No |
| F5 validation diagnostics | 1 | No | Yes |
| F6 systemd units | 1 | No | Yes |
| F7 session entries | 1 | No | Yes |
| F8 gate exit codes | 0 (latent) | Yes | Yes |
| F9 dead base digest | 1 | Yes | Yes |
| F10 crun spec version | 1 | No | Yes |
| F11 vfs storage driver | 0 (timing only) | No | Yes |
| F12 store driver change | 1 | No | Yes |

F2 accounts for four of the eight failing source jobs. F6 and F7 predate the
branch and are not regressions from the candidate commit; they are repaired here
because the objective is a green source pipeline, not a green diff.

Three defects — F3, F4 and F8 — affect whether evidence means what it claims.
None of them was visible as a red step for the reason that actually matters: F4
failed for a reason that hid the real one, and F3 and F8 do not fail at all yet.

F9 to F12 were found by *running* the hosted builder, which had been committed
and never executed. Each needed a real dispatch to surface, and F9 in particular
could not have been found any other way: it is invisible from the machine whose
cache still holds the base image. The gap between "the workflow is committed" and
"the workflow works" was four defects wide.
