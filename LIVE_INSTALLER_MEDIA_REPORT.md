<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Live installer media report

Date: 2026-08-01
Status: **NOT PRODUCED / NOT_RUN — no live-installer media exists at this target; the GUI live installer flow is untested**

## Result

```text
Live-installer media          NOT PRODUCED in this pass
Existing build path           build/scripts/build-live-image.sh
                              (image-builder bootc-generic-iso)
Precondition                  requires a local beta payload image;
                              unexercised at target 619065e (Commit C)
Live-installer scenarios      NOT_RUN — no live-installer scenario ran
```

No live-installer ISO was built, booted or tested against the qualified
archive. The build path exists in the repository and remains exactly that: a
path, not evidence.

## Method

There is no method to describe, because nothing ran. This section exists so
that its absence cannot be mistaken for an omission: no
`build-live-image.sh` invocation, no boot, no installation from live media
occurred at this target.

## Requirements coverage — overlap only, not substitution

The live-installer media requirements are: detect the target disk, present
destructive warnings, ship no default password, ship no hidden account, log
no secrets, and emit a machine-readable install record. Some of these are met
by the HOST-SIDE bootc mechanism records from the installation matrix
(`INSTALLABLE_IMAGE_REPORT.md`) — but only where the two mechanisms overlap.
The host-side records say nothing about a GUI session, its warning dialogs,
its account handling or its logging. The GUI live installer flow itself is
UNTESTED, and overlap with the host-side mechanism does not soften that.

## What this establishes, and what it does not

**Established.** Nothing about live-installer media. The only true statements
are the ones above: the build path exists, it was not exercised, and the
host-side installation records cover shared mechanism behaviour only.

**Not established.** Everything specific to the live installer: booting the
medium, disk detection in its UI, destructive-action warnings as presented to
a user, the absence of default or hidden credentials in the live session,
secret handling in its logs, and the install record it would produce. None of
this can be inferred from host-side evidence.

## Where the evidence lives

```text
(none)                                    no live-installer evidence exists
build/scripts/build-live-image.sh         the unexercised build path
qualification/installed-system/evidence/installs/
                                          host-side mechanism records —
                                          overlap only, cited above with
                                          their limits
```

## Gate position

```text
Live-installer media         NOT_RUN — this report changes nothing
Installation matrix          rows move only through
                             qualification/installed-system/scripts/
                             import_matrix_results.py; live-installer rows
                             stay NOT_RUN
Qualification candidate      still BLOCKED
Stable release               NO-GO, unchanged
```

This report exists to record the gap precisely, not to move any line.
