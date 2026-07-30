<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ADR-028 — Deterministic package-manager state

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-07-30 |
| Supersedes | — |
| Related | ADR-027 base image security decision; `docs/IMAGE_FINALISATION.md` |

## Context

Two independently administered builders built commit
`9ea5459bdaf122f8c5999683b2c8961555826954` against the same base digest and
produced images sharing 164,356 identical paths, identical permissions and
ownership, an identical 6,076-package inventory and an identical kernel.
Fifteen files out of 104,247 differed. Five of them are package-manager state:

```text
usr/share/rpm/rpmdb.sqlite
usr/lib/sysimage/libdnf5/system.toml
usr/lib/sysimage/libdnf5/transaction_history.sqlite
usr/lib/sysimage/libdnf5/transaction_history.sqlite-wal
usr/lib/sysimage/libdnf5/transaction_history.sqlite-shm
```

Measured causes, not assumed ones:

* `rpmdb.sqlite` — rpm writes `INSTALLTIME` into every installed package's
  header from the system clock.
* `system.toml` — contains one field, `rpmdb_cookie`, a digest **derived from
  the rpmdb**. It differs only because the rpmdb differs.
* `transaction_history.sqlite` — records transaction timestamps.
* `-wal` and `-shm` — write-ahead-log residue recording where an unflushed
  transaction happened to stop.

The remaining ten differing files are a random `brlapi.key`, seven fontconfig
caches and two dnf `countme` counters, addressed elsewhere.

Excluding the rpm database from comparison was considered and rejected before
this decision was written. The brief is explicit — *package-manager state may
not be ignored merely because it is "not product code"* — and the reason is
sound: `rpm -V` verifies an installed system against this database, a security
auditor queries it, and a licence inventory is derived from it. A file that
important is exactly the wrong one to stop comparing.

## Options considered

### A. Run package transactions under a controlled build clock

`libfaketime` is `LD_PRELOAD`ed for the dnf process only, with the clock frozen
at the declared build epoch.

| Dimension | Assessment |
| --- | --- |
| Database integrity | Unaffected. rpm writes its own database through its own code path; only the value it reads from `clock_gettime` changes. |
| Package verification | Unaffected. `rpm -V` compares file digests, sizes, modes and owners against the header — none of which is the install time. |
| Signature preservation | Unaffected. Every RPM keeps its original Fedora signature and is verified at install time against Fedora's own key. |
| Query compatibility | `rpm -qi` reports an install time equal to the commit timestamp rather than to when the build ran. That is *more* accurate for an immutable image, where "when was this installed" has no per-device answer. |
| Update compatibility | Unaffected. dnf compares versions, not install times. |
| Repair tooling | Unaffected. `rpm --rebuilddb` and `rpm --verifydb` operate normally. |
| Security | The override is scoped to one process. It touches no TLS handshake, because the snapshot is a `file://` repository; it does not disable signature checking; and the epoch is the candidate commit's timestamp, which is inside the validity of every key involved. |
| Supportability | libfaketime is a packaged Fedora tool. It is bind-mounted from the builder image and **never installed into the product image**, so it adds nothing to the artifact or to its attack surface. |

### B. Rebuild the RPM database deterministically after installation

`rpm --rebuilddb` rewrites the database from the headers it already holds.

Rejected: it does not change `INSTALLTIME`, because that value is *in* the
headers. It would normalise sqlite page layout and leave the actual cause
untouched — a fix that makes the symptom smaller and the diagnosis harder.

### C. Export package headers and reconstruct the database canonically

Rejected as too close to the thing the brief forbids. Reconstructing the
database outside rpm's own code path means owning rpm's on-disk format
indefinitely, and a reconstruction that subtly diverged would produce a database
that queries correctly and verifies wrongly. The brief's "do not hex-edit or
arbitrarily rewrite the RPM database" is aimed at exactly this class.

### D. Move non-essential transaction history out of the immutable image

Rejected as a primary fix, adopted in part as a secondary one. Deleting
`transaction_history.sqlite` would remove the record of what was installed —
needed for repair, security auditing, licence inventory and update
compatibility. What *is* removed is the WAL residue, and only after
checkpointing it into the database, so no recorded transaction is lost.

### E. Another RPM-supported deterministic mechanism

None exists. `SOURCE_DATE_EPOCH` is honoured by rpm when *building* packages,
not when installing them, and this build installs pre-built packages.

## Decision

**A, with D applied to the WAL residue only.**

1. The package transaction runs under a frozen clock set to the declared build
   epoch, provided by `libfaketime` bind-mounted from the builder image and
   `LD_PRELOAD`ed for the dnf process alone.
2. After installation, both sqlite databases are checkpointed with
   `PRAGMA wal_checkpoint(TRUNCATE)` and vacuumed, so `-wal` and `-shm` are
   absent rather than nondeterministic. The transaction history itself is kept.
3. `system.toml` is left untouched. It is derived from the rpmdb, so it follows
   automatically — and if it ever fails to, that is a real divergence in the
   database and the comparison should report it rather than have it normalised
   away.
4. The epoch's scope is declared in `build/inputs/reproducibility-lock.json` and
   validated: `appliedTo` may name only declared-applicable sites, and
   `neverAppliedTo` must list certificate validity, advisory freshness,
   signature verification, update-metadata expiry and evidence timestamps
   explicitly.

## Consequences

**Accepted.** `rpm -qi` reports an install time that is the commit timestamp.
Anyone reading it as "when this machine installed the package" will be wrong;
for an immutable image built once and installed on many devices, there was never
a correct per-device answer in the image.

**Accepted.** The build depends on `libfaketime` being present on the builder.
It is pinned in the builder image and the build fails closed when it is absent,
rather than continuing and producing an artifact that silently cannot reproduce.

**Rejected.** Any suggestion that this makes the rpm database "fake". The
database records what was installed and from which signed package; only the
recorded clock differs, and it differs to a value that is written down, checked
and reviewable.

**Not established.** That the rpm database is now byte-identical between two
builders. This ADR records the mechanism and the reasoning; whether it works is
a measurement, and it is reported in `RPM_DATABASE_DETERMINISM_REPORT.md` from
an actual two-builder comparison rather than asserted here.

## Verification

Required before this decision is treated as effective:

```text
rpm --verifydb                     the database is structurally sound
rpm -qa | wc -l                    the package count is unchanged
rpm -V <sample>                    file verification still passes
dnf history list                   the transaction history is intact and queryable
```

and, from two builders:

```text
make rpmdb-determinism-check       usr/share/rpm/rpmdb.sqlite identical
```

A passing `rpmdb-determinism-check` without a passing `rpm --verifydb` is a
worse outcome than the difference it replaced, and both are required.
