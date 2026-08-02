# GNOME Screencast Unit Disposition (dsq-1)

## Identity

There is no unit named `1.2-org.gnome.Shell.Screencast@0.service` and
there never was. The unit is the **transient, D-Bus-activated, user-scope**
`dbus-:<connection>-org.gnome.Shell.Screencast@0.service`, created by the
session's dbus-broker from
`/usr/share/dbus-1/services/org.gnome.Shell.Screencast.service`
(`Exec=/usr/bin/gjs -m /usr/share/gnome-shell/org.gnome.Shell.Screencast`).
No systemd unit file exists for it. The `:1.2` / `:1.3` prefix in prior
evidence is the D-Bus connection ID, which varies per boot; the prior
collector stripped `dbus-:` and kept the connection ID, so a single unit
was counted as two distinct failures across passes.

## Stage 8 answers

- **System or user unit?** User — it runs inside the gnome-initial-setup
  session's user manager (uid 60578 on this image).
- **Who activates it?** Whatever requests `org.gnome.Shell.Screencast` on
  the session bus — gnome-shell, during session start on this image.
- **Does it require a logged-in GNOME session?** It requires a graphical
  session bus and a display. The gnome-initial-setup session (this image's
  greeter-role session) satisfies both; no desktop login is needed.
- **Does it require PipeWire / a portal / a graphical D-Bus session?**
  PipeWire for actual recording; it queries
  `org.freedesktop.portal.Settings` at startup (absence is non-fatal —
  logged, then it proceeded to the display check); session D-Bus, yes.
- **Is failure before login expected or erroneous?** Neither arises:
  measured across all 60 dsq-1 boots, the activation **succeeds in every
  boot in which it occurs**. There is no steady-state failure to excuse.
- **Does it affect the GDM greeter?** No. It is not in gdm.service's or
  the session's required path; in the prior failing boot the session
  continued without it.
- **Coredump or restart loop?** None, in any scenario, ever.

## What actually failed in the prior passes

`HARNESS_OR_COLLECTOR_DEFECT` (prior scenario), confidence **CONFIRMED**:

1. **Collector defect** — the name mangling above, plus the prior
   collectors' inability to see user-scope units at all (they read only
   the `UNIT` journal field; user managers log to `USER_UNIT`).
2. **Harness defect** — the prior harness initiated shutdown ~10 s after
   boot. The screencast activation happens at ~11 s; it collided with the
   dying session and failed with `Failed to open display` while
   gnome-shell's Wayland display was being torn down.

In dsq-1 — canonical naming, phase classification, and a ≥ 75 s
observation window — the unit shows **zero failures in 60 boots** (see
`DISPLAY_STACK_BOOT_MATRIX_REPORT.md`). The regression protection required
by Stage 8 is in `tests/display_stack/`: connection-ID canonicalisation
identity, the no-global-ignore rule, and the context checks that would
reject an `EXPECTED_WITHOUT_USER_SESSION` claim if a real user session
existed. Nothing ignores this unit by name; a future genuine failure will
be counted and will block until disposed.
