# Broker demonstration

```text
bunny-os --json status
bunny-os-info --json
bunny-os doctor
```

Show `/run/bunny/broker.sock` is Unix-only, then send an invalid `root.shell` request using the test fixture and show `unknown_method`. Attempt an authorized mutation from an inactive/unauthorized user and show the safe `unauthorized` response. Journald should contain UID/PID/request ID/method/outcome but no params or tokens.

