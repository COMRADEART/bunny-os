# The ACPI power key, and the keybinding filter behind it

Phase 4, Part 2. Eleven boots of the Phase 3 binding machine
(`build/out/phase3/machine.qcow2`, user `alex`, LUKS
`bunny-disk-passphrase`), each recorded here as `result.json`,
`interaction.json` and the boot's own journal.

## What was reported

Phase 3 closed with: *the ACPI power key does nothing in a Bunny session.*
logind logs the press and defers to the `handle-power-key` block held by
gsd-media-keys, whose handler — the same handler whose VM branch logs and
powers off in a stock GNOME session **on the same machine** — never runs.
Every Bunny-session boot therefore ended with an `unclean-shutdown` finding.

## What it actually is

Not a power-key defect, and not confined to the power key.

The Bunny desktop is a GNOME Shell extension. It was built during
gnome-shell's own startup, and one of the first things it does is dismiss the
overview GNOME opens at login. In GNOME 50.4 (`gnome-shell-50.4-1.fc44`,
read out of the shipped `libshell-18.so`), `overviewControls.js`'s
`runStartupAnimation()` awaits `this.layout_manager.ensureAllocation()` — a
promise that settles only when the controls actor is first allocated. Hiding
the overview before that allocation happens leaves the promise unsettled for
ever. So:

```
desktop built during startup
  → overview hidden before its first allocation
    → ensureAllocation() never settles
      → layout.js never reaches _startupAnimationComplete()
        → 'startup-complete' never fires
          → main.js never flips Main.actionMode from NONE to NORMAL
            → windowManager.js's _filterKeybinding drops EVERY keybinding
```

`_filterKeybinding` returns `true` (filter it) whenever
`Main.actionMode === Shell.ActionMode.NONE`. Nothing logs, because a filtered
binding is not an error. The power key, every media key, and the Bunny
desktop's own four shortcuts were all inert in every Bunny session ever
booted.

Two visible symptoms had already been worked around without the cause being
found: the desktop's own code hides the shell's leftover cover pane ("the
shell left its cover pane over the desktop") and hides GNOME's panel "after
the startup deadline" — both are consequences of a startup that never
completes.

## The measurement

The discriminator is `GNOME Shell started`, the message main.js logs from
inside its own `startup-complete` handler. Its absence *is* the stalled
startup.

| Run | Extension at login | `GNOME Shell started` | Press delivered | Findings |
| --- | --- | --- | --- | --- |
| p4-power-1 | enabled | absent | no | unclean-shutdown |
| p4-power-2 | enabled | absent | no | unclean-shutdown |
| p4-power-3 | enabled | absent | n/a — handler killed by the debug restart; logind's own `HandlePowerKey` powered the machine off | none |
| p4-power-4 | enabled, **disabled mid-session** | **present** | **yes** | none |
| p4-power-5 | disabled (dconf latch) | **present** | **yes** | none |
| p4-power-6 | disabled, **re-enabled mid-session** | **present** | **yes** | none |
| p4-power-7 | enabled | absent | no | unclean-shutdown |
| p4-power-8 | enabled + two host volume presses | absent | **no accelerator of any kind was ever received** | unclean-shutdown |
| p4-power-9 | enabled (fix injected into `/usr` — see below) | absent | no | unclean-shutdown |
| p4-power-10 | enabled (diagnostic injected into `/usr`) | absent | no | unclean-shutdown |
| **p4-power-11** | **enabled, fixed extension shadowed in `$HOME`** | **present** | **yes** | **none** |

p4-power-8 is the one that proves the scope: two volume-up presses injected
from the host through QMP produced no `Received accel id` line at all. It is
not the power key that is filtered; it is every key.

p4-power-4 and p4-power-6 are the same fact from the other side: disabling
the extension mid-session lets the stalled startup finish seconds later, and
the very same press then delivers — `Received accel id …` → `Launching action
for key type '43'` → gsd's VM branch → `The system will power off now!`.

## Two harness traps found on the way

1. **A write into the deployment's `/usr` is silently ignored.** This machine
   boots a composefs image sealed with fs-verity (`.ostree.cfs` inside the
   deployment). p4-power-9 and p4-power-10 ran the *original* extension while
   the injected copy sat in the deployment directory, checksum-verified and
   never read; the diagnostic build's `console.log` produced no journal lines
   at all, which is what exposed it. `/etc` and `/var` are ordinary writable
   directories — which is why `phase3-inject.sh` has always worked. p4-power-11
   installs the fixed extension into
   `/var/home/alex/.local/share/gnome-shell/extensions/`, from a one-shot unit
   inside the guest so ownership and SELinux labels come from the guest's own
   tools.
2. **The gsd user units refuse a manual restart** (`Operation refused, unit
   … may be requested by dependency only`), and killing the process instead
   leaves it dead: the unit has no restart policy, its `handle-power-key`
   inhibitor goes with it, and logind's own `HandlePowerKey=poweroff` then
   powers the machine off. That produced a *clean* shutdown for the wrong
   reason in p4-power-3 — a false PASS that would have closed this
   investigation with the defect intact.

## The fix

Two commits, both in the extension:

- `f17fb19c` — `enable()` defers the desktop's construction to
  `startup-complete` when the shell is still starting, the upstream pattern
  for extensions that restructure the stage. `disable()` cancels a pending
  deferred build.
- `0d9866a4` — `_dismissOverviewOnce()` refuses to run while
  `Main.layoutManager._startingUp`, and deliberately does not set its
  once-flag in that path, because the desktop already connects a
  `startup-complete` retry and a flag set early would make that retry a no-op.

Either alone is sufficient; both are kept, because the second names the exact
API contract that was violated and would catch a future caller that hides the
overview from somewhere else.

Regression tests: `tests/shell/test_desktop_shell.py::StartupDeferralTests`
(five assertions, each naming the way the fix could be faked and rejecting
it).

## What p4-power-11 shows

`findings: []` — the first Bunny-session boot in this project's history to
end with no findings at all. `GNOME Shell started` present; the desktop up;
the overview dismissed *after* startup completed; and the press answered:

```
systemd-logind: Power key pressed short.
gsd-media-keys: Received accel id 172 (device-id: 0, timestamp: 189943, mode: 0x1)
gsd-media-keys: Launching action for key type '43' (on device node /dev/input/event0)
gsd-media-keys: Virtual machines only honor the 'nothing' power-button-action, and will shutdown otherwise
systemd-logind: The system will power off now!
```

This run validates the fix on an installed machine with the fixed source
shadowing the image copy. The binding proof is the same journey on a fresh
install of the release-candidate image, recorded in the Phase 4 report.
