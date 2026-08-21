# Two values in `interaction.json` are redacted

`interaction.json` in this directory has **two `password` values replaced with
`<redacted>`**: robin's and sam's, the accounts this journey creates.

## Why the file needed it

The session driver records each request beside its answer, which is what makes
a journey readable afterwards — and it recorded the request *verbatim*. The
account-creation journey passes the new account's password as a request
parameter, so the password was written into the record in plaintext.

It was found by `tests/evidence/test_no_credentials_in_evidence.py`, on the
first run in which that gate met real staged evidence. Nothing else in the
tree carried it.

## Why redaction, and not a correction note

Everywhere else in this phase, a committed record that turned out to be wrong
was left alone and corrected alongside — see
`qualification/phase4/artifact/CORRECTION.md`. A secret is the one case where
that rule cannot be followed, because the point of the immutability rule is
that the bytes stay reachable for ever, and that is exactly what must not
happen to a credential. **This file had not been committed yet**, so nothing
is being rewritten: what happened is a decision about what to publish, taken
before publication, which is the only moment at which it can be taken.

The unredacted original remains on the builder at
`build/out/phase3/login/g5/interaction.json` and is not published.

## What is not redacted

Everything else, including every field this journey exists to prove: the
`CreateUser` return codes, the D-Bus object paths, the `Session=bunny`
property read back from each account, and the on-disk AccountsService record
showing which template each came from. The redaction removes two credentials
and no evidence.

## Fixed at source

`build/scripts/phase3-session.py` now redacts `password`, `passphrase`,
`secret`, `token` and `credential` at every depth of a request before it is
recorded, so a later run cannot write one down. The staging step redacts as
well and reports how many values it removed, because a redaction nobody is
told about is indistinguishable from a record that never had a secret in it.

**`g15` re-proves the same claim on a record that was clean when it was
written**, by creating a third account through the fixed driver.
