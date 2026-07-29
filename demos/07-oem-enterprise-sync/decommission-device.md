# Device decommissioning

```text
make test-decommission
python -c "import json, enterprise.decommission as d; print(json.dumps(d.lost_device_response(stolen=True), indent=2))"
```

Show the six scenarios and their required action sets. Note that personally owned unenrolment requires no wipe: the organisation withdraws its own footprint and nothing more.

Refusal:

- Record a decommission with only the certificate revoked: reported incomplete, with `rotate-sync-keys` and the rest still outstanding. Partial decommissioning is the common real-world failure and is treated as failure here.
- Record `full-reset` on a personally owned device: refused.
- Record a reset with `recoveryPreserved: false`: refused, because a wiped device must stay reinstallable.
- Omit the audit correlation id: refused.

For a stolen device, show the response sequence and its honest guidance: LUKS credentials still protect stored data, rotating sync keys protects objects uploaded after revocation, and objects already downloaded cannot be retracted.
