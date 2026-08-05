# Local and remote execution

Implementation: `capability/router.py` (tasks), `capability/engine.py` (services).

`engine.py` decides what *services* run. `router.py` decides where one *task*
runs — a different question, asked far more often and against much stronger
constraints. A service placement is a resource decision; a task placement can be
a disclosure.

## The rule

> Sensitive tasks must not be sent remotely merely because the local device is
> weak.

The routing order is therefore **permission first, capability second**:

1. May this task leave the device *at all*? Asked before, and independently of,
   whether it could run here.
2. Can it run locally? If yes, it does — local is preferred.
3. Only now, is remote permitted, configured, reachable and affordable?

Local incapability is never an argument for remote execution. A weak machine
running a sensitive task gets *"this cannot be done here, and it may not be done
elsewhere"*, which is the honest answer, rather than a quiet upload.

`TaskRequest.may_ever_leave_device` is a property of the task alone, computed
before any hardware or policy is read:

```python
remote_allowed and data_locality != "device-only"
                and not requires_offline
                and privacy != "secret"
```

## Task declaration

```python
TaskRequest(
    id="plan-7-step-3",
    capability="inference",        # inference | tts | stt | render | ...
    privacy="internal",            # public | internal | sensitive | secret
    data_locality="any",           # any | trusted-remote | device-only
    latency="interactive",         # interactive | batch
    maximum_cost_units=0,          # 0 means nothing may be spent
    requires_offline=False,
    remote_allowed=True,           # cannot widen what policy permits
    user_approved=False,
    local_memory_bytes=None,
    local_requirements={"local_ai": 40.0},
)
```

`maximum_cost_units=0` means *nothing may be spent*, which is not the same as
"no limit". A paid provider is refused against it.

`local_requirements` gates are checked with `when_unknown=False`: an unmeasured
dimension does not satisfy a requirement, because the failure mode of guessing
is a task that starts and dies.

## Policy

```yaml
remote_execution:
  enabled: false                # off by default
  require_user_approval: true   # even when enabled
  allow_sensitive_data: false   # even when enabled and approved
  permitted_providers: []       # "on" is not a destination
```

The four are **independent**. Enabling remote execution does not enable
sensitive-data egress, does not waive approval, and does not name a destination.
An empty allowlist permits nothing even when `enabled` is true, and a policy in
that state produces a warning saying so.

Related, and also default-deny:

```yaml
metered_network_allowed: false   # unknown metering is treated as possibly metered
confirm_before_paid_api: true
```

## Providers are an interface, not an integration

```python
@dataclass(frozen=True)
class ProviderDeclaration:
    id: str
    title: str
    locality: str            # loopback | private-network | hosted
    retention: str           # none | ephemeral | logged | unspecified
    trains_on_input: bool | None
    costs_money: bool
    capabilities: tuple[str, ...]
    jurisdiction: str
```

Every field is read by the router or rendered into a disclosure. There is
deliberately no free-text "description of our privacy practices": a disclosure
that renders from prose cannot be checked.

**Undeclared fails closed.** `fully_declared` requires a concrete `retention`, a
non-`None` `trains_on_input`, and a recognised `locality`. A provider that will
not say whether it trains on input cannot be the destination for a decision the
user is entitled to understand.

`RemoteProvider` is a `Protocol`. `NullProvider` — which declares nothing and
accepts nothing — and the test doubles in `tests/capability/test_router.py` are
the **only implementations in this repository**. Nothing here contacts a named
commercial service, no credential is read, stored or logged by this module, and
no integration with any specific provider exists or is implied.

## Refusal order

A remote dispatch is refused, in this order, by:

1. the task may not leave the device (`secret`, `device-only`, offline
   requirement, `remote_allowed=False`)
2. `remoteExecution.enabled` is false
3. the task is `sensitive` or above and `allowSensitiveData` is false
4. there is no default route
5. the connection is metered, or of unknown metering, and metering is not
   permitted
6. per provider: does not serve the capability / not allowlisted / not fully
   declared / bills money the task will not spend / not currently available
7. `requireUserApproval` and the task is not approved — this returns the
   provider id and `requiresUserApproval: true`, so the surface asking for
   approval knows what it is asking about

Consent before configuration, configuration before connectivity: a user whose
sensitive workload may not leave the machine is told *that*, not told the
network is down.

## Disclosure

A dispatched task carries a complete, mechanically rendered disclosure:

```json
{
  "provider": { "id": "...", "locality": "hosted", "retention": "none",
                "trainsOnInput": false, "costsMoney": false,
                "capabilities": ["inference"], "jurisdiction": "unspecified" },
  "capability": "inference",
  "privacy": "internal",
  "whatLeavesTheDevice": "the inputs of task plan-7-step-3",
  "costPermitted": 0
}
```

Every routing decision — dispatched or refused — carries its full reason list, so
it can be reconstructed after the fact.

## Services versus tasks

For **services**, `engine.py` applies the same principles through
`_remote_eligibility()`, ordered identically: sensitivity, then permission, then
provider allowlisting, then connectivity, then metering, then payment, then
approval. A service manifest's `handlesSensitiveData` plays the role a task's
`privacy` classification does.

Every remote implementation in `capability/services/` names a provider, and
`tests/capability/test_manifest.py` asserts it: an unnamed destination cannot be
allowlisted, so a manifest declaring one would be dead weight that looks like a
capability.

## What is not implemented

- No transport. Nothing in this repository opens a connection to a provider.
- No authentication. Phase 1 §A.9 requires remote execution be treated as
  untrusted until authenticated; the authentication itself is future work.
- No credential storage. Keys are not read, written, defaulted or logged here.
- No provider integrations of any kind, real or mocked-as-real.

The interfaces and the entire decision path are complete and tested against
stubs, so an integration can be added without the policy logic changing.
