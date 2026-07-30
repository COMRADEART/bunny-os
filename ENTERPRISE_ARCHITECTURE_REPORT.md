# Enterprise architecture report

Date: 2026-07-29. Scope: the device-side management architecture in `enterprise/` and the trust boundaries around it.

## Component boundaries

| Component | Location | Why |
|---|---|---|
| `bunny-oem-tools` | `oem/` in this repository | Build-host and device-side only; no network service; never imported by boot, update, or recovery |
| `bunny-device-agent` | `enterprise/` in this repository | Ships with the OS, versioned with the OS contract |
| `bunny-policy-schema` | `schemas/device-policy.schema.json` | Shared contract; both sides must agree, so it lives with the other schemas |
| `bunny-fleet-server` | **separate repository** | Network service with a database and tenants; independent deployment lifecycle |
| `bunny-enrolment-service` | **separate repository** | Issues certificates; distinct compromise consequences from policy distribution |
| `bunny-encrypted-sync` | `sync/` client here, **service separate** | Separate trust domain from management by design |
| `bunny-enterprise-console` | **separate repository** | Web application; own dependency surface and release cadence |

ADRs: `ADR-023` for the control plane boundary, `ADR-024` for tenancy, `ADR-020` for sync, `ADR-022` for the agent, `ADR-025` for OEM trust, `ADR-026` for the remote boundary, `ADR-021` for identity.

No server code was placed in `services/`, `build/`, or any boot or recovery path.

## Trust domain separation

```text
Organisation control plane        Encrypted sync service
  policy, rings, catalogue          encrypted objects, device registry
  compliance, audit                 version coordination
        |                                   |
        +-----------------+-----------------+
                          |
                    Bunny OS device
```

The two services are separate trust domains. An organisation that controls device policy does not gain access to private synced content. Two mechanisms enforce this rather than one: memory and prompt exposure are safety invariants that cannot be expressed as policy at any enforcement level, and sync content is encrypted under keys neither service holds.

## Signing authority separation

Five namespaces, disjoint and validated at parse time: `update-`, `bunny-os-release-`, `oem-`, `fleet-`, `sync-`. `operations/data/phase7-key-separation.json` records what each authority can and cannot cause. A fleet-control key cannot cause an OS image to be installed. An OEM key cannot sign an offline management bundle. An OEM key named to impersonate a release namespace is refused.

## Authority model

| Layer | Can | Cannot |
|---|---|---|
| Safety invariants | — | be changed by anyone |
| OS security policy | set security defaults | be relaxed by an organisation |
| Organisation policy | 15 typed domains | disable signature verification, expose memory, run code |
| User preference | everything not managed | bypass a mandatory baseline |
| Application preference | its own settings | override the above |

Every conflict resolution names the owning layer and produces an explanation, because a user who cannot change a control is entitled to know who decided that.

## Roles

Seven roles with separated authority. `organisation-owner` is break-glass: it re-authenticates for destructive actions and the console warns when it is used for routine work. Help-desk operators cannot erase devices. Auditors perform no device operations. Read-only analysts cannot export audit records.

Destructive actions require step-up authentication with a passkey or hardware security key; a single factor is never sufficient. Custom password authentication is refused by name — Bunny OS does not build a password database when OIDC, SAML, passkeys, and hardware keys exist.

## Offline and outage behaviour

Devices operate correctly with the control plane unreachable. Policy is cached, the last applied bundle stays in force, updates continue on the device's own schedule, local administration remains available, and recovery never depends on a service. The air-gapped workflow is the extreme case of the same property.

No functional requirement was added that makes login, unlock, or recovery depend on continuous cloud availability.

## What does not exist

No fleet server, enrolment service, or console. No deployment, no load test, no failover exercise, no certificate-expiry drill, no signing-key rotation rehearsal. The policy agent has no privileged transport and the settings layer has no organisation scope, so resolved policy cannot yet change a running desktop.

## Reliability targets

Not committed. Stating an availability target for a service that has never run would be invented. What is committed is the device-side property above: the OS keeps working when the service does not.
