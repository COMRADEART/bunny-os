# Air-gapped policy bundle

```text
make test-airgap
python -c "import json, enterprise.airgap as a; print(json.dumps(a.describe_workflow(), indent=2))"
```

Walk the six stages: exported, transported, verified, applied, status-exported, status-imported. No cloud connection is used at any stage.

Refusal:

- Set `signatureVerified: false`: refused. There is no unsigned or "trusted local" import path, for any bundle kind.
- Replay a bundle whose sequence is not greater than the last applied: refused as stale policy replay.
- Present an expired bundle: refused.
- Sign with an `oem-` or `bunny-os-release-` key: refused, because offline management bundles accept only the `fleet-` namespace.
- Present a revoked `fleet-` key: refused.
- Skip the verification stage and go from transported straight to applied: refused.
