# Tester privacy and credential handling

The program wants your experience, not your identity, and it is built so
that collecting less is the default that machinery enforces — not a
promise someone has to remember.

## What never enters repository evidence

By default, none of the following appears in any report, attachment, or
derived record:

    real name
    email address
    IP address
    street address
    government identity
    hardware serial number

You are `T-NNN`. The mapping from `T-NNN` to a person lives with the
program operator, outside this repository. If some process outside this
repository ever genuinely requires more (it has not), that exchange
happens outside the evidence tree and is not copied into it.

Machine differentiation, when you test on several machines, uses a label
**you choose** (`machine-1`, `blue-desktop`) — never a serial number,
never a hostname that names you.

## The credential scan

Before a single byte of a submission is ingested, the intake scans the
record and every attachment for likely credential material:

    private keys        password / passphrase assignments
    bearer tokens       API and session token assignments
    cloud access keys   JSON web tokens, code-forge tokens

On a hit, the submission is **rejected with nothing ingested**: the
credential never touches the evidence tree, and the recorded refusal
names the class and filename — never the value. This is deliberately
fail-closed: a false positive costs you one masked resubmission; a false
negative would publish a credential into permanent, immutable evidence.
Treat any real credential that appeared in something you almost sent as
compromised, and rotate it.

The scan is byte-level, so nesting does not hide anything: a token three
levels deep in an attached JSON file is the same bytes.

## Redaction, when it ever happens

The program prefers rejection (you resubmit masked) over editing your
submission — your original is never mutated. If an approved process ever
performs redaction to salvage evidence, the derived record states: what
class of data was removed, why, how many values, and which derived
evidence was created from the redacted copy. The redacted original is
handled under the quarantine rules; the explanation never repeats the
secret.

## Quarantine

A submission whose content is unsafe for the permanent evidence tree
(credentials, working exploit detail) is recorded as a refused intake —
the decision, its reason class, and the date are immutable evidence that
the submission happened — while the unsafe bytes stay with the operator,
outside the repository. Nothing is silently discarded; nothing unsafe is
published.

## What the project does with what it keeps

Reports are preserved verbatim, forever, in an append-only sealed
ledger. They are quoted in derived registers with your words intact and
your `T-NNN` as the only identity. Nothing you report is used for
anything except qualifying this software.
