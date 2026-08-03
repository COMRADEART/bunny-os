<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Package manifest

The toolchain required to measure V4 and Programs E through H1, in
`packages/fedora-packages.txt` as `group:package` so that absence is
attributable to an area rather than to a long flat list.

100 packages across 19 groups: build, lang, data, container, virt, tpm, storage,
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

    total: 100   ALREADY_PRESENT: 54   AVAILABLE: 46   UNAVAILABLE: 0

Every package in the manifest resolves on Fedora 44. This was measured in the
WSL2 Fedora 44 development environment, which shares Fedora repositories with the
target host but is **not** a qualification host and produced no other evidence.

## Versions

Exact versions are recorded in the environment report under `tooling`, and the
full RPM inventory belongs with the host evidence:

    rpm -qa --qf '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n' | sort

This is **host evidence, never release evidence**. The toolchain that measured an
artifact is not a property of the artifact.
