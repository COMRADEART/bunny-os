# Display-Stack Reliability Report (dsq-1)

## Verdict

```text
GDM reliability:            PASS
Display-stack reliability:  BLOCKED
Stop condition:             Outcome B — diagnosed, separate correction required
```

Every one of the 60 supported matrix boots reached `graphical.target`,
produced a usable greeter-role session (gnome-initial-setup on this
image), created seat0, survived a journal-verified ≥ 60 s observation
window, and recorded no GDM crash, coredump, restart loop or boot-phase
failure. The blocker is not GDM: it is a deterministic product defect in
`bunny-first-boot.service` that no prior pass could see, plus a
`chronyd` first-boot race — both requiring Path C image changes that this
pass deliberately does not make.

The full occurrence tables are in `DISPLAY_STACK_BOOT_MATRIX_REPORT.md`
(generated from the gate's own verdict file); the diagnostic authority is
`docs/DISPLAY_STACK_RELIABILITY_BASELINE.md`.

## What the "intermittent display-stack failures" actually were

Five distinct mechanisms, none of them an intermittent boot failure of the
display stack:

| Finding | Mechanism | Phase | Rate (dsq-1) | Confidence |
| --- | --- | --- | --- | --- |
| `gdm.service` failed | exit 1 racing its own stop against accounts-daemon/D-Bus teardown | shutdown only | 29/60 | STRONGLY_SUPPORTED |
| "screencast unit" failed | prior collector mangled the transient unit name and counted a per-boot D-Bus connection ID as unit identity; prior harness shut down ~10 s after boot, colliding with the activation | prior scenario | 0/60 | CONFIRMED |
| `avahi-daemon.service` failed | upstream avahi 0.8 SIGABRT in its own shutdown path when SIGTERM lands ~1 s after startup | prior scenario, shutdown | 0/60 | STRONGLY_SUPPORTED |
| `chronyd.service` failed | `Unknown user 'chrony'` when its spawn lands inside the `authselect-apply-changes` nsswitch window | boot | 1/60 | STRONGLY_SUPPORTED |
| `bunny-first-boot.service` failed | `226/NAMESPACE`: `ReadWritePaths=%h/.config/bunny-os` under `ProtectHome=read-only`, directory never pre-created | boot | 60/60 | CONFIRMED |

Also disposed, all strictly shutdown-phase:
`gnome-session-manager@gnome-initial-setup.service` (60/60 — ignores
SIGTERM at poweroff, systemd aborts it after the 45 s stop timeout, which
also delays every shutdown), `at-spi-dbus-bus.service` (4/60),
`session-c1.scope` (8/60). Root-cause detail: `GDM_FAILURE_ROOT_CAUSE.md`,
`SCREENCAST_UNIT_DISPOSITION.md`, `AVAHI_FAILURE_DISPOSITION.md`,
`qualification/display-stack/evidence/unit-dispositions.json`.

## Why the prior passes saw chaos

1. **Their collectors could not see user units** (they read only the
   `UNIT` journal field; user managers log to `USER_UNIT`) and mangled the
   one transient user unit they did surface. The same defect existed in
   this pass's first collector and was caught by its own first sweep —
   those records are retained under `evidence/invalidated/`.
2. **Their harnesses shut the VM down ~10 s after boot**, converting three
   independent teardown behaviors (gdm exit race, avahi shutdown crash,
   screencast activation collision) into what looked like intermittent
   boot failures.
3. **No phase information was recorded**, so a unit failed at
   poweroff and a unit failed at boot were the same fact.

## The chronyd race, demonstrated

Control: in 60 supported boots, chronyd failed once (`217/USER`,
`Failed to determine credentials for user 'chrony': Unknown user`), and
the failure lies inside that boot's measured authselect apply window —
the image creates the chrony user at boot (sysusers) and materialises
`/etc/nsswitch.conf` at first boot (authselect), with no ordering between
chronyd and either.

Diagnostic arm (declared `diagnostic`, per-run overlay drop-in
`After=authselect-apply-changes.service`, fills no cell): **20/20
succeeded**, and in every run chronyd's `Starting` verifiably followed
the authselect window end — changed synchronization behavior, failure
removed. Graded STRONGLY_SUPPORTED rather than CONFIRMED only because the
control failure rate (~2 %) makes 20 clean corrected boots suggestive,
not statistically conclusive, on their own.

## Corrections this pass made (smallest, evidence-supported)

- **Path A (evidence integrity):** restored 23 CRLF-corrupted TPM
  serial.log files to their attested bytes and forbade content filters on
  `qualification/**` (commit `44571e1`); replaced the failed-unit
  collector with the phase-classifying, user-unit-aware
  `dsq-failed-units-2` and invalidated (retained) the v1 records.
- **Path B (harness):** dsq-1 itself — real observation window,
  ACPI-powerdown teardown, offline installed-journal collection, per-unit
  nine-way disposition, 33 adversarial evidence tests with mutation
  coverage.
- **No Path C change was made.** The artifact remains Commit G's
  qualified disk, byte-verified before every boot.

## Required product corrections (separate workstream, Path C)

Each requires the full rebuild chain (two hermetic builds, 17/17
qualification, new archive and installed-system targets, full matrix
rerun):

1. `bunny-first-boot.service`: pre-create `%h/.config/bunny-os`
   (user-tmpfiles.d or skel) or fix the sandbox declaration. **Blocking**:
   deterministic failure in every fresh home, including a real user's
   first login — first-boot preferences are never applied.
2. `chronyd.service` (and any service resolving a sysusers-created user):
   order after `authselect-apply-changes.service`, or bake the users into
   the image. A failed boot currently runs without time sync.
3. Quality, non-blocking: gdm stop-ordering against accounts-daemon;
   gnome-session-service SIGTERM handling at poweroff (45 s shutdown
   delay per boot); upstream avahi shutdown-path assertion (report
   upstream).

## Stop condition

Outcome B: root causes confirmed or strongly supported for every finding;
frequencies measured across five environment cells; diagnostic evidence
complete and pushed; the display-stack reliability prerequisite remains
blocked pending the Path C corrections above. No probabilistic success is
presented as qualification. The next workstream after the correction is
encrypted unlock KDF calibration and reproducibility.
