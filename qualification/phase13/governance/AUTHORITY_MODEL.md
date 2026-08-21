# Phase 13 authority model

The subject artifact is `e906a48793d7`, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
frozen, unsigned. The question this model governs is who may make each
release decision about it — and the one rule everything below serves:

> The repository may evaluate whether authorization requirements are
> satisfied. It may never create the authority that satisfies them.

## The seven authorities

| Identifier | Role | Responsibility |
| --- | --- | --- |
| `AUTH-SECURITY-REVIEWER` | `SECURITY_REVIEWER` | Produces independent review evidence |
| `AUTH-SECURITY-OWNER` | `SECURITY_OWNER` | Resolves security disposition and accepted risk |
| `AUTH-ALPHA-PROGRAM` | `ALPHA_PROGRAM_OWNER` | Defines Alpha sufficiency thresholds |
| `AUTH-RELEASE` | `RELEASE_AUTHORITY` | Makes final artifact authorization decision |
| `AUTH-KEY` | `KEY_AUTHORITY` | Controls production signing |
| `AUTH-SECOND-APPROVER` | `SECOND_APPROVER` | Independently verifies and approves |
| `AUTH-HARDWARE` | `HARDWARE_VALIDATION_OWNER` | Owns interpretation of physical hardware evidence |

No real person is named in `authorities.json` by design: no external
identities are legitimately available, and hard-coding one would be the
repository assigning authority to itself.

## Three levels, kept distinct

- **`ROLE_DEFINED`** — the role exists in `authorities.json`. Nothing
  more. A role existing in a JSON file is not an authority action.
- **`AUTHORITY_ASSIGNED`** — a sealed assignment record in
  `assignments.json` names an identity, an assigner, a date, and a basis.
  Assignment is appended only through
  `release_authority_ops.py record assignment`; a hand edit breaks the
  record's seal and fails every subsequent run closed.
- **`AUTHORITY_ACTED`** — the act itself exists. For the
  evidence-producing roles (reviewer, key authority, second approver,
  hardware owner) the act is a gate-eligible ACCEPTED intake in the
  matching Phase 9 source. For the decision-making roles (release
  authority, security owner, Alpha program owner) the act is a validated,
  sealed Phase 13 decision — which validates only against an assignment,
  so a decision-making authority can never have acted without first
  having been assigned.

The derived `authorization-status.json` reports the level of every
authority on every run. At Phase 13 close all seven are `ROLE_DEFINED`.

## Separation of duties

`separation-policy.json` names the incompatible pairs. One identity may
not silently occupy both sides of any of them:

- reviewer / security owner (the reviewer's independence)
- reviewer / release authority
- security owner / release authority
- Alpha program owner / release authority (the threshold-setter must not
  be the one the thresholds gate)
- release authority / key authority
- release authority / second approver
- key authority / second approver (the signer may not approve their own
  signature)

If the organization explicitly permits an overlap, that is a **recorded
policy decision**: a sealed record in `separation-policy.json` naming the
identity, both roles, the reason, the deciding authority, and the date.
Matching strings never permit anything; an inferred overlap is a
separation violation, and a separation violation refuses `AUTHORIZED`.

## What this model cannot check

Mechanical validation ends at the record. The tools verify that an
authority is named, assigned, and acted — not that the name belongs to a
real, independent person. That judgment is human, stays human, and is
recorded, never manufactured. This is the same honesty boundary Phase 9
declared for intake identity, inherited here unchanged.
