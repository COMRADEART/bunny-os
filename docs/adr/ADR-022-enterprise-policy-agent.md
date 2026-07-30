# ADR-022: Enterprise policy agent

- Status: accepted; the privileged transport and the settings organisation scope are now implemented
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

Both gaps are now closed.

The transport is a second socket at `/run/bunny/policy.sock`, mode 0600, adopted by `LISTEN_FDNAMES` so it can never be confused with the user socket. `require_local_user` is untouched; `require_policy_identity` is a sibling, and authorisation is the dedicated service uid plus a `/proc/<pid>/cgroup` unit match rather than a logind session the daemon does not have. Each socket has its own method table, rate limiter and nonce cache.

The socket carries only `policyId` and `version`. The desired state comes from the bundle the agent already verified, so a compromised control plane cannot push a novel value through the interface and the broker does not reimplement the fifteen per-domain validators.

The settings layer gained a root-owned overlay at `/etc/bunny-os/managed-settings.json`, written only by the broker. `MANAGEABLE_SETTINGS` is an allowlist; `set()` raises `SettingLockedError` naming the organisation and policy; `reset()` returns a locked setting to the organisation value rather than the Bunny OS default, closing what would otherwise be a one-command escape.

What remains unproven is operational, not architectural: no policy has been delivered to a running device, because no control plane exists to deliver one.
