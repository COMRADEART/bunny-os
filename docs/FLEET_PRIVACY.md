# Fleet privacy

Schema: `schemas/fleet-health.schema.json`. Implementation: `enterprise/health.py`. Tests: `tests/fleet`.

## Exactly what an organisation administrator can see

Ten fields, all categorical or a version string:

| Field | Meaning |
|---|---|
| `osVersion` | The Bunny OS version string |
| `updateState` | Whether an update is offered, staged, installed, failed, or rolled back |
| `recoveryReadiness` | Whether a verified recovery path is available |
| `encryptionState` | Whether full-disk encryption is active |
| `secureBootState` | Whether Secure Boot is enabled |
| `policyAgentHealth` | Whether the policy agent is running |
| `requiredServiceStatus` | Whether required system services are running |
| `storageHealthCategory` | A storage health category, never a serial or SMART dump |
| `hardwareSupportCategory` | The support tier of this hardware |
| `criticalSecurityAdvisoryStatus` | Whether a critical advisory is open or patched |

There are no free-text fields, no counts, and no durations. A duration is the easiest way for an operational metric to become a behavioural one, so none is present.

## Prohibited

Prompts, conversations, memory, file names, browser history, terminal history, application usage duration, keyboard activity, screenshots, camera and microphone content, and location.

Also prohibited: identifying fields. `hostname`, `username`, `email`, `macAddress`, and `serial` are refused, reusing `IDENTIFIER_KEYS` from `operations/redaction.py` so fleet health and diagnostic export share one definition of forbidden data. Device correlation uses the enrolment identity supplied out of band, not an inline identifier.

## Behavioural analytics remain prohibited

No engagement tracking, no feature-adoption metrics, no advertising identifiers, and no data brokerage — in the fleet surface as everywhere else. `enterprise/fleet.py` additionally refuses group attributes that describe personal behaviour, so an administrator cannot rebuild a productivity metric out of group membership.

`enterprise/pilot.py` refuses productivity, engagement, session-length, and similar measures as pilot success criteria. Studying people needs a separate research protocol with its own consent, which Phase 7 does not provide.

## Audit records

See `docs/ENTERPRISE_AUDIT.md`. Audit entries record administrator actions, not user activity, and are scanned against the shared secret and content vocabularies before acceptance.
