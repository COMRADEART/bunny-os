# Policy application and conflict explanation

```text
python -c "import json, enterprise.policy as p; print(json.dumps(p.describe_domains(), indent=2))"
make test-policy
```

Show the 15 managed domains, each bound to exactly one typed operation.

Refusal:

- Require encryption: accepted.
- Attempt `domain: os.update.signature-verification`: refused as a safety invariant, at any enforcement level.
- Attempt `domain: bunny.memory.expose-to-organisation`: refused.
- Put `{"command": "/bin/sh"}` in `desiredState`: refused as an execution channel.
- Put an `apiKey` in provider policy: refused, because policy references a credential *source*, never a value.
- Set `maximumCapability: full-requested` with no plugin allowlist: refused, because capabilities are never granted silently.

Then resolve a conflict where the user prefers encryption off and the organisation requires it on. Show the winning layer, the owner, and the explanation the settings surface displays. Show that a tie inside one layer is refused rather than resolved arbitrarily.
