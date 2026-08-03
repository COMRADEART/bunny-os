# Known limitations

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

Ordered by how much they would matter to a person using this as a desktop.

## Blocking for any real use

**No input method.** `zwp_input_method_v2` is not implemented. There is no
on-screen keyboard and no CJK, Japanese or Korean input. This is simultaneously
an accessibility blocker and an internationalisation blocker, and it is the most
serious single omission in the phase.

**No screen sharing.** Smithay 0.7 implements no screencopy protocol at all, so
there is no compositor capture path to hand to PipeWire and the ScreenCast
portal has nothing to talk to. Video calls do not work. This is a framework gap,
not a Bunny decision, and it is the reason no Bunny portal backend was written.

**No XWayland.** V3 resolves XWayland *state* — requested, available,
unavailable — but never starts an Xwayland server. No X11 application can run.
`xterm` was launched against the shell and did not map, which is the correct and
expected result. The shell started fine without it, which was the property being
tested.

**No pointer constraints.** `zwp_pointer_constraints_v1` is available in Smithay
but not wired up, so pointer lock and confinement do not work. Games and 3D
applications will misbehave.

**No hardware acceleration was exercised.** Every measurement was taken on Mesa
llvmpipe, a software rasteriser, inside WSL2. No DRM/KMS path, no GPU, no
`linux-dmabuf`, so no hardware video decode.

## Unverified rather than broken

**Accessibility is inferred, not observed.** No Orca session was run. The
architecture is sound — the chrome is GTK, so it carries AT-SPI — but "sound
architecture" is not "a screen reader read it". See `ACCESSIBILITY_MODEL.md`.

**Multi-display was never exercised.** The nested backend has exactly one
output. Everything in `MULTI_DISPLAY_REPORT.md` beyond the single-output case is
the layout *model* verified by unit tests, not the hardware path.

**Session locking was never performed end to end.** The protocol is implemented
and advertised, the lock client is written, and the state machine is tested in
both Rust and Python. But no PAM service was configured, so no session was
actually locked and unlocked. `AuthenticationHelper` returns
`HELPER_UNAVAILABLE` by design rather than pretending.

**Most of the application ecosystem is untested.** Qt, Electron, Chromium,
Firefox, a file manager, a code editor, a media player and Flatpak were not
installed on the measurement host. Only GTK 4 applications and one terminal were
run.

**Eight of nine compatibility dimensions were not measured.** Input, resizing,
clipboard, scaling, dialogs, portals, notifications and screen sharing each need
a facility the measurement environment lacked. Only "launches" was measurable.

## Architectural costs accepted

**Chrome start-up is slow.** Each panel is a separate process: Python
interpreter, PyGObject import, an `LD_PRELOAD` re-exec for gtk4-layer-shell, GTK
init, then a surface. That is ~3.2 s per panel on this host against a 150 ms
target. The target assumes resident chrome; V4 must keep panels running and
toggle visibility rather than spawning them.

**`wlr-layer-shell-v1` is not a stable protocol.** All Bunny chrome depends on
it. It is the de-facto standard and widely implemented, but it is not `ext-`.

**Layer-shell namespaces are self-asserted.** A client can claim
`bunny-top-bar`. V3 limits the damage — an unrecognised namespace gets no
exclusive zone and no privileged role — but does not authenticate the claim.

**The compositor cannot pace itself.** In a nested run the host's frame callback
paces it. Every attempt to add a second rate limit killed the host connection
within a second, measured repeatedly. On DRM/KMS there is no host, so V4 must
drive pacing from the page-flip event.

**Clients do not survive a compositor restart.** A Wayland client connects to
the compositor's socket; when the compositor dies, so does the client.

**No damage tracking.** The compositor redraws the whole output every frame.
`OutputDamageTracker` is constructed but not used to skip unchanged regions.

## Deliberately not done

**No Bunny portal backend.** xdg-desktop-portal-gtk already handles consent
correctly and V3 found no Bunny-specific requirement it cannot meet.

**`wlr-data-control` is off.** It grants unrestricted clipboard read to any
client that binds it, with no consent step.

**`ext-foreign-toplevel-list` is off.** It lets any client enumerate every
window; it wants a security-context restriction first.

**Sensitive-clipboard clearing is off.** Silently emptying a clipboard loses
data the user expected to keep.

**No private Wayland protocol.** Every interface the shell speaks is a standard
one.

## Measurement-environment caveats

The nested backend contends with the host compositor, and a compositor start can
lose that race. Two harness runs produced "the measurement did not happen"
results that were environmental, not defects — the harness reports them as
unavailable rather than as protocol absence, which is the behaviour that matters.
Running the harnesses sequentially, with the previous compositor fully stopped,
removed the flakiness.
