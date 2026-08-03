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

## dsq-2 — the corrected archive, with a login (2026-08-02)

The dsq-1 matrix below measured the b9c317d archive and never logged in. It
remains evidence about that archive. dsq-2 reruns the same five cells against
the corrected artifact (`bunny-os-93d1f6fb4f23.qcow2`,
`1290afe9eeb54b1d…`, Commit Q `12b5423b9f1b`) and performs a first login on
every boot.

```
                      A      B      C      D      E     total
collected            20     10     10     10     10     60/60
first-login PASS     20     10     10     10     10     60/60
second-login PASS    10      -      -      5      5     20/20
graphical.target     20     10     10     10     10     60/60
seat0 created        20     10     10     10     10     60/60
completion marker    20     10     10     10     10     60/60

226/NAMESPACE         0      0      0      0      0        0
chronyd 217/USER      0      0      0      0      0        0
chronyd in window     0      0      0      0      0        0
failed system units                                     none
home problems         0      0      0      0      0        0
```

Per-unit dispositions, read from `USER_UNIT` in each run's user journal:

```
bunny-config-dir.service     activated-and-succeeded   60/60
bunny-first-boot.service     activated-and-succeeded   60/60
                             not re-run on all 20 second logins
```

Directory state, read offline from each powered-down overlay:

```
.config/bunny-os        directory  0700  uid 4242  gid 4242  config_home_t
.config/systemd/user    directory  0700  uid 4242  gid 4242  systemd_unit_file_t
first-boot-complete.json           0600  uid 4242  374 bytes
```

Guest resets against each cell's expectation:

```
A  expected 0   0 on 20 first boots, 0 on 10 second boots
B  expected 0   0 on 10
C  expected 1   1 on all 10
D  expected 0   0 on 15
E  expected 0   0 on 15
```

chronyd ordering, across the 80 analysed boots that carry both timestamps:

```
chronyd start minus authselect window end   min +0.009s  median +0.029s  max +0.254s
authselect window width                     min  0.070s  median  0.224s  max  0.773s
inversions                                  0
```

Compare dsq-1 on the same five cells: `bunny-first-boot.service` activated on
60 boots and failed on 60; chronyd failed on 1. Both are zero here.
