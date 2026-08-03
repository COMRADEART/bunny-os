# V3 accessibility model

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## The headline

**No assistive-technology session was run, so no accessibility claim in this
phase is observed.** Orca needs a session bus, speech-dispatcher and audio; the
measurement environment had none of them. Every screen-reader statement below is
*inferred* from the toolkit, and is labelled as such.

`parity_claimable()` returns `false` and is asserted false by a unit test. It
stays false until real assistive-technology sessions pass.

## The architectural decision this phase turns on

A compositor is not an accessibility stack. On GNOME, AT-SPI reaches the shell
because GNOME Shell exposes its own UI through GTK/Clutter's accessibility
implementation. **A Smithay compositor inherits none of that.**

The consequence is blunt: *anything the compositor draws itself is invisible to a
screen reader.* There is no AT-SPI for pixels.

So V3 draws no chrome in the compositor. The top bar, dock, launcher, command
palette, Quick Settings, notification centre, assistant panel, approval cards and
lock screen are all GTK 4 clients on `wlr-layer-shell-v1`, and GTK carries their
accessibility. This is the single largest reason for that architecture — it is
not an aesthetic preference.

Had V3 taken the easier path of drawing the bar and dock inside the compositor,
the accessibility problem would have become unsolvable rather than merely hard,
and the honest verdict for this phase would have been worse.

## Assessed capabilities

Read from the compositor itself via `bunny-shell --accessibility`, so the
report cannot drift from the code.

| Capability | Mechanism | Evidence | Note |
|---|---|---|---|
| Screen reader reaches shell chrome | AT-SPI via GTK 4 layer-shell clients | **inferred** | The chrome is GTK and GTK exposes AT-SPI, but no Orca session ran |
| Screen reader reaches compositor-drawn surfaces | none | **unsupported** | No accessible representation exists; V3 avoids drawing chrome for this reason |
| Keyboard navigation of shell surfaces | GTK focus handling per client | **inferred** | Focus order is GTK's; the compositor guarantees only the two rules below |
| Visible focus indicator | Compositor focus policy plus GTK focus ring | **observed** | Single focus target, and focus changes no user action caused are refused |
| High contrast | GTK theme selection | **inferred** | Carried from V2 tokens; not re-measured against a contrast analyser |
| 200% scaling | `wp-fractional-scale-v1` plus GTK text scale | **observed** | 3840×2160 at scale 2.0 resolves to 1920×1080 logical; unit tested |
| Reduced motion | Compositor setting honoured by clients | **observed** | Returns a zero duration, not a shortened one |
| Sticky keys, slow keys, mouse keys | libinput and xkbcommon | **unavailable** | Seat-level features; the nested winit backend exposes no libinput seat |
| Magnification | Compositor output transform | **unsupported** | Modelled as a setting; the render path is not implemented |
| Accessible lock screen | GTK lock client over `ext-session-lock-v1` | **inferred** | It is a GTK client so it carries AT-SPI, but no AT session ran against a locked screen |

Three observed, four inferred, one unavailable, two unsupported.

## What was actually measured

- **The AT-SPI bus is reachable.** `org.a11y.Bus` was present on the session bus
  in the measurement environment. That proves the bus exists; it does not prove
  anything traverses it.
- **The chrome sets accessible labels.** 16 `AccessibleProperty.LABEL` calls and
  a live region on the lock screen's failure message, counted in source. That is
  evidence the labels were written, not that a screen reader read them.
- **Every dock item is keyboard reachable**, including overflow items — the tab
  order covers the full ordered list, not just the visible slice.
- **Passive chrome never requests the keyboard.** The top bar and dock declare
  `KeyboardMode.NONE`; only user-invoked surfaces (palette, launcher, approval
  panel, lock screen) take it.

## Two guarantees the compositor makes regardless of toolkit

1. **The guide character is never focusable.** It carries no controls, so
   focusing it would strand keyboard and screen-reader users on an element they
   cannot act on. Enforced twice: `ShellSurface::CharacterLayer.focusable()`
   returns false in the compositor, and the widget sets `can-focus` and
   `can-target` false so it is not in the focus chain at all.
2. **Nothing steals focus.** A notification, an assistant state change or an
   application requesting activation cannot move the keyboard. For a screen
   reader user, a stolen focus is not a minor annoyance — it silently relocates
   the reading cursor mid-sentence.

The character's accessible text is the *containing panel's state in words*
("Bunny is planning the next step"), so a screen-reader user loses no
information by not seeing the illustration.

## Gaps that matter, in order

1. **No input-method protocol.** `zwp_input_method_v2` is not implemented, so
   there is no on-screen keyboard and no CJK input. This is an accessibility and
   internationalisation blocker, not a cosmetic gap, and it is the most serious
   single omission in this phase.
2. **No assistive-technology session was run.** Everything about screen readers
   is inference.
3. **Seat-level accessibility features were never exercised.** Sticky keys, slow
   keys and mouse keys live in libinput; the nested backend has no libinput seat.
   These need a DRM/KMS session on real hardware.
4. **Magnification is not implemented.**
5. **High contrast was not re-measured** against a contrast analyser in V3.

## What V4 must do before any accessibility claim

- Run Orca against the shell, on real hardware, for every surface including the
  lock screen, and record what it reads.
- Implement `zwp_input_method_v2` and test an on-screen keyboard.
- Implement magnification.
- Exercise sticky/slow/mouse keys on a libinput seat.
- Re-run the V2 contrast audit against the V3 chrome.
- Have an accessibility specialist review the result, as the earlier phases did.

Until then, the correct statement is the one this document opens with: parity
with GNOME is not claimed and is not claimable.
