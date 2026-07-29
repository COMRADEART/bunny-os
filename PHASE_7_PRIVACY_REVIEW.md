# Phase 7 privacy review

Date: 2026-07-29. Scope: fleet health, device identity, enrolment, audit records, encrypted sync metadata, account recovery, crash reporting, hardware reporting, organisation policies, and remote actions.

## Exactly what an organisation administrator can see

Ten fields, all categorical or a version string. This is the complete list.

| Field | What it reveals |
|---|---|
| `osVersion` | The OS version string |
| `updateState` | One of nine operational states |
| `recoveryReadiness` | Whether recovery is available |
| `encryptionState` | Whether disk encryption is active |
| `secureBootState` | Whether Secure Boot is enabled |
| `policyAgentHealth` | Whether the agent is running |
| `requiredServiceStatus` | Whether required services are running |
| `storageHealthCategory` | A health category, never a serial or SMART dump |
| `hardwareSupportCategory` | A support tier |
| `criticalSecurityAdvisoryStatus` | Whether a critical advisory is open |

No free text. No counts. No durations. A duration is the shortest path from an operational metric to a behavioural one, so none exists.

## What an administrator cannot see

Prompts, conversations, memory, file names, file paths, documents, browser history, terminal history, application usage or duration, keyboard or mouse activity, screenshots, camera or microphone content, and location. Refused by name and by allowlist.

Also refused: `hostname`, `username`, `email`, `macAddress`, and `serial`, reusing `IDENTIFIER_KEYS` from `operations/redaction.py` so that fleet health and diagnostic export share one definition of forbidden data rather than drifting apart.

## Device identity

A locally generated 128-bit value plus a rotatable key. `docs/PRIVACY.md` prohibits persistent tracking IDs, and a hardware serial is the most persistent identifier a device has, so no hardware identifier is used as remote identity. The existing redactor already strips `deviceid`, `serial`, and `macaddress` from exports, which means a Phase 7 identity appearing in any diagnostic bundle is removed by code that predates Phase 7.

## Enrolment

Nine statements must be shown before confirmation, including what the organisation can see and what stays private. A personally owned device must disclose how the owner may unenrol, and cannot disclose blanket full-reset permission. There is no silent enrolment path.

## Audit records

Administrator actions, not user activity. Entries are scanned against the secret and content vocabularies before acceptance. Export is one organisation per file. Retention is bounded and stated, defaulting to 400 days.

## Encrypted sync metadata

Documented rather than minimised away. Visible to an operator: account identifier, device key id, opaque collection identifier, object identifier, object version and version count, encrypted object size, and upload timestamp.

From that set an observer can infer that an account exists, how many devices it has, roughly how much data it holds and how often that changes, when a device was active, and that two devices belong to one account. This is stated in `docs/ENCRYPTED_SYNC.md` and in the code.

**The design is not zero knowledge and is not described as such.** `assert_no_zero_knowledge_claim` refuses documentation or UI text containing "zero knowledge", "we know nothing", "metadata-free", "completely anonymous", or "untraceable", precisely because the metadata above remains visible.

## Account recovery

The service cannot recover private content. Server-assisted recovery is refused unless the request presents the recovery secret or an already-trusted device. Organisation recovery reaches three organisation-owned collections and is refused on personally owned devices. There is no escrow of personal keys, consistent with `docs/RECOVERY_KEYS.md`.

## Crash and hardware reporting

Unchanged from Phase 5. `operations/crash.py` still accepts seven fields with no persistent user id, and hardware inventory still reports `privacy.transmitted: false`. Phase 7 adds no new reporting channel and no upload endpoint.

## Organisation policies

Policy can require encryption, pin a channel, restrict applications, and constrain plugins and providers. It cannot expose Bunny memory or prompts, disable diagnostic redaction, or make the privacy dashboard invisible — those are safety invariants and are rejected at parse time, so such a policy cannot exist even as a stored draft.

Provider policy references a credential *source*, never a credential value, and credential-shaped keys are refused.

## Remote actions

Fourteen typed operations, none of which reads user data. `diagnostics.status.request` returns a redacted status summary through the existing local diagnostic path; it does not read home directories or Bunny databases.

## Prohibitions upheld

No advertising, no behavioural analytics, no data brokerage, no engagement tracking. Fleet groups cannot carry behavioural attributes such as productivity or usage hours, so an administrator cannot reconstruct a behavioural metric from group membership. Pilot success criteria are restricted to eight operational measures; productivity, engagement, session length, and prompt counts are refused, because studying people requires a separate research protocol with its own consent.

## Findings

No Blocker or Critical privacy finding in Phase 7 source.

One Major limitation: the metadata visible to a sync operator is genuinely revealing about device count and activity timing, and padding reduces but does not eliminate size correlation. The mitigation is disclosure, not elimination, and users deciding whether to enable sync should be shown it.

## Not assessed

No service has been operated, so no real metadata has been observed accumulating. No privacy impact assessment has been conducted by an independent reviewer.
