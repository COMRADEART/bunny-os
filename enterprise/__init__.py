"""Bunny OS device-side enterprise management.

This package is the *device* half of the optional organisation control plane. It
contains no server implementation: the fleet server, enrolment service, and
management console are separate trust domains with their own deployment
lifecycles and live outside this repository. See
``docs/adr/ADR-023-fleet-control-plane.md``.

Every module here follows two rules that the rest of the repository already
enforces:

* Typed operations only. There is no generic root execution path, no argv
  passthrough, and no remote shell.
* Fail closed. Unknown input is rejected rather than ignored, and absent
  evidence is never treated as success.
"""
