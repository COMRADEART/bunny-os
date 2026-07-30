# Privacy review

```text
python -c "import json, enterprise.health as h; print(json.dumps(h.describe_visible_fields(), indent=2))"
python -c "import json, sync.metadata as m; print(json.dumps(m.describe_visible_metadata(), indent=2))"
python -c "import json, sync.deletion as d; print(json.dumps(d.describe_all(), indent=2))"
make test-privacy-regressions
```

Show exactly what an organisation administrator can see: ten categorical fields, no free text, no counts, no durations.

Refusal:

- Add `prompts`, `memories`, `fileNames`, `browserHistory`, `applicationUsageDuration`, or `screenshot` to a health report: each refused by name.
- Add `hostname`, `username`, `email`, `macAddress`, or `serial`: refused, reusing `IDENTIFIER_KEYS` from `operations/redaction.py` so fleet health and diagnostic export share one definition of forbidden data.
- Add a behavioural attribute such as `productivityScore` to a fleet group: refused, so an administrator cannot rebuild a productivity metric from group membership.
- Add `userProductivity` as a pilot success criterion: refused; studying people needs a separate research protocol with consent.
- Claim "zero knowledge" for sync: refused, because operational metadata remains visible.
- Claim a deletion is "completely gone": refused, because backup copies may persist for up to 35 days.

Show the six deletion scopes and their disclosed retention delays.
