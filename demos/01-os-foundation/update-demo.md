# Update demonstration

The developer image should first show `updatesEnabled:false`/disabled configuration. For a disposable signed test channel, provision a test public key/config and run:

```text
bunny-os update check
bunny-os update stage
bootc status
```

Show manifest signature, sequence, architecture, contract, Bunny range, repository/digest and space checks, then a staged second deployment. A unit-test-only simulated stage is acceptable in a source demo but must be labelled simulation.

