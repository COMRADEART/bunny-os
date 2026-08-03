# Protocols

> BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
> DEFAULT SESSION

This directory is empty of protocol XML on purpose.

**Bunny defines no private Wayland protocol in V3.** Every interface the shell
speaks is a standard one, implemented by Smithay and re-exported from
`wayland-protocols`, `wayland-protocols-wlr` or `wayland-protocols-misc`. A
private protocol would mean every Bunny shell component became unusable outside
Bunny, and would put Bunny in the position of maintaining an interface
contract — a cost worth paying only for a capability no standard protocol
covers, and V3 found no such capability.

Shell components communicate with the compositor through `wlr-layer-shell-v1`
and with the rest of the system through D-Bus, both of which are existing,
documented interfaces.

The measured protocol matrix — what is implemented, inherited, partial or
absent, verified by running `wayland-info` against the compositor — is in
`visual-v3/PROTOCOL_SUPPORT.md`.

Should V4 need a Bunny-specific interface (the most likely candidate is a
privileged channel for approval surfaces that must not be impersonable by an
ordinary client), the XML belongs here and the security review belongs in
`visual-v3/SECURITY_MODEL.md`.
