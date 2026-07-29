# Organisation enrolment and disclosure

```text
make test-enrolment
make test-device-identity
```

Show that a valid one-time token parses, and that the token descriptor carries no secret.

Refusal, in order:

- Replay the same token id and show `already been consumed`.
- Expire the token and show `has expired`.
- Put a `token` field inside `params` and show `secret field 'token' is forbidden`.
- Pass `--token=abc123` to `assert_no_secret_in_arguments` and show the refusal, because process arguments are world-readable.
- Remove `personalDataBoundary` from the disclosure and show that enrolment cannot be confirmed until the organisation states what stays private.
- Set `fullDeviceResetPermitted: true` on a personally owned disclosure and show it refused.

Then show that a device identity derived from `mac-address` is rejected, and that `operations/redaction.py` already redacts `deviceid`, `serial`, and `macaddress` from exports.
