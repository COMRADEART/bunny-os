# ADR-022: Enterprise policy agent

- Status: accepted as design; the privileged transport is unimplemented
- Date: 2026-07-29

## Decision

Policy is applied through typed, named operations with validated desired states. There are 15 managed domains and 15 operations, and no operation accepts a command, argv, script, interpreter, environment, or server-chosen path. This extends the rule `services/bunny-system-broker/src/bunny_system_broker/backend.py` already states — "No operation accepts an executable or argv" — from the broker to the fleet.

Twelve safety invariants are not policy-controllable at any enforcement level and are rejected at parse time, so an unreviewed policy cannot exist even as a draft. An organisation may require encryption; it may not disable update signature verification or expose private Bunny memory.

Precedence is fixed and total: safety invariant, OS security policy, organisation device policy, user preference, application preference. Ties within a layer are refused rather than resolved arbitrarily.

## Why not a generic execution channel

Every management product that ships one becomes a remote code execution tool, and the fleet server becomes the highest-value target on the network. A typed surface means a compromised control plane can pin a channel or set a deadline but cannot run code. The cost is that each new managed capability requires a code change and a review, which is the intended friction.

*Reusing the existing user broker socket* was rejected because it does not fit: `auth.py` refuses UIDs below 1000 with "system service identities may not use the user broker API", and `authorize_polkit` requires an active logind session that a headless daemon does not have. A separate socket with its own peer-credential rule is required.

*Writing policy into the existing settings store* was rejected as insufficient: `shell/services/bunny_shell/settings.py` has 22 user-scoped settings, no organisation scope, and no locked-setting mechanism. It reports a `policyOwner` but cannot enforce one.

## Consequences

Both gaps are real and unclosed. The policy agent's privileged transport and the settings-layer override mechanism are unimplemented, and are recorded in `KNOWN_LIMITATIONS.md` and `docs/DEVICE_POLICY.md`. What exists is the policy model, the validation, the conflict resolution, and the tests — not a running agent that changes system state.
