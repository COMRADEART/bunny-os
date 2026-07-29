# Organisation application deployment

```text
make test-fleet
```

Show a signed Flatpak entry accepted with its enforceable permission set, its update policy, and its support owner.

Refusal:

- Set `signatureVerified: false`: refused. Unsigned packages never pass the trusted catalogue interface, whatever the source.
- Declare `full-system-access` on a Flatpak entry: refused, because the sandbox cannot express it.
- Declare bounded permissions on an `rpm` entry: refused, and show that the entry instead carries the broad-system-access label that cannot be suppressed.
- Put an `apiKey` in `managedConfiguration`: refused.
- Mark an application `required` and `user-removable`: refused.
- Mark a package both `required` and `blocked`: resolves to `blocked`, because the safe reading of a policy error is not to install.
