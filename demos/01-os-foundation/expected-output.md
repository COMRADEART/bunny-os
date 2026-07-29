# Expected output

- Version identifies OS 0.1.0, image/profile/source commit, contract 1.0.0, broker 0.1.0 and Bunny placeholder/verified status.
- Hardware states use detected/driver-available/driver-active/runtime-verified honestly; local model assessment says benchmark unverified.
- Broker invalid methods and unauthorized mutations fail with stable safe codes.
- Default firewall has no inbound ports; broker has no TCP listener; update timer/SSH/telemetry are off.
- Real signed update shows a new digest-pinned staged deployment and retains the previous one.
- Recovery runs without Bunny or cloud and requires explicit confirmation for mutation.
- Support output is a local 0600 archive owned by the authenticated requesting user, with no prompts/files/tokens.

Any deviation is a failed demo row, not an opportunity to reinterpret the expected result.
