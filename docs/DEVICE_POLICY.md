# Device policy

Schema: `schemas/device-policy.schema.json`. Implementation: `enterprise/policy.py`, `enterprise/conflict.py`. Tests: `tests/policy`.

## Typed operations only

Every policy binds to exactly one named operation with a validated desired state. There are 15 managed domains and 15 operations. No operation accepts a command, argv, script, interpreter, environment, or server-chosen path — the same rule `services/bunny-system-broker/src/bunny_system_broker/backend.py` already states for the broker. `_assert_no_execution_channel` rejects an execution-shaped key at any nesting depth inside `desiredState`.

Run `python -c "import json,enterprise.policy as p; print(json.dumps(p.describe_domains(), indent=2))"` for the catalogue.

## Managed domains

Update channel, update deadline, application allowlist, application blocklist, firewall baseline, screen lock, encryption requirement, Secure Boot requirement, minimum OS version, recovery readiness, Bunny provider policy, local-only AI requirement, plugin policy, removable-media policy, diagnostic-export policy.

## Policy fields

ID, version, domain, scope, owner, desired state, enforcement type, effective time, expiry, priority, conflict rule, remediation. Enforcement types are `informational`, `recommended`, `enforced`, `blocked`. A `blocked` policy must declare a remediation other than `none`.

## Safety invariants

Twelve settings are not policy-controllable at any enforcement level, including update signature verification, update trust root, security-warning visibility, recovery availability, permission enforcement, memory exposure to an organisation, diagnostic redaction, and sync end-to-end encryption. `parse_policy` rejects them before storing, so an unreviewed policy cannot exist even as a draft.

An organisation may require encryption. An organisation may not disable update signature verification or expose private Bunny memory.

## Precedence

```text
safety invariant
operating-system security policy
organisation device policy
user preference
application preference
```

Within a layer, higher priority wins. A tie is refused rather than resolved arbitrarily, because an arbitrary winner makes fleet behaviour unpredictable.

Every resolution produces an explanation and names the owning layer. `explain_for_display` feeds the settings surface so a user who cannot change a control is told which layer decided that and who owns it. Silent enforcement is the failure this is built to prevent.

## Known gap

`shell/services/bunny_shell/settings.py` has no organisation scope today: all 22 settings are user-scoped, and `describe()` reports a `policyOwner` but there is no override or locked-setting mechanism. Wiring the agent's decisions into that surface is unimplemented Phase 7 work and is recorded in `KNOWN_LIMITATIONS.md`.

The agent also cannot use the existing user broker socket: `auth.py` rejects UIDs below 1000 and requires an active logind session, and a system daemon has neither. A separate socket with its own peer-credential rule is required and is not implemented. See `docs/adr/ADR-022-enterprise-policy-agent.md`.
