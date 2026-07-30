# Enterprise enrolment

Schema: `schemas/enrolment-message.schema.json`. Implementation: `enterprise/enrolment.py`. Tests: `tests/enrolment`.

Enrolment is optional and explicit. Consumer Bunny OS works with no account and no organisation; `docs/LOCAL_ONLY_AND_BUNNY_DISABLED.md` and `operations/modes.py` keep that qualified separately.

## Modes

`personally-owned`, `organisation-managed`, `organisation-owned`, `shared-laboratory-device`, `kiosk-or-dedicated-purpose`. The last three are organisation-owned and unlock destructive remote operations; the first two do not. See `docs/REMOTE_WIPE.md`.

## Mandatory disclosure

Nine statements must be present before anyone can confirm: organisation name, management server, policies applied, information visible to the organisation, remote actions available, application controls, update controls, unenrolment rules, and the personal-data boundary. `evaluate_disclosure` reports which specific statement an administrator failed to provide rather than failing generically, because the enrolment screen has to show the user what is missing.

On a personally owned device the disclosure must state how the owner may unenrol, and declaring blanket full-reset permission is refused.

Confirmation is always required. There is no silent enrolment path.

## Protocol

Five message types, exact field sets, a 60-second freshness window, a per-message nonce with replay rejection, and recursive refusal of secret-shaped keys inside `params` — the same shape as `installer/protocol.py`.

Tokens are single-use, expire within 24 hours, and carry no secret: the descriptor states which organisation issued it and when it expires, and the secret is proved separately by challenge response. `parse_enrolment_token` rejects a token id that has already been consumed.

`redact_for_log` is the only supported way to write an enrolment message to the journal; it emits identifiers and omits params, matching the broker's audit line. `assert_no_secret_in_arguments` refuses a command line carrying a secret, because process arguments are world-readable on Linux.

## Resumable

Nine ordered states with validated transitions. An interruption leaves the device at the last completed state and can resume or abort to `unenrolled`; it cannot land in an undefined condition. Skipping a stage is refused.
