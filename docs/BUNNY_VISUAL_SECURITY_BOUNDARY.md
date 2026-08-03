# Bunny Visual V2 security boundary

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

The visual layer observes a bounded user-private state projection and dispatches
only audited fixed actions. Command Palette input filters registered actions;
it is never passed to a shell, interpreter, subprocess, or privileged service.

Approval decisions use the existing `/usr/bin/bunny-approval-decision` adapter
with a validated request identifier and `approve` or `deny` argument. The
visual layer does not elevate privileges. In mock mode the adapter is
unavailable, controls are disabled or clearly simulated, and `VISUAL MOCK DATA`
is continuously visible.

Welcome persists an allowlist of non-secret preferences with telemetry forced
off and mode `0600`. It does not collect passwords, provider tokens, API keys,
or accounts and does not contact a network service.

The V2 branch does not change qualification evidence, release gates, stable or
pilot status, signing records, reproducibility records, production keys, or
the default session.
