# Remote administration boundary

Implementation: `enterprise/remote.py`. Tests: `tests/fleet`.

## Closed set

Fourteen operations. A request naming anything else is refused, and a shell-shaped name is refused with a specific message so the attempt is visible in an audit trail rather than looking like a typo.

```text
update.check.request                 Ask the device to check for updates
update.schedule                      Schedule an already-approved, signed update
device.restart.request               Ask the device to restart
device.lock.request                  Ask the device to lock the screen
enrolment.certificate.revoke         Revoke the device enrolment certificate
applications.organisation.disable    Disable organisation-deployed applications
management.certificate.rotate        Rotate the device-management certificate
diagnostics.status.request           Request a redacted diagnostic status summary
recovery.schedule                    Schedule the local recovery environment
organisation.data.remove             Remove organisation data and profiles
organisation.applications.remove     Uninstall organisation-deployed applications
organisation.credentials.revoke      Invalidate organisation credentials
device.factory-reset                 Fully reset an organisation-owned device
device.cryptographic-erase           Destroy encryption keys
```

## No generic remote shell

There is no operation that accepts a command, argv, script, or arbitrary path. `assert_within_boundary` matches shell-shaped names — shell, exec, command, run, script, bash, sh, powershell, cmd, ssh, python, eval, system — and refuses with an explanation.

Any optional remote command execution for advanced environments would need a separate design, strong authentication, off-by-default status, and exclusion from the stable consumer profile. None is designed and none exists.

`docs/NETWORK_SECURITY.md` already records the related constraint: remote Bunny access is postponed, and changing the app-server listen address is not an acceptable shortcut.

## Preconditions

Destructive operations require an explicit non-empty scope and a UUID audit correlation id before execution. `device.factory-reset` and `device.cryptographic-erase` additionally require an organisation-owned device, multi-factor administrator authorisation, and a disclosed prior policy. Where policy demands it, device-side confirmation is also required.

## Consequences are stated

`device.factory-reset` and `device.cryptographic-erase` return the data-loss consequences with the decision, including that locally stored recovery keys are destroyed and that encrypted data without an external key copy becomes unrecoverable. Both preserve the recovery environment so the device stays reinstallable.
