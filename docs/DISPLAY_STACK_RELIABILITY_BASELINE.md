# Display-Stack Reliability Baseline — scenario dsq-1

This document is the diagnostic authority for the display-stack boot
reliability pass. Every dsq-1 record binds to
`qualification/display-stack/evidence-context.json`; a record naming any
other artifact, firmware, emulator or collector version is stale and can
fill no matrix cell.

## What this pass measures

The prior installed-system and TPM passes reported `gdm.service`, an Avahi
unit and a "GNOME screencast service" failing *inconsistently* across
identical boots of one image. A single successful boot cannot clear an
intermittent failure and a single failed boot cannot prove one systematic,
so this pass measures actual per-unit frequency across a repeated-boot
matrix and disposes each finding from evidence.

## Exact units under investigation (Stage 1 resolution)

Resolved from the qualified image itself
(`qualification/display-stack/evidence/unit-facts.json`), not from prior
reports:

| Reported name | Canonical identity | Scope | Activation |
| --- | --- | --- | --- |
| `gdm.service` | `gdm.service` (alias `display-manager.service` via `/etc/systemd/system/display-manager.service`) | system | enabled, pulled by `graphical.target`; `Restart=always`; `Conflicts=getty@tty1.service`; `OnFailure=plymouth-quit.service` (absent on the image) |
| "screencast service" / `1.2-org.gnome.Shell.Screencast@0.service` | transient `dbus-:<conn>-org.gnome.Shell.Screencast@0.service` — canonicalised as `dbus-:*-org.gnome.Shell.Screencast@0.service` | user (the gnome-initial-setup session's manager) | D-Bus activation of `org.gnome.Shell.Screencast` (`/usr/share/dbus-1/services/org.gnome.Shell.Screencast.service`, `Exec=gjs -m …`); no systemd user unit file exists |
| Avahi unit | `avahi-daemon.service` + `avahi-daemon.socket` (alias `dbus-org.freedesktop.Avahi.service`) | system | preset-enabled in `multi-user.target.wants`; `Type=dbus`, socket- and D-Bus-activatable |

The `1.2-` / `1.3-` prefixes in prior evidence were a collector artifact:
the D-Bus connection ID `:1.2` varies per boot, so the prior collector
counted one transient unit as two different failures. The connection ID is
never part of a unit's identity in dsq-1.

Context the image imposes on every boot: no login-capable user account
exists and `gnome-initial-setup-done` is absent, so GDM's launch
environment is the **gnome-initial-setup session** (uid allocated at boot,
observed 60578), which plays the greeter's role in every assertion below.
The image bakes `gdm` (uid 42) into `/etc/passwd` but **not** `chrony` or
`avahi` (created at boot by systemd-sysusers), and ships no
`/etc/nsswitch.conf` (materialised at first boot by
`authselect-apply-changes.service`) — both facts are load-bearing for the
dispositions.

## Matrix definition (Stage 5)

All cells boot the frozen artifact `bunny-os-b9c317d35b85.qcow2`
(sha256 `0b7dd90d…fab217`) via a per-run copy-on-write overlay and a
per-run OVMF variable store. The source disk is never modified.

| Cell | TPM | OVMF vars | Resources | Network | Expected resets | Runs |
| --- | --- | --- | --- | --- | --- | --- |
| A | absent | seeded (normal boot entry exists) | 4 vCPU / 8 GiB | user-mode | 0 | ≥ 20 |
| B | CRB, state reused from seed | seeded | 4 vCPU / 8 GiB | user-mode | 0 | ≥ 10 |
| C | CRB, fresh state | fresh | 4 vCPU / 8 GiB | user-mode | exactly 1 (shim fbx64 restoration) | ≥ 10 |
| D | absent | seeded | 2 vCPU / 4 GiB | user-mode | 0 | ≥ 10 |
| E | absent | seeded | 4 vCPU / 8 GiB | `-nic none` | 0 | ≥ 10 |

Seed provenance: `--cell seed-A` / `--cell seed-B` boots create the reused
variable stores (and cell B's TPM state) from fresh inputs; measured on
this artifact, shim's fallback chainloads the created boot entry directly
without a TPM and takes its one designed restoration reset only with one
(the tpmq-1 finding). Seed records live beside the matrix records.

Sequences are contiguous from 001 per cell; a run directory is never
overwritten and never deleted. Superseded or invalid runs stay recorded
with explicit status.

## Per-boot evidence (Stages 3–4)

Live observation: serial stages, QMP guest-reset events, screendumps at
each stage, a ≥ 75 s post-graphical observation window, then an ACPI
power-button shutdown (the method actually used is recorded; a forced quit
is a recorded degradation).

The installed journal, extracted offline from the read-only overlay after
the VM exits, is the authoritative service record — the guest ships no
credentials, so live `systemctl` queries are impossible by design (and no
product credential is injected). Unit metadata that `systemctl show` would
give live is read statically from the image (`unit-facts.json`). The
collector distinguishes, per unit: activated-and-succeeded /
currently-failed / **failed-during-shutdown** /
failed-transiently-and-recovered / skipped-by-condition /
inactive-no-activation-observed / absent-from-journal, with user-scope
units keyed by uid and their session existence recorded. A collection
failure yields `collection.status = collection-failed` and null analysis
fields — never an empty failed-unit list.

Failures are phase-classified against the recorded shutdown initiation
(logind power-key event or poweroff/shutdown target), so a teardown exit
race can neither masquerade as a boot failure nor hide one.

## GDM readiness (Stage 7)

`graphical.target` is never proof of a usable login screen. Per boot, from
the installed journal: gdm.service reached active; `display-manager.service`
resolves to gdm.service on the image; seat0 created; the launch-environment
session opened (pam `gdm-launch-environment`); no boot-phase gdm failure;
no restart loop; no GDM/gnome-shell coredump; no fatal display-server
error before shutdown; no `GdmDisplay: Session never registered` before
shutdown; the observation window completed; guest resets equal the cell's
expectation. Screendumps support but never substitute for these.

## Disposition vocabulary and context verification

A unit that failed anywhere closes only through
`evidence/unit-dispositions.json` with confidence CONFIRMED or
STRONGLY_SUPPORTED, and the gate re-verifies the claimed context against
every record — there is deliberately no way to accept a unit by name:

- `EXPECTED_WITHOUT_USER_SESSION` — rejected if any covered boot had a real
  user session.
- `SHUTDOWN_TEARDOWN_EXIT_RACE` — rejected if the unit failed even once
  before shutdown initiation, if a record lacks a shutdown timestamp, or
  if the unit dumped core (a crash can never close as an exit race).
- `SHUTDOWN_TEARDOWN_CRASH` — same phase requirements, and any coredump of
  the disposition's named processes must itself lie after shutdown
  initiation.
- `FIRST_BOOT_NSS_WINDOW_RACE` — rejected if any failure lies outside that
  record's measured `authselect-apply-changes` window.
- `BOOT_CRITICAL_DEFECT` / `GRAPHICAL_SESSION_DEFECT` /
  `HARNESS_OR_COLLECTOR_DEFECT` — always blocking.

## Collector lineage

- `dsq-failed-units-1` — **invalidated** (retained under
  `evidence/invalidated/dsq-failed-units-1/`): read only the `UNIT` journal
  field, so every user-manager unit event — including the screencast unit
  this pass exists to measure — was invisible. Found during the first
  partial cell-A sweep, before any import.
- `dsq-failed-units-2` — current: reads `USER_UNIT` for user managers,
  phase-classifies failures, records the authselect window and shutdown
  initiation.
- `dsq-journal-1` — offline journal extraction; binary journals are
  retained out-of-tree (default `/root/dsq-traces/<run-id>/`) with their
  manifest digest recorded in the run's record.

Bulky raw evidence (screendumps) is moved out of the committable tree by
`retain_bulky_evidence.py`, digest-first: a file is moved only after its
bytes match the record's manifest, each run gains a
`retention-manifest.json`, and the importer accepts a missing evidence
file only when that manifest carries the record's own digest. Retention
destinations preserve the run's position in the evidence tree — an
invalidated run shares its ID with its rerun, and a flat layout let one
tree overwrite the other's retained bytes before this was fixed (the 38
affected v2 screenshots are recorded as lost in their retention
manifests; their sha256 attestations stand).

## Adversarial evidence tests (Stage 13)

`tests/display_stack/` builds valid synthetic evidence trees, applies one
fraud at a time (copied boots, sequence gaps, foreign boot IDs or disk
digests, serial-only records, relabelled cells, doctored files, stale
authority, screenshot-only readiness, boot-phase failures dressed as
teardown races, out-of-window NSS claims, blanket ignore-by-name), and
asserts the gate names each one. Mutation tests disable each critical
check and prove the corresponding fraud then passes — each check is
load-bearing.
