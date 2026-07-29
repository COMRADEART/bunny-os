# OEM profile validation and image build

```text
python oem/bin/bunny-oem --json validate-profile --profile oem/profiles/example-validated-integrator.json
python oem/bin/bunny-oem --json validate-overlay --overlay oem/overlays/example-nimbus-overlay.json
make build-oem-image
```

Show `accepted: true` and the list of checks performed.

Refusal: copy the profile, delete the `signature` block, and re-run. The verdict becomes `accepted: false` with `unsigned profile` and exit code 2. Then set `branding.claimsOfficialBunnyOsDevice` to `true` and show that the claim is refused because the programme level does not permit it and no signed qualification report was supplied.

`make build-oem-image` validates inputs and states plainly that no image was produced. Set `FULL_GATE=1` only on the documented Fedora 44 image-builder host.
