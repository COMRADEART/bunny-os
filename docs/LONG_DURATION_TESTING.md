# Long-duration testing

The catalogue defines 24-hour idle, 72-hour idle, 24-hour normal use, repeated suspend/resume, network loss, application/Bunny lifecycle, update checks, local-model start/stop, and login/logout. Each run pins candidate hash, machine/VM, workload, start/end time, power state, network faults, crash/OOM/storage events, and logs.

`make long-run-tests` validates plans only; it never converts a short host run into soak evidence. A scenario may say PASS only after its minimum duration and evidence bundle complete. All current scenarios are `NOT_RUN`.
