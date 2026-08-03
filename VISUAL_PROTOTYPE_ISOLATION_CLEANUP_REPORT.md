# Visual Prototype Isolation Cleanup Report

Three visual prototype prototypes carried an explicit `DO NOT MERGE INTO MAIN`
policy and were nevertheless merged into `main`. This branch reverts those three
merges and restores branch isolation. It changes no product qualification
content, and it removes no evidence.

This report records what was reverted, what was deliberately left alone, and the
exact exit code of every protected gate, measured on this host.

## Authority

Reverted merge commits, in reverse chronological order:

| Order | Merge | PR | Prototype branch | Second parent |
|---|---|---|---|---|
| 1 | `da87b231d665f3c52b0384e5b7c55b5ba46cc3be` | #16 | `visual/bunny-wayland-shell-v3` | `f22212fe66ffa0c2b0b237c512a7eeb60ef25806` |
| 2 | `a62a7c8bb78792b9172a971acd0b3b4786245868` | #15 | `visual/bunny-desktop-v2-dual-mode` | `3ac806271057c2777c0133ad300a85164ab06c40` |
| 3 | `1a8d4e375ae1644c58c5965255c1df37a5c3c1d5` | #13 | `visual/bunny-desktop-v1` | `63f3c95241240be5af78e292d8b166a196d9c1fb` |

Each was reverted with `git revert -m 1`, mainline first parent. All three
applied with **no conflicts**, so no conflict resolution judgement was exercised.

The revert commits are preserved individually and must not be squashed.

## Preservation

The prototype branches are untouched and all three heads still resolve to the
commits recorded as current authority:

| Branch | Head | Resolves |
|---|---|---|
| `visual/bunny-desktop-v1` | `63f3c95241240be5af78e292d8b166a196d9c1fb` | yes |
| `visual/bunny-desktop-v2-dual-mode` | `3ac806271057c2777c0133ad300a85164ab06c40` | yes |
| `visual/bunny-wayland-shell-v3` | `f22212fe66ffa0c2b0b237c512a7eeb60ef25806` | yes |

All historical visual work remains reachable from those three branches. Nothing
was deleted from history; the reverts add commits, they do not rewrite any.

## What was removed from `main`

112 paths changed against `3ca74d937ccada6043b0f10fbe3c7baebe35584f`, the last
`main` state before the V2 and V3 merges. Every changed path is
prototype-exclusive except `.gitignore` and `Makefile`, which are reviewed below.

Prototype implementation trees, now empty in `main`:

| Path | Tracked files in `main` |
|---|---|
| `visual/` | 0 |
| `visual-v2/` | 0 |
| `visual-v3/` | 0 |
| `compositor/` | 0 |
| `shell-ui/` | 0 |
| `portals/` | 0 |
| `sessions/` | 0 |
| `shell/bunny-shell-extension/` | 0 |
| `apps/common/bunny_visual/` | 0 |
| `tests/visual/` | 0 |

Also removed: the five `apps/bunny-*` VisualV1 prototype applications, the
prototype root reports `VISUAL_PHASE_V1_REPORT.md`, `VISUAL_PHASE_V2_REPORT.md`
and `BUNNY_WAYLAND_SHELL_V3_REPORT.md`, and the prototype architecture documents
under `docs/`.

### Experimental session entries

`sessions/` contained only `bunny-visual-preview*` entries, and the directory did
not exist at all in the pre-V1 authority `54907c30255c79f834fca2b71760b17ad78fed96`.
`main` now advertises no experimental visual session.

### Portal definitions

`portals/bunny-desktop-portal`, `portals/bunny-screencast-portal` and
`portals/bunny-screenshot-portal` were introduced by the prototype merges. They
are absent from both pre-visual authorities, so their removal restores the
pre-prototype state rather than deleting product capability.

### `.gitignore` and `Makefile`

These are the only two non-prototype-prefixed paths touched, and both changes are
strictly the removal of prototype entries:

- `.gitignore` — removes the `build/visual/` ignore rule. The `build/visual-v2/`
  and `build/visual-v3/` rules were themselves added by the V2 and V3 merges and
  are removed with them.
- `Makefile` — removes the nine `visual-*` targets and their `.PHONY` entries.
  Every product target is preserved unchanged.

No release file, qualification file, evidence record, TPM record, BrlAPI record
or first-login record was modified by any of the three reverts. Measured: the
reverts changed **zero** files under `qualification/`, `release/`, `evidence/`,
`security/`, `selinux/`, `installer/`, `schemas/`, `operations/`, `services/`,
`systemd/`, `hardware/`, `reviews/`, `oem/`, `enterprise/`, `sync/` and
`scripts/`.

### Tests

Removed test suites, all introduced by the prototype merges and all measuring
zero files in the pre-visual authorities: `tests/visual`, `tests/visual_v2`,
`tests/shell_v2`, `tests/shell_ui_v3`, `tests/security_v3`,
`tests/accessibility_v2`, and `tests/accessibility/test_visual_v1_accessibility.py`.

No product test file was removed. The product suite `tests/accessibility` is
preserved, including `test_brlapi_key.py`. All 48 other product test directories
are preserved.

The suite count falls from 1876 to 1691 collected tests. The entire difference is
prototype tests.

## Working-tree isolation

The prototype merges had also left untracked prototype artefacts inside the
repository, including a **nested git worktree** for
`visual/bunny-desktop-v2-dual-mode` checked out at `build/visual/v2-worktree`.

`release/validation.py` walks `under="build"` recursively, so the protected
`validate` gate descended into that nested checkout and validated another
branch's content as if it were `main`. This is the same class of isolation
failure as the merges themselves.

These artefacts were **relocated, not deleted**, to
`../bunny-os-prototype-artifacts/` (3.8 GB):

| Artefact | Disposition |
|---|---|
| `build/visual/v2-worktree` | worktree relocated outside the repository, `git worktree repair` applied, still on `visual/bunny-desktop-v2-dual-mode` at `3ac8062`, clean, 0 uncommitted entries |
| `build/visual/`, `build/visual-v2/`, `build/visual-v3/` | prototype build output, relocated |
| `compositor/bunny-shell/target/release/bunny-shell` | compiled V3 binary, relocated |
| `visual-v3/reports/` | raw V3 run logs and diagnostics, relocated and retained |

The V2 worktree was verified clean at exactly the preserved head before it was
moved, so all of its content remains reachable from the prototype branch. No
evidence was destroyed.

## Protected gate results

Measured on this host after the reverts. Exit codes are recorded exactly as
returned.

Host: Windows 11 Pro 10.0.26200, Python 3.14.6, git 2.55.0.windows.3.

| Gate | Exit code | Result |
|---|---|---|
| `python scripts/task.py validate` | **0** | PASS |
| `python scripts/task.py test` | **1** | 1691 tests, 0 failures, 1 error, 19 skipped |
| `python scripts/task.py test-installer` | **0** | PASS, 60 tests |
| `python scripts/task.py test-phase5` | **0** | PASS, 105 tests |
| `python scripts/phase7.py source-gate` | **0** | PASS, pilot recommendation NO-GO recorded |

### The one remaining error is an environment limitation, not a defect

`tests.display_stack.test_evidence_gate.MutationTests.test_duplicate_boot_check_is_load_bearing`
fails to execute:

```
OSError: [WinError 1314] A required privilege is not held by the client
  tests/display_stack/test_evidence_gate.py:414  link.symlink_to(run)
```

This host cannot create symbolic links at all; a minimal `Path.symlink_to` probe
outside the repository fails identically. The cause is the absence of
`SeCreateSymbolicLinkPrivilege` (Windows Developer Mode or elevation), which
cannot be granted from inside this session.

The test is a **mutation test** asserting that the duplicate-boot guard is
load-bearing. It is exactly the class of high-risk guard that the evidence rules
require to be mutation-tested, so it must not be weakened, skipped or rewritten
to accommodate the host.

Its state on this host is **`NOT_RUN`**. It is not recorded as `PASS`, and the
`test` gate is reported with its true exit code of `1`. Re-running this gate on a
host with symlink privilege is required before the `test` gate can be claimed as
passing.

### Comparison with the pre-revert baseline

The same five gates were measured on `da87b23` before any revert:

| Gate | Before | After |
|---|---|---|
| `validate` | 1 | **0** |
| `test` | 1 (4 failures, 1 error) | 1 (**0 failures**, 1 error) |
| `test-installer` | 0 | 0 |
| `test-phase5` | 0 | 0 |
| `phase7.py source-gate` | 0 | 0 |

The four pre-existing failures were all caused by prototype artefacts inside the
working tree, not by tracked content: two were the `JSON parsing` validator and
its two portability assertions reading a zero-byte file inside the nested V2
worktree, and two were the licence gate finding 307 missing and 38 non-matching
SPDX headers inside that same worktree plus the generated `build/visual-v3/stage`
tree. Restoring isolation cleared all four.

## Status after this change

- `main` contains no experimental visual session.
- `main` contains no active prototype implementation.
- GNOME behaviour is unchanged. `shell/session/bunny.desktop`,
  `shell/session/bunny-safe.desktop` and every build profile are untouched by the
  reverts.
- The three visual branches are preserved and all heads resolve.
- Qualification evidence is unchanged and remains valid.
- Release gate results are unchanged.

This change is repository-state correction only. It qualifies nothing, releases
nothing, and does not alter the standing verdicts:

- Stable release: **NO-GO**
- Pilots: **BLOCKED**
