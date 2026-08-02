# Display-Stack Repeated-Boot Matrix Report (dsq-1)

Generated from `qualification/display-stack/evidence/display-stack-qualification.json`; the numbers below are the gate's own input, not a summary of it.

## Cells

| Cell | Scenario | Planned | Attempted | Collected | GDM-ready boots | Complete |
| --- | --- | --- | --- | --- | --- | --- |
| A | ordinary no-TPM cold boot | 20 | 20 | 20 | 20/20 | yes |
| B | CRB TPM, restored NVRAM | 10 | 10 | 10 | 10/10 | yes |
| C | first TPM fallback boot | 10 | 10 | 10 | 10/10 | yes |
| D | reduced resources (2 vCPU / 4 GiB) | 10 | 20 | 10 | 10/10 | yes |
| E | network unavailable | 10 | 20 | 10 | 10/10 | yes |

## Boots failing a GDM readiness assertion

None. Every collected boot passed every readiness assertion, observation window included.

## Per-unit occurrence counts

### `at-spi-dbus-bus.service`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 17 | 0 | 3 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 9 | 0 | 1 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |

### `bunny-first-boot.service`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 0 | 10 | 0 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 0 | 10 | 0 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 0 | 10 | 0 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 0 | 10 | 0 | 0 | 0 | 0 | 10 |

### `chronyd.service`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 19 | 1 | 0 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |

### `gdm.service`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 9 | 0 | 11 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 4 | 0 | 6 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 7 | 0 | 3 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 6 | 0 | 4 | 0 | 0 | 0 | 10 |

### `gnome-session-manager@gnome-initial-setup.service`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 0 | 0 | 20 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 10 |

### `session-c1.scope`

| Cell | attempted | reached graphical | activated | succeeded | failed (boot phase) | failed during shutdown | failed+recovered | skipped | n/a | collection failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 20 | 20 | 20 | 18 | 0 | 2 | 0 | 0 | 0 | 0 |
| B | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| C | 10 | 10 | 10 | 7 | 0 | 3 | 0 | 0 | 0 | 0 |
| D | 20 | 10 | 10 | 9 | 0 | 1 | 0 | 0 | 0 | 10 |
| E | 20 | 10 | 10 | 8 | 0 | 2 | 0 | 0 | 0 | 10 |

## Units with no failure in any cell

Watched throughout, zero failures in any phase: `avahi-daemon.service`, `avahi-daemon.socket`, `dbus-:*-org.gnome.Shell.Screencast@0.service`

## Disposition verdicts

- `at-spi-dbus-bus.service`: CLOSED (SHUTDOWN_TEARDOWN_EXIT_RACE)
- `avahi-daemon.service`: CLOSED (SHUTDOWN_TEARDOWN_CRASH)
- `bunny-first-boot.service`: BLOCKING (GRAPHICAL_SESSION_DEFECT)
- `chronyd.service`: CLOSED (FIRST_BOOT_NSS_WINDOW_RACE)
- `dbus-:*-org.gnome.Shell.Screencast@0.service`: CLOSED (HARNESS_OR_COLLECTOR_DEFECT in prior scenario; no dsq-1 failure)
- `gdm.service`: CLOSED (SHUTDOWN_TEARDOWN_EXIT_RACE)
- `gnome-session-manager@gnome-initial-setup.service`: CLOSED (SHUTDOWN_TEARDOWN_CRASH)
- `session-c1.scope`: CLOSED (SHUTDOWN_TEARDOWN_EXIT_RACE)

## Gate result

- GDM reliability: **PASS**
- Display-stack reliability: **BLOCKED**
