<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CVE binary analysis report

Date: 2026-07-30
Scope: the 24 unique Critical and High fixable findings in the consumer-facing
beta profile.
Base image: `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`

## Result

**The framework is complete and nothing has been analysed, because no binary and
no debuginfo package is present on the machine that runs these gates.**

```text
$ python scripts/reachability.py analyse-symbols
symbol analysis: 0 of 4 target(s) collected
  missing tooling: eu-readelf, eu-unstrip, file, rpm
  NOT COLLECTED  podman-5.8.4-1.fc44.x86_64
      /usr/sbin/podman does not exist on this host; the image must be mounted or booted
  NOT COLLECTED  skopeo-1.22.2-2.fc44.x86_64
  NOT COLLECTED  bootc-1.16.4-1.fc44.x86_64
  NOT COLLECTED  kernel-core-7.1.5-200.fc44.x86_64
  symbol-absence verdict: supports 'nothing'
      Absence of a symbol from a stripped binary is not evidence of absent code.
      Debuginfo must be acquired before this question can be answered.
BLOCKED
```

That is the state of the analysis, not a failure of the tooling. No conclusion may
be drawn from data that was not collected, and none is.

## What *was* measured, and it is new

The scan records each finding's carrier as an **ostree object digest**, not an
installed path, because `fedora-bootc` ships an object store and `dnf remove`
cannot remove an object from a lower layer. Reading those digests out of
`evidence/vulnerability/beta-grype.json` produced a fact nobody had extracted:

**all 24 Critical and High findings are carried by exactly four distinct objects.**

| Carrier object | Advisories | Modules carried |
|---|---|---|
| `/sysroot/ostree/repo/objects/8f/bfb47329076d06ea8a11d1beb743cd9e5758c4079135869d0d5d01f51694b4.file` | **15** | `golang.org/x/crypto`, `github.com/opencontainers/selinux`, `github.com/sigstore/fulcio`, `github.com/docker/docker`, `golang.org/x/net` |
| `/sysroot/ostree/repo/objects/8c/c9b0248b19238b5f375ee6f7c986efc7ef8cdd360140254e41c478cd91b933.file` | **7** | `github.com/moby/buildkit`, `github.com/containers/podman/v5`, `google.golang.org/grpc`, `go.opentelemetry.io/otel` |
| `/sysroot/ostree/repo/objects/75/5cc7cfe2e3b547556eb117093d626800f1dcb3751e3b31952cec86177bdcab.file` | **1** | `golang.org/x/text` |
| `/sysroot/ostree/repo/objects/ea/cf5a37b7b9193f1063a40c3def6c25fc348d9f404d569b91aeba6007bceef7.file` | **1** | `linux-kernel` |

Twenty-four independent questions became **four binaries to identify and two Go
binaries to analyse**. That is a materially better brief for a reviewer.

### The one advisory whose analysis differs

`…755cc7cfe2…` is the object the previous phase identified as **`toolbox`**, which
package minimisation removed. `rpm -q toolbox` reports not installed and
`/usr/bin/toolbox` is absent from the minimised image; the object survives in a
base layer because the object store is baked into a lower layer.

If that attribution is confirmed, `GO-2026-5970` (`golang.org/x/text` v0.21.0) has
**no installed executable to invoke** and its invocation analysis differs from the
other 23.

It remains `Unknown`. The attribution is not confirmed, and question 7 —
whether the vulnerable code path is compiled in and active — is unanswered either
way. It is the second question in `reviews/security/REQUEST.md`.

## Carrier attribution is not resolved

Three Go binaries are installed, measured in
`evidence/reachability/beta-minimised-binaries.txt`:

```text
PRESENT  podman       /usr/sbin/podman     podman-5.8.4-1.fc44.x86_64
PRESENT  skopeo       /usr/sbin/skopeo
PRESENT  bootc        /usr/sbin/bootc      bootc-1.16.4-1.fc44.x86_64
ABSENT   toolbox                           package toolbox is not installed
```

Which object corresponds to which binary is recorded as `unknown` with the three
candidates named, because resolving it needs the image:

```sh
# inside a mounted or booted beta deployment
find /sysroot/ostree/repo/objects -samefile /usr/sbin/podman
ostree ls -R <commit> /usr/sbin
```

The module sets make an inference available — `github.com/containers/podman/v5`
appears only in `…8cc9b024…` — and an inference is not a measurement. It is not
recorded as one.

## The 29-field analysis record

One record per advisory in `security/reachability/findings/<ADVISORY>.json`,
validated by `security/reachability/schemas/cve-analysis.schema.json`.

**Measured, from committed evidence:**

| Field | Value | Source |
|---|---|---|
| `carrierObjects` | the ostree object above | `beta-grype.json` |
| `systemdUnits` | `podman.service` present not enabled; `podman.socket` present, absent from `sockets.target.wants`; `bootc-fetch-apply-updates.timer` present not enabled | `beta-facts.txt` |
| `socketUnits` | `podman.socket` — `ListenStream=%t/podman/podman.sock`, unix | `beta-facts.txt` |
| `commandInvocationPaths` | `/usr/sbin/{podman,skopeo,bootc}` mode 0755 root:root, no setuid | `beta-permissions.txt` |
| `bunnyInvocationPaths` | none — typed fixed broker backends, no generic exec path | source inspection of `services/` |
| `pluginInvocationPaths` | none — plugins reach the system only through the broker | same |
| `desktopActivation` | `no` | `grep '^Exec=.*(podman|skopeo|bootc|toolbox|docker)'` over every shipped `.desktop`: no match |
| `defaultEnablement` | `no` | no enabled unit, no preset |
| `userInvocability` | `yes` | mode 0755, no setuid |
| `sandboxReachability` | `yes` | `selinux-policy-targeted` enforcing |

**Deliberately `unknown`, and why:**

| Field | Why |
|---|---|
| `vulnerableFunctionOrSubsystem` | naming a function without the advisory's own description of it is a guess dressed as evidence |
| `elfBuildId` | requires the binary |
| `strippedState` | requires the binary |
| `exportedSymbols` | requires the binary |
| `dynamicDependencies` | requires the binary |
| `sourceRpmReference`, `debuginfoReference`, `debugsourceReference` | requires acquisition from Fedora infrastructure |
| `sourcePackage`, `binaryPackage` | requires carrier attribution — except the kernel, where the version string *is* the NEVRA |
| `dbusActivation` | not enumerated; `busctl --list` inside a booted deployment would settle it |
| `packageScripts` | requires the RPM |

All twelve vulnerable-path mapping fields are `unknown` for all 24 advisories.

## An absent symbol is not absent code

The rule that does the most work. `classify_symbol_evidence` returns
`sufficientForNotPresent: False` for **every** combination of stripped state,
language and symbol presence the test suite enumerates — twelve cases.

| Observation | What it supports |
|---|---|
| symbol absent, binary stripped | **nothing** — that is what a stripped binary looks like whether or not the code is present |
| symbol absent, unstripped **Go** binary | **nothing** — the compiler inlines across package boundaries and the linker rewrites call graphs |
| symbol absent, unstripped C binary | weak absence only — a file-static or inlined function is absent from that table too |
| symbol **present** | presence, and nothing about reachability — a linked function no entry point calls is present and unreachable |

`release/cve.py` additionally refuses a `Not present` conclusion whose only cited
evidence is a symbol observation: a record must also cite debuginfo, debugsource, a
build configuration, or a source-to-binary mapping.

## Version discipline

An analysis of the wrong build establishes nothing about the shipped one, so:

- `parse_analysis` refuses a record whose `sourcePackageVersion` does not
  correspond to its `installedVersion`. `v0.46.0` and `0.46.0` correspond;
  `v0.46.0` and `0.52.0` do not.
- `release/acquisition.py` refuses a debuginfo package at a different release:
  `podman-debuginfo-5.8.4-2.fc44.x86_64` against `podman-5.8.4-1.fc44.x86_64` is
  rejected with *"An analysis of a different build establishes nothing about the
  shipped binary"*.

## Acquisition

`security/reachability/sources/ACQUISITION.md` and `acquisition-plan.json` carry
the exact commands for four targets. **A plan, not an execution:** the environments
that run these gates have no route to Fedora infrastructure, and a plan can be
reviewed before it is run.

```text
$ python scripts/release.py validate-cve-acquisition
BLOCKED: security/reachability/sources/acquisition-manifest.json does not exist.
No source, binary or debuginfo package has been acquired, so no symbol analysis
can be performed.
```

Constraints, enforced:

- **Fedora infrastructure only.** Seven trusted hosts. A debuginfo RPM from an
  arbitrary mirror is an arbitrary binary, and the analysis resting on it is worth
  what that host is worth.
- **Every download's SHA-256 recorded**, plus the `repomd.xml` digest the package
  was resolved against.
- **Exact NEVRA matching**, not merely the same upstream version.
- **Nothing committed.** `storedOutsideRepository` must be `true`; a single podman
  debuginfo package is larger than the entire source tree. A test asserts no `.rpm`
  is tracked in git.

## What would resolve this

| Step | Resolves | Needs |
|---|---|---|
| Mount the beta deployment, run `analyse-cve-symbols --sysroot` | carrier attribution for all four objects; build IDs; stripped state; dynamic dependencies | the Fedora builder |
| Execute the acquisition plan | source, binary, debuginfo and debugsource for four targets | network access to Fedora |
| Per-CVE function identification and mapping | question 7 | **an independent security reviewer** |

The first two remove work from the reviewer's scope. Neither answers question 7,
and only the third can.

## Evidence

- `security/reachability/findings/` — 24 records plus an index
- `security/reachability/packages/` — 24 bundles × 9 files
- `security/reachability/sources/` — the acquisition plan
- `security/reachability/reports/symbol-analysis.json` — what could not be collected
- `security/reachability/schemas/` — three schemas
- `tests/reachability/` — 32 tests, including the missing-debuginfo,
  version-mismatch, absent-symbol and Critical-without-reviewer cases
