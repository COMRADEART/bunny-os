# GDM Failure Root Cause (dsq-1)

## Finding

The `gdm.service` failures reported intermittently by the installed-system
and TPM passes are **shutdown-teardown exit races, not boot failures**.
Confidence: **STRONGLY_SUPPORTED**.

Across the 60-boot dsq-1 matrix:

- **0 of 60** boots showed any gdm failure before shutdown was requested;
- **29 of 60** boots recorded gdm entering `failed` during poweroff
  teardown (cell A 11/20, B 6/10, C 5/10, D 3/10, E 4/10);
- in every one of the 60 boots, GDM reached active, seat0 existed, the
  launch-environment session opened, and the display stack stayed stable
  through at least a 60 s journal-verified observation window — 636 s in
  the longest case;
- no GDM coredump, no restart loop, no fatal display-server error exists
  in any record.

## Mechanism

At poweroff, systemd stops `gdm.service` while `accounts-daemon.service`
and the D-Bus broker are being stopped concurrently — `gdm.service`
declares no ordering relationship to either, so the stop order between
them is unconstrained. When a D-Bus peer vanishes first, gdm logs

```text
Gdm: Failed to list cached users: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown
```

and its main process exits 1 *inside its own stop job* (0.05–0.1 s after
`Stopping gdm.service...` in every affected record), which systemd records
as `Failed with result 'exit-code'`. When gdm wins the race it stops
cleanly — that coin flip is the entire "intermittency". `Restart=always`
never engages because the unit is in a stop job.

The prior passes could not see this because their harnesses initiated
shutdown ~10 s after boot and their collectors read final unit state with
no phase information: a teardown race at second 10 is indistinguishable
from a boot failure in that design. The prior first-boot journal shows the
identical signature, plus `GdmDisplay: Session never registered, failing`
— the gnome-initial-setup session was still starting when teardown killed
it (`gdm-launch-environment` pam session closed 0.6 s after opening).

## Why this is not inferred from timing alone

The claim is supported by (1) the unit files: no `After=`/`Before=`
between gdm and accounts-daemon (see `unit-facts.json`); (2) the invariant
journal signature in all 29 affected boots — stop request, D-Bus error,
exit 1, all within ~0.1 s; (3) the phase invariant: 29/29 failures lie
after the logind power-key event, 0 before, across five environment
variants including reduced resources and no network; and (4) the absence
of any such failure while the stack was in operation for 75+ s windows.
It is graded STRONGLY_SUPPORTED rather than CONFIRMED because the
correction that would remove it (stop-ordering gdm against
accounts-daemon, a Path C image change) has not been applied and
re-measured in this pass.

## Disposition and consequence

`SHUTDOWN_TEARDOWN_EXIT_RACE`, verified per record by the gate (a single
boot-phase failure, or a core dump, voids it). GDM reliability itself
**passes** Stage 15: every supported boot produced a usable greeter-role
session and no unexplained failure remains. The cosmetic teardown exit is
recorded as a Path C correction candidate:

```text
order gdm.service against accounts-daemon.service for stop,
or make gdm tolerate D-Bus peer disappearance in its shutdown path
```
