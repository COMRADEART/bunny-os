<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Package manifest

The toolchain required to measure V4 and Programs E through H1, in
`packages/fedora-packages.txt` as `group:package` so that absence is
attributable to an area rather than to a long flat list.

101 packages across 19 groups: build, lang, data, container, virt, tpm, storage,
wayland, graphics, audio, portal, a11y, ime, toolkit, compositor, apps, perf,
trace, supplychain.

## Installation

    sudo bash scripts/install-packages.sh \
      --report /var/lib/bunny-qualification/environments/FQH-<id>/packages.json

`--dry-run` resolves availability without installing.

## Classification

Every package is recorded with one of:

| State | Meaning |
|---|---|
| `INSTALLED` | installed by this run |
| `ALREADY_PRESENT` | present before it ran |
| `AVAILABLE` | resolvable, queued (dry-run only) |
| `UNAVAILABLE` | not resolvable from configured repositories |

**An unavailable package is recorded, never skipped.** A silently dropped
dependency is how a matrix later reports `NOT_RUN` for a reason nobody can trace
back. If anything lands in `UNAVAILABLE`, resolve it before qualifying: a renamed
package and a genuinely missing one look identical afterwards.

## Resolution measured on Fedora 44

Run as a dry-run against real `dnf` repositories:

    total: 101   ALREADY_PRESENT: 55   AVAILABLE: 46   UNAVAILABLE: 0

Every package in the manifest resolves on Fedora 44. This was measured in the
WSL2 Fedora 44 development environment, which shares Fedora repositories with the
target host but is **not** a qualification host and produced no other evidence.

## `python3-jsonschema` is a runtime dependency, not a convenience

`host-readiness-gate.py` validates the environment report against
`host-environment.schema.json` before evaluating it, and **fails closed** when
`jsonschema` is absent — a gate that cannot check its input has not checked it.

Without this package a host can install everything else, collect a clean
environment, satisfy every hardware requirement, and still be refused:

```text
BLOCKED: <path> is not a valid environment report.
         jsonschema is unavailable, so the environment report cannot be validated.
```

That is the gate behaving correctly and the manifest being wrong. The package is
listed here so an actual FQH installation always has it.

This is separate from the test suite, which *skips* its schema tests when
`jsonschema` is missing rather than failing — the repository convention, and what
lets the `Gate state` workflow run without the optional dependency. The manifest
guarantees the dependency on a qualification host; it does not require every
environment to carry it.

## Versions

Exact versions are recorded in the environment report under `tooling`, and the
full RPM inventory belongs with the host evidence:

    rpm -qa --qf '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n' | sort

This is **host evidence, never release evidence**. The toolchain that measured an
artifact is not a property of the artifact.
