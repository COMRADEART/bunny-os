# chronyd NSS ordering correction

Scope: the correction of `chronyd.service`, which failed on 1 of 60 control
boots in the dsq-1 diagnostic pass with `217/USER` and did not retry.

Status: the mechanism is measured and the correction is in the image and
verified by `systemd-analyze`. Whether it eliminates the failure across a full
matrix is Stage 8's evidence, and is not claimed here.

---

## 1. The observed failure

One boot in sixty, cell A only (cells B–E: zero). Signature:

```
chronyd.service: Failed to determine credentials for user 'chrony': Unknown user
chronyd.service: Main process exited, code=exited, status=217/USER
```

No restart: `chronyd.service` declares no `Restart=`. The system then ran for
the rest of the session with no time synchronisation.

dsq-1 graded this `FIRST_BOOT_NSS_WINDOW_RACE` / `STRONGLY_SUPPORTED` — the
failure fell inside the `authselect-apply-changes.service` window on the one
boot it occurred, and a 20-boot diagnostic arm with `After=` on that unit
produced 20 clean boots. Suggestive at a ~2% base rate, not conclusive.

---

## 2. The mechanism, corrected

The dsq-1 disposition records the mechanism as: *"The image bakes no chrony
user (systemd-sysusers creates it at boot)."*

**That is not what happens on this image.** Measured directly:

```
$ grep -c '^chrony:' /etc/passwd            0
$ grep -c '^chrony:' /usr/lib/passwd        1
$ getent passwd chrony
chrony:x:994:992::/var/lib/chrony:/usr/sbin/nologin

$ grep '^passwd' /etc/authselect/nsswitch.conf
passwd:     files altfiles systemd

$ ls -l /etc/nsswitch.conf
/etc/nsswitch.conf -> /etc/authselect/nsswitch.conf
```

The `chrony` account is **not created at boot by sysusers**. It is already
present, in `/usr/lib/passwd` — the fedora-bootc base user database — and is
resolved through the **`altfiles`** NSS source. `systemd-sysusers` would be a
no-op for an account that already resolves.

What makes it transiently unresolvable is that `/etc/nsswitch.conf` is a
symlink to `/etc/authselect/nsswitch.conf`, and
`authselect-apply-changes.service` runs `authselect apply-changes --upgrade`,
which **rewrites that exact file** on first boot. For the width of that
rewrite, the `altfiles` source is not in effect, so *no* account provided by
`/usr/lib/passwd` resolves — chrony included. Nothing about chrony changes; the
name service does.

This matters for more than accuracy. Under the sysusers reading, the fix is to
wait for `systemd-sysusers.service`, which is `Before=sysinit.target` and
completes long before authselect — so that correction would have been ordered
against the wrong unit and would not have closed the window. It also means the
exposure is not chrony-specific: any unit resolving an `altfiles`-provided
account during that window is subject to the same race. `gdm` is not, because
uid 42 *is* baked into `/etc/passwd`.

`chronyd.service` as shipped has no ordering that covers this:

```ini
[Unit]
After=ntpdate.service sntp.service ntpd.service
Conflicts=ntpd.service systemd-timesyncd.service
ConditionCapability=CAP_SYS_TIME
```

---

## 3. The correction

`/usr/lib/systemd/system/chronyd.service.d/50-bunny-nss-order.conf`:

```ini
[Unit]
Wants=nss-user-lookup.target
After=nss-user-lookup.target
After=authselect-apply-changes.service
```

**Why the target and not only the unit.** `authselect-apply-changes.service`
already declares:

```ini
Before=systemd-user-sessions.service nss-user-lookup.target
```

`nss-user-lookup.target` is systemd's documented contract for "identity sources
are settled", and authselect promises to be ordered before it. Ordering chronyd
after the target therefore covers the measured window *and* stays correct on an
image where authselect is absent or inapplicable — the target is passive, so it
is simply reached at once and chronyd is not delayed. This is the same pattern
upstream `accounts-daemon.service` uses, for the same reason; its unit body
carries `Wants=`/`After=nss-user-lookup.target` with a comment about avoiding
races with identity-providing services.

**Why `Wants=` is load-bearing, not decorative.** `nss-user-lookup.target` is
passive: nothing pulls it into the boot transaction by itself, and an `After=`
on a unit that is not in the transaction orders nothing at all. Without the
`Wants=`, the drop-in would look correct and change nothing. This is the exact
failure mode Stage 3 rejection 16 names, and
`tests/first_login/test_corrections.py` fails if the `Wants=` is removed.

**Why authselect is also named.** The target is what upstream units promise to
be ordered before; `authselect-apply-changes.service` is the unit whose window
was actually measured, and it is enabled in `multi-user.target.wants` on this
image, so it is in the transaction. An `After=` on an absent unit is a no-op,
so naming it costs nothing where authselect is not installed.

**Why not `Requires=`.** `authselect-apply-changes.service` carries
`ConditionPathIsReadWrite=/etc`. A `Requires=` would make chronyd fail wherever
that condition does not hold, converting a timing problem into an availability
problem. The drop-in adds ordering edges out of chronyd only — no `Before=` —
so it cannot close an ordering cycle; a test asserts the `Before=` list is
empty.

---

## 4. Verification

In the image built at Commit O, `systemd-analyze verify chronyd.service`
exits 0, and the merged unit shows:

```
After=ntpdate.service sntp.service ntpd.service
Wants=nss-user-lookup.target
After=nss-user-lookup.target
After=authselect-apply-changes.service
```

The drop-in is at
`/usr/lib/systemd/system/chronyd.service.d/50-bunny-nss-order.conf`, with 0 CR
bytes. `build/scripts/ci-verify-units.sh` now copies `*.service.d/`
directories; its previous globs would have silently skipped this drop-in and
verified a chronyd without it.

### The ordering is now measurable

dsq-1 recorded the authselect apply window but **no chronyd timestamp**, so the
ordering could only be argued from the absence of a failure. The analysis now
records, per boot:

| field | meaning |
|---|---|
| `chronydStartRequestedMono` | when the manager requested chronyd |
| `chronydActiveMono` | when it became active |
| `nssUserLookupReachedMono` | when the target was reached |
| `authselectApplyStartMono` / `EndMono` | the window |
| `orderedAfterAuthselect` | request ≥ apply end |
| `startedInsideApplyWindow` | request falls inside the window |
| `userResolutionFailure` | main exit status is `217/USER` |

`orderedAfterAuthselect` is `None`, not `False`, when either timestamp is
absent. A boot where authselect had nothing to apply proves nothing about the
ordering and must not be counted as proving it holds — the gate treats an
unprovable boot as unprovable rather than as a pass.

---

## 5. What the gate refuses

From `tests/first_login/test_evidence_gate.py`, each built from a valid record
with exactly one fraud:

* chronyd exiting `217/USER` blocks the run (rejection 15);
* chronyd spawning inside the apply window blocks it (rejection 14);
* a single such failure among otherwise-clean runs still blocks — there is no
  percentage threshold, and a test asserts that one failure in an otherwise
  passing pair is not tolerated.

---

## 6. Limitations

* **Not yet observed across a matrix.** The correction is in the image and
  `systemd-analyze` accepts it. The 60-boot evidence is Stage 8's.
* **The base rate is low.** The control failure was 1 in 60. A clean matrix
  raises confidence but cannot by itself distinguish a fixed race from an
  unobserved one; the ordering assertion — that chronyd's request timestamp
  follows the apply window in every boot — is the stronger claim, and it is
  what the gate checks per boot rather than inferring from the absence of
  failures.
* **The exposure is broader than chronyd.** Any unit resolving an
  `altfiles`-provided account inside the authselect window is subject to the
  same race. This pass corrects the one unit that was measured failing; a
  systematic sweep of units with `User=` against `/usr/lib/passwd` is not part
  of it and is recorded in `KNOWN_LIMITATIONS.md`.
* **The dsq-1 disposition text remains as written.** It is frozen evidence
  about the superseded archive and this pass does not edit it. Its mechanism
  description is superseded by section 2 above.
