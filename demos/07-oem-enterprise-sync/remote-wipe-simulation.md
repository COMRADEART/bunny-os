# Remote wipe boundaries

```text
python -c "import json, enterprise.remote as r; print(json.dumps(r.describe_operations(), indent=2))"
make test-remote-wipe
```

Show the five distinct wipe operations, from removing organisation data to cryptographic erase, and that they are separate so an administrator cannot reach for the largest hammer when they meant the smallest.

Refusal:

- `device.factory-reset` on a `personally-owned` device: refused. A personally owned device is never fully wiped remotely.
- `device.factory-reset` with no prior policy declared: refused.
- The same with `single-factor` authorisation: refused.
- The same with no audit correlation id: refused, because destructive operations require audit evidence before execution.
- `organisation.data.remove` where policy requires device-side confirmation and none was recorded: refused.
- Any operation named `device.shell`, `run.command`, or `exec.script`: refused with the message that Bunny OS provides no generic remote shell.

Then authorise a fully compliant organisation-owned reset and show the returned data-loss consequences, including that locally stored recovery keys are destroyed and that the recovery environment is preserved.

Nothing is wiped. No executor exists.
