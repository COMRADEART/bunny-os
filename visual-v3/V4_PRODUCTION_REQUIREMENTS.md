# V4 production requirements

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

What a production Bunny shell would need that V3 does not have. Ordered so that
the items which could still invalidate the whole direction come first.

## 0. Re-run the framework decision with the accessibility answer in hand

V3 selected Smithay on a narrow margin over wlroots, and Smithay scored *worst
of every candidate* on inherited accessibility. That was acceptable for a
prototype whose job was to find out whether the accessibility route exists at
all. It is not automatically the right answer for production.

V4 should re-open the choice if a real assistive-technology session shows the
GTK-client route is insufficient. In that case libmutter becomes the strongest
candidate — and V3 established that libmutter genuinely supports downstream
shells, since gala, gnome-kiosk and lumina-desktop all link it.

**Deliverable:** a decision review, not an assumption that V3's choice stands.

## 1. Prove accessibility before anything else

Nothing else in this list matters if a screen-reader user cannot use the shell.

- Run Orca against every surface — top bar, dock, launcher, palette, Quick
  Settings, notifications, assistant, approvals, overview, lock screen — on real
  hardware, and record what it reads.
- Implement `zwp_input_method_v2` and test an on-screen keyboard and a CJK input
  method.
- Implement magnification.
- Exercise sticky keys, slow keys and mouse keys on a real libinput seat.
- Re-run the V2 contrast audit against the V3 chrome.
- Commission an independent accessibility review, as earlier phases did.

**Gate:** no accessibility claim may be made from inference again.

## 2. A real session backend

- **DRM/KMS output** with `libseat` session management, replacing the nested
  winit backend.
- **libinput seat** for real keyboards, touchpads, touchscreens and the
  accessibility keyboard features that live there.
- **Page-flip-driven pacing.** V3 measured that a nested compositor must not
  rate-limit its own loop; on hardware there is no host to pace against, so the
  page-flip event becomes the clock. This is new code with no V3 equivalent.
- **Damage tracking.** V3 redraws the entire output every frame. Production must
  use `OutputDamageTracker` so an idle desktop costs nothing.
- **Multi-GPU handling.** V3 assumed one renderer.

## 3. Screen capture, which is currently impossible

Smithay 0.7 ships no screencopy implementation. V4 must either implement a
capture protocol against the compositor's renderer, contribute one upstream, or
select a framework that has one. Until then there is no screen sharing, no
screenshots through the portal, and no remote support.

**This is the single largest functional gap and it has no workaround.**

## 4. Resident shell chrome

V3 spawns a process per panel and pays ~3.2 s per panel. Production must keep the
chrome resident and toggle visibility, which also removes the `LD_PRELOAD`
re-execution. Expect a rewrite of the component entry points, and consider a
compiled chrome (Rust + GTK 4) rather than PyGObject for start-up cost.

## 5. Security work V3 deferred

- **Authenticate layer-shell namespaces** with `wp_security_context_v1`, so a
  client cannot claim to be the Bunny top bar.
- **Connect the approval backend.** V3 tested the approval state machine, not the
  real backend.
- **Implement the PAM helper.** V3 defines the boundary and deliberately returns
  `HELPER_UNAVAILABLE`.
- **Re-evaluate `ext-foreign-toplevel-list`** once security contexts exist; the
  dock and the overview both want it.
- **Threat-model XWayland** before enabling it, using the six recorded
  consequences as the starting point.

## 6. XWayland, if the ecosystem requires it

V3 proved the shell starts without it, which was the requirement. Production must
decide whether X11 support is needed at all; if it is, it needs a real Xwayland
integration with window matching, clipboard bridging and the security review
above.

## 7. The compatibility matrix, actually run

Every toolkit in the phase brief — GTK 3, Qt 6, Electron, Chromium, Firefox, a
file manager, a code editor, a media player, Flatpak — on a host where they are
installed, across all nine dimensions rather than one.

## 8. Multi-display on hardware

The full matrix from `MULTI_DISPLAY_REPORT.md`, including hotplug while locked,
mixed DPI, portrait secondaries, and cursor movement across scale boundaries.

## 9. Qualification, if it ever ships

A production shell would enter the same qualification ladder as the rest of Bunny
OS: reproducible builds, installed-system qualification, display-stack
reliability, first-login, encrypted unlock, physical hardware and accessibility
evidence. **None of that has begun**, and none of it may begin from this branch.

## What V3 hands over that is worth keeping

- The window, workspace, focus, output, session-lock and security policy modules,
  which are pure logic with 86 passing tests and no dependency on the backend.
- The character policy, which is structural rather than checked.
- The bounded restart supervisor, measured against a real SIGKILL.
- The session-isolation gates and the tests that keep the qualified image
  untouched.
- The measurement harnesses, including the guards that refuse to report a failed
  measurement as a negative result.
