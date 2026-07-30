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

## How a policy reaches a running desktop

1. The policy agent verifies a signed organisation bundle and stages it at `/var/lib/bunny-os/policy/staged-policies.json`, root-only.
2. It connects to `/run/bunny/policy.sock` — mode 0600, a different socket from the user broker with a different method table and a different authentication rule — and sends only `policyId` and `version`.
3. The broker reads the desired state from the staged bundle it already verified, so the socket is never a channel for a novel value, and applies it by atomically writing `/etc/bunny-os/managed-settings.json`.
4. The desktop settings layer reads that overlay. A locked setting reports `managed: true`, `lockedBy`, and `effectiveSource: organisation`, and `set()` raises `SettingLockedError` naming the organisation and the policy.

The agent cannot use the user broker socket: `auth.py` rejects UIDs below 1000 and `authorize_polkit` requires an active logind session a headless daemon does not have. `require_local_user` was deliberately left untouched and `require_policy_identity` added alongside it, because a shared function with a mode flag is one bug away from opening the user socket to system identities.

## What an organisation may and may not lock

`MANAGEABLE_SETTINGS` is an allowlist, so a setting absent from it cannot be managed even if the overlay names it. `NEVER_MANAGEABLE_SETTINGS` additionally refuses `telemetryEnabled`, `memoryEnabled` and the four accessibility settings by name — an organisation has no legitimate need to take a user's accessibility controls away.

A value failing its own validator is discarded and reported in `managed_status().rejected`, never applied. A malformed organisation policy must not brick a desktop, and must not take effect silently either.

`reset()` on a locked setting returns the organisation's value, not the Bunny OS default, because resetting to default would otherwise be a one-command escape from policy.

## Network kinds

`sync` and `enrolment` are both in `NETWORK_KINDS`, with a different and explicit local-only decision each. `sync` is denied under local-only mode: a user asking for their content to stay on the device means it, even though the service could not read what would be uploaded. `enrolment` is allowed, matching `os_update`, because it is management traffic carrying no user content. Offline mode stops both.

## What remains unproven

No policy has been delivered to a running device, because no control plane exists to deliver one. The transport, the overlay and the refusals are implemented and tested; end-to-end delivery is not.
