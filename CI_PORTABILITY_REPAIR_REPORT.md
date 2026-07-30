# CI portability repair report

What was broken in GitHub Actions, what was repaired, and what the repairs did
not change.

| | |
| --- | --- |
| Starting commit | `9dc7e33f66a270150dfc2c1c9950b1e974a3c2ae` |
| Branch | `feature/qualification-evidence-closure` |
| Failures found | 8 defects across 8 failing jobs in 3 workflows |
| Baseline record | [docs/CI_PORTABILITY_BASELINE.md](docs/CI_PORTABILITY_BASELINE.md) |
| Regression tests added | 125, in `tests/portability/` |

No protected decision moved. The gate state this pass began with is the gate
state it ends with, and three of the repairs make that state harder to falsify
than it was.

## What was failing

Eight jobs, five of them the same defect seen through five job definitions.

```text
Qualification evidence closure    FAIL  Two-person development signing drill   (F1)
                                  FAIL  Qualification evidence suites          (F2)
                                  FAIL  Per-CVE reachability framework         (F4)
                                  FAIL  Gate state                             (F2 via F5)
Release blocker closure           FAIL  Blocker closure test suites            (F2)
Bunny OS Phase 1 and 2            FAIL  host-gate                              (F2)
                                  FAIL  phase7-gate                            (F2)
                                  FAIL  systemd-units                          (F6)
                                  FAIL  gnome-integration                      (F7)
```

`systemd-units` and `gnome-integration` had also failed at `3adb0253` and
`79bb99dd`, before this branch existed. They are repaired here because the
objective is a green source pipeline, not a green diff.

Two further defects, F3 and F8, were not failing. They were found while
diagnosing F4 and are the two that most affect whether evidence means what it
says.

## What was repaired

### F1 — Report output outside the repository crashed the tool

`Path.relative_to` raises when the path is not under the root. The two-person
drill used it to shorten a filename for a progress line, while CI deliberately
writes the drill record to `$RUNNER_TEMP` so it can never be mistaken for a
committed artifact. All nine checks passed, the record was written, and then the
progress message crashed the job.

The two uses of `relative_to` are now separated. `release/paths.py` provides
`display_path`, which never raises. Containment checks keep calling
`relative_to` and keep raising, because there the exception *is* the check.

All 33 call sites were classified before any was touched:

| Classification | Count | Change |
| --- | --- | --- |
| Display-only | 9 | now `display_path` |
| Security boundary | 12 | unchanged — must keep raising |
| Repository invariant | 12 | unchanged — cannot escape by construction |

`build/scripts/sign-stable-rc.py` is the inverted case: `relative_to`
*succeeding* is the failure, because it means a private signing key is inside
the repository. A blanket fallback there would have accepted a committed key. A
test now asserts it still refuses.

One latent defect was fixed alongside: `reachability.py` built evidence strings
from `Path.relative_to`, which yields backslashes on Windows. The generated
record would have differed by platform. Paths now come from git in POSIX form.

### F2 — ShellCheck SC1091 failed four jobs across three workflows

`scripts/reproducibility/collect-builder-record.sh` sourced `/etc/os-release`.
ShellCheck cannot follow an absolute runtime path, emits SC1091, and
`scripts/task.py validate` runs `shellcheck` with no severity floor, so an
`info` finding was fatal. The host that produced the script has no ShellCheck
installed and printed `SKIP`.

The script now reads the two fields with `sed` rather than sourcing them. This
removes the finding at its cause, keeps the `unknown` fallback when the file is
absent, and confines the values to two named variables instead of defining every
key in the file as a shell variable.

No `SC1091` directive was added anywhere, no `.shellcheckrc` was created, and no
severity floor was introduced — three tests assert each of those. All 25 shell
scripts pass ShellCheck 0.11.0 with no suppression.

Verified: the builder record's `operatingSystem` field is byte-identical before
and after (`fedora-44 6.18.33.2-microsoft-standard-WSL2`), and reports
`unknown <kernel>` when `/etc/os-release` is removed.

### F3 — Pull-request jobs run against a synthetic merge commit

Not a failing step. `actions/checkout@v4` on a `pull_request` event checks out
`refs/pull/N/merge`, a commit GitHub synthesises that exists in no branch and
will never be pushed. Six call sites each independently resolved a commit as
`git rev-parse HEAD` and stamped it into evidence. Running any evidence
generator in a PR job would have minted a well-formed record describing a commit
nobody can check out.

`release/commits.py` now resolves all five concepts in one place:

```text
CHECKOUT_COMMIT     git rev-parse HEAD — the synthetic merge, in a PR job
PR_HEAD_COMMIT      the tip of the source branch
MERGE_TEST_COMMIT   the synthetic merge, named as such
CANDIDATE_COMMIT    the immutable commit artifacts and evidence describe
EVIDENCE_COMMIT     a later commit importing reports about the candidate
```

A synthetic merge is detected by parent count rather than by ref name, so a
workflow that checks out the PR head explicitly is not mislabelled.
`commit_for_purpose` encodes the rule: integration tests may use the merge ref,
committed-evidence regeneration must use the declared candidate, and an
independent build requires an exact 40-character commit as input.

### F4 — Committed CVE findings could never regenerate

The step reported one filename. All 25 records differed, and it had stripped
`generatedAt` from both sides before comparing, so it could not distinguish a
drifted timestamp from an edited conclusion.

Every differing field was classified before anything was excluded:

| Field | Classification | Disposition |
| --- | --- | --- |
| `generatedAt` | Generation metadata | Excluded, documented |
| `sourceCommit` | Commit identity | **Fixed at the cause** |
| `desktopActivationEvidence[0]` | Commit identity in a semantic string | **Fixed at the cause** |

The root cause was self-invalidating evidence. `reachability.py` stamped
`git rev-parse HEAD`; the records were generated at `80df25b`, then committed,
which moved `HEAD` to `9dc7e33`. **The act of recording the evidence invalidated
it.** No regeneration could ever have matched.

The generator now resolves its commit through the declared `candidateCommit`
(`79bb99dd` — the commit whose built image was scanned into
`evidence/vulnerability/beta-grype.json`). `sourceCommit` stays in the
comparison, so wrong-commit evidence still fails.

A second defect was found in the same field: the desktop grep ran over the
*working directory* while the record claimed to describe the *candidate commit*.
It now reads the entries out of the commit with `git ls-tree` and `git show`, so
the record describes the tree it names. A shallow clone fails closed with a
message naming the cause rather than silently measuring the wrong tree; the job
checks out with `fetch-depth: 0`.

`release/regeneration.py` classifies every difference into one of six classes and
emits a structured diff. The step no longer reports `does not regenerate`; it
reports field path, committed value, regenerated value and classification.
Invariants are documented in
[docs/CVE_REGENERATION_INVARIANTS.md](docs/CVE_REGENERATION_INVARIANTS.md).

Result: 25 records compared, nothing excluded before comparison, 25 differences,
all `Generation metadata`.

### F5 — `repositoryValidation: FAIL` named the wrong three things

One Boolean stood for twelve independent checks. The description named JSON,
schemas and Python; the check that failed was ShellCheck.

`release/validation.py` reports thirteen validators separately, each with its own
count and the exact files it rejected, and writes
`build/out/qualification/repository-validation.json`. A new command,
`release.py validate-repository`, exposes the same evaluation without running the
source gate's three test suites.

A `SKIP` is reported as a skip with its reason, never as a pass, so "it passed
locally" and "it never ran locally" are distinguishable — which is precisely how
F2 reached CI.

The gate's verdict and exit code are unchanged.

```text
  ok    JSON parsing                     278 documents parsed
  ok    Schema validation                35 schemas
  ok    Python compilation               310 files compiled in memory
  ok    Shell syntax                     25 scripts parsed by bash -n
  ok    ShellCheck                       25 scripts, no suppression
  ok    Desktop entries                  9 entries (2 session, 7 launcher)
  ok    XML and SVG                      8 XML/SVG assets parsed
  ok    Licence headers                  162 declarations, all permitted
  ok    Workflow YAML                    4 workflows parsed
  ok    Committed evidence consistency   26 records agree on candidate 79bb99ddb39d
  ok    GNOME extension syntax           extension.js parsed by node --check
  skip  systemd units                    requires BUNNY_VERIFY_SYSTEMD=1
  ok    systemd unit programs            19 units, 1 recorded gap
  ok    Shell layout                     7 required shell directories
```

### F6 — `systemd-analyze verify` ran against an uninstalled system

Four units named programs absent from a bare `fedora:44` container. Three
(`bunny-installer-backend`, `bunny-live-session`, `bunny-first-run`) are
installed by `build/scripts/install-root.py`; the job simply did not install
them. `build/scripts/ci-verify-units.sh` now installs exactly what the image
build installs, to the paths it installs them to.

The fourth was real and was invisible inside the noise:
**`systemd/bunny-policy-agent.service` names `/usr/libexec/bunny-policy-agent`,
which nothing installs.** `install-root.py` copies `systemd/` wholesale, so the
unit ships; `enterprise/policy.py` is a library, not an executable. Writing the
agent would be a new product feature and is out of scope for this pass, so the
gap is recorded in `operations/data/unit-program-gaps.json` with its impact —
the unit is guarded by `ConditionPathExists=/etc/bunny-os/enrolment.json`, no
device is enrolled, and the enterprise pilot gate is BLOCKED.

A new validator, `systemd unit programs`, fails any unit whose program is
neither shipped nor recorded, so this cannot recur silently. Verified in a real
`fedora:44` container: 18 units verified, 1 skipped by record, exit 0.

### F7 — One validator for two different file kinds

`desktop-file-validate` rejected `DesktopNames` in `shell/session/*.desktop`.
The key is required by the GNOME session specification and unknown to the
freedesktop Desktop Entry Specification. Removing it would break session
selection; renaming it `X-DesktopNames` would break it silently.

`build/scripts/ci-validate-desktop.sh` now sends the seven application launchers
to `desktop-file-validate` and checks the two session entries against the session
rules. The `Desktop entries` validator makes the same distinction and fails a
session entry missing `DesktopNames` *and* a launcher carrying one. Verified in a
real `fedora:44` container: exit 0.

### F8 — A crash was indistinguishable from a correct refusal

Several steps asserted only "the gate did not return 0". A traceback exits 1. So
does a missing evidence file, an import error and a syntax error. A job written
that way goes green when `release.py` stops parsing, and reports that the stable
gate correctly refuses — the most misleading thing this pipeline could say.

`build/scripts/assert-gate.sh` asserts the exact documented status and reports
three outcomes distinctly:

```text
0   evaluated, approved
2   evaluated, refused — GO withheld, NO-GO, or BLOCKED
*   failed to evaluate — NOT a refusal, and never reported as one
```

Every protected-gate call site in all four workflows now goes through it — 17
call sites converted, and three tests assert that no `set +e` status capture,
no `if python scripts/release.py`, and no `[ "$status" -ne 0 ]` remains.

One case the exit code alone cannot distinguish: **CPython exits 2 for
"can't open file", which is also the refusal status.** The helper therefore
checks a named script exists before running it, and a test asserts every script
referenced by a workflow assertion is present.

## What was not changed

The gate state is preserved exactly:

```text
Source gate:               PASS        (exit 0)
Qualification candidate:   BLOCKED     (exit 2, 2 of 14 prerequisites)
Stable release:            NO-GO       (exit 2)
OEM pilot:                 BLOCKED     (exit 2)
Enterprise pilot:          BLOCKED     (exit 2)
Sync pilot:                BLOCKED     (exit 2)
```

Three repairs make protected refusals harder to falsify than before:

* F3 means evidence cannot silently bind to a commit that will never exist.
* F4 means a semantic change to a finding can no longer hide behind a timestamp.
* F8 means a crashed gate can no longer be reported as a holding gate.

The candidate gate's build-mode check is *additive*: it prints after the
prerequisite table rather than replacing it, so the 2-of-14 count stays visible.
An earlier draft returned early and hid it.

## Archive-only mode

`BUNNY_ARCHIVE_ONLY=1` now records itself. `write-build-provenance.py` writes
`archiveOnly: true` and `diskImages: []`, and refuses to write a record its
artifacts contradict — an archive-only build that produced a disk image, or a
full build that produced none.

`release/buildmode.py` refuses such an artifact at both protected gates, naming
what the build did not do rather than reporting a bare rejection. A provenance
record that does not declare the field is treated as *unknown*, not *full*:
failing open there would let any older record pass as a complete build.

A crash was found and fixed while testing this: `write-build-provenance.py`
called `subprocess.run(["image-builder", ...])` unguarded, so it raised
`FileNotFoundError` on any host without the tool — including an archive-only
builder, where the tool is deliberately absent. A missing tool is now recorded as
`absent`.

## Regression tests

125 tests in `tests/portability/`:

| File | Tests | Covers |
| --- | --- | --- |
| `test_display_path.py` | 13 | F1: inside repo, `/tmp`, Windows temp, relative, symlink, security-sensitive still refused, record content unaffected by output location |
| `test_shellcheck_portability.py` | 11 | F2: no suppression, no severity floor, nothing sources `/etc/os-release`, absent-file fallback, quoted values, JSON stays parseable |
| `test_commit_context.py` | 21 | F3: local branch, detached exact, PR merge, PR head, evidence after candidate, wrong candidate, missing candidate, evidence bound to merge ref |
| `test_cve_regeneration.py` | 27 | F4: allowed metadata difference, changed carrier/package/advisory/disposition/commit, reorder tolerance, nested change, structured diff output |
| `test_repository_validation.py` | 18 | F5: all ten required validators reported, one failure does not implicate the others, session vs launcher rules, machine-readable output |
| `test_gate_exit_codes.py` | 14 | F8: refusal accepted, approval rejected, crash/traceback/missing-file/odd-status rejected, no workflow accepts any non-zero |
| `test_archive_only.py` | 21 | archive-only refused by both gates, provenance writer refuses contradictory records, undeclared mode treated as unknown |

## Local verification

Run on Fedora Linux 44 (WSL2) and Windows 11:

```text
python scripts/task.py validate                          PASS  (13 validators)
python scripts/task.py test                              PASS  (892 + 60 tests)
python scripts/task.py test-installer                    PASS  (60 tests)
python scripts/task.py test-phase5                       PASS  (105 tests)
python scripts/task.py phase7-audit                      PASS
python scripts/phase7.py source-gate                     PASS
python scripts/release.py validate-repository            exit 0
python scripts/release.py qualification-evidence-baseline exit 0
python scripts/release.py two-person-development-signing-drill  9/9
python scripts/reachability.py verify-findings           exit 0, only generatedAt
python scripts/release.py gate --kind source             exit 0
python scripts/release.py gate --kind qualification-candidate   exit 2
python scripts/release.py gate --kind stable-release     exit 2
python scripts/release.py gate --kind oem-pilot          exit 2
python scripts/release.py gate --kind enterprise-pilot   exit 2
python scripts/release.py gate --kind sync-pilot         exit 2

shellcheck (0.11.0, Fedora 44)                           25 scripts, 0 findings
podman run fedora:44 ci-verify-units.sh                  exit 0, 18 units
podman run fedora:44 ci-validate-desktop.sh              exit 0
```

ShellCheck and the container jobs cannot run on the Windows development host.
They were run under Fedora Linux 44 on WSL2 from an ext4 clone: a `/mnt/c`
checkout is CRLF and ShellCheck reports SC1017 on every line of every file, which
is an artifact of the mount and not of the repository.
