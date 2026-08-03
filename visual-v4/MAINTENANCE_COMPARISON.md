<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Maintenance comparison

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

This comparison is an architectural judgement rather than a harness result, and
it is recorded **unscored**. `maintenance-burden` carries 7 points and
`security-boundary-ownership` carries 8; both arms score 0 in both, because an
estimate made before either arm exists is a guess with a number attached, and a
guess with a number attached is how a scorecard starts lying.

What can be stated without measuring:

## Smithay

Smithay puts Bunny upstream of nothing. Every protocol Bunny needs is implemented
in Bunny's own tree, which means every protocol Bunny needs is Bunny's to
maintain — including the tedious, security-sensitive ones: screen capture, input
method, session lock.

The V3 gap list is, read one way, simply a list of protocols nobody has written
yet. That is a cost that arrives once. The recurring cost is that each of those
protocols then has to track upstream Wayland protocol evolution, and each is a
place where a Bunny-specific bug becomes a Bunny-specific CVE.

## libmutter

libmutter puts Bunny downstream of GNOME's release cadence and API churn. The
maintenance question is not "does libmutter implement this" — it does — but "what
happens to the Bunny downstream shell when libmutter changes".

That cost is invisible until the first major version bump lands, and it is not
reliably proportional to anything observable beforehand. A downstream that tracks
libmutter closely inherits its fixes; one that lags inherits its CVEs.

## Security-boundary ownership

The trade-off is legible even unmeasured, and it is genuinely a trade rather than
a ranking.

Smithay makes Bunny the owner of its own security boundary. That is both the risk
and the point: nothing is inherited, so nothing is assumed, and the lock screen
is exactly as good as Bunny makes it.

libmutter inherits a boundary that is well exercised in GNOME Shell — but the
guarantees are not transitive to a different downstream, because the downstream
owns the lock surface and the session lifecycle. Inheriting a well-tested library
beneath a differently-wired session is not the same as inheriting a well-tested
session.

Which is preferable depends on measurements neither arm has produced.

## What an honest version of this document needs

Both arms existing, and at least one upstream version bump absorbed by each.
Neither condition holds, so neither category is scored.
