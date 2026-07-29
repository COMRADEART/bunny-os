# Device attestation

Schema: `schemas/device-attestation.schema.json`. Implementation: `enterprise/attestation.py`. Tests: `tests/identity`.

Optional. A device that does not attest is not penalised beyond the compliance status an organisation chooses to assign.

## Reportable

Exactly eight facts: verified boot state, Secure Boot state, OS image digest, update channel, broker version, recovery availability, encryption state, and policy-agent status.

Enforcement is exact-set equality, following `operations/crash.py`. Every listed field is required and no other field is permitted, so adding a field needs a code change and a review.

## Never reportable

User files, file names, prompts, conversations, memory contents, application usage, browser history, terminal history, personal account activity, screenshots, camera or microphone content, keystrokes, and location. These are refused by name as well as by the allowlist, so a diff shows the intent and not only the effect.

## Honest states

`unknown` and `disabled` are first-class values. A device with Secure Boot off reports `disabled`; it does not omit the field or report `unknown` to look better. `docs/SECURE_BOOT.md` already requires this of the installer.

## Distinct from identity

Attestation says what software state a device is in. It does not say who is using it. See `docs/DEVICE_IDENTITY.md` for the four separated concepts.
