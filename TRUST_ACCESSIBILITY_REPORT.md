# Accessibility — the Companion, the Trust prompt and the task workspace

**Date** 2026-08-10 · **Commits** `fc1e58a`, `adce2c5`
**Status** Design and logic implemented and tested. **No assistive technology has
been used against any of it.**

§25's requirement is that the Companion *enhance* accessibility rather than become
another barrier. A character that narrates the system is a genuine opportunity for
a person who cannot read a dense settings page — and a genuine hazard if the
narration is the only route to something.

---

## 1. The decision that shaped everything else

**The non-graphical surface is the reference implementation, and the graphical one
is derived from it.**

The usual arrangement is the opposite: build a dialog, then add labels, then add a
screen-reader path. That produces a text mode with fewer facts than the picture,
and the gap is discovered by the person who depends on it.

Here, `trust/explain.py` builds one `TrustPrompt` containing every sentence in
final wording, plus a `spoken` field assembled from those same sentences.
`companion/trust_surface.py:prompt_lines()` renders it as text; the GTK dialog
renders the same list; the shell's `trustPrompt.js` orders the same fields and
uses `spoken` verbatim as its announcement. A test asserts the graphical surface's
source calls `prompt_lines`, and another asserts the spoken form contains the
headline, the capability note and every option label.

The consequence: a text-only Companion is not a degraded mode. It is the same
question.

---

## 2. §25's list, item by item

| Requirement | Status | Mechanism | Evidence |
|---|---|---|---|
| Keyboard-only use | **Implemented, tested** | `focusOrder()` defines Tab order; deny first, then allow options weakest-first, then the disclosure | `test_the_keyboard_starts_on_the_safe_option` |
| Screen readers | **Implemented, not validated** | One `spoken` string per prompt, one `announcement` per workspace change, both built in the layer that owns the words | `test_the_spoken_form_contains_every_fact_the_drawn_form_does`, `test_the_announcement_is_the_layers_own_spoken_string` |
| High contrast | **Implemented, tested** | `scrim: solid` at high contrast, not lighter; risk carries a *shape* as well as a colour | `test_the_scrim_gets_heavier_at_high_contrast_not_lighter`, `test_every_risk_level_has_a_token_and_the_dangerous_ones_have_a_marker` |
| Large text | **Implemented, partly tested** | `largeText` flows through both models; nothing truncates silently — a value longer than expected wraps | `buildPrompt`/`buildWorkspace` accept and propagate it |
| Reduced motion | **Implemented, tested** | Motion budget pinned to 0 ms; **fidelity unchanged** | `test_reduced_motion_stops_movement_without_lowering_the_picture`, `test_reduced_motion_removes_the_transition_and_not_the_rows` |
| Captions | **Pre-existing** | `companion/voice/captions.py`, unchanged by this phase | — |
| Visual alternatives to audio | **Pre-existing** | Notification layer, unchanged | — |
| Audio alternatives to visual | **Partial** | Every prompt and every workspace change has a spoken form; whether it is *spoken* is the pre-existing voice runtime's business | — |
| Text-only Companion mode | **Implemented, tested** | `textOnly` wins over everything, including a working graphical session | `test_a_text_only_preference_wins_over_a_graphical_session`, `test_text_only_is_honoured_over_everything` |

---

## 3. Five decisions worth stating

**Reduced motion is not a fidelity tier.** A person who asked for less movement
did not ask for a worse picture. `prefers-reduced-motion` sets the animation budget
to zero and leaves the character drawn and expressive in pose. Dropping such a user
to text would read the setting as a complaint about the character.

**Deny holds focus, and reading order is not focus order.** The eye reads the
options in escalating order — Allow once, Allow while using, Always allow, Don't
allow — and the keyboard starts on the safe one. A person who presses Return
without reading has denied something, which is recoverable; the opposite is not.

**Colour is never the only signal.** High and critical risk carry
`marker: true`, a shape beside the heading. A permission prompt is the worst
possible place for a colour-only distinction.

**Every future step is visible in the workspace.** All seven steps are drawn, the
unreached ones dim, so the progress is "3 of 7" rather than a spinner — for the
eye and for the announcement, which are the same string.

**A disabled Companion still delivers an attention state.** `presence: 'off'`
draws nothing, and `routeToNotification` is `True` when a question is outstanding.
A person who turned the character off must still be told the microphone was asked
for. Tested.

**A screen-reader user is not automatically a text-only user.** Many use one
alongside a visible desktop. `screenReader: true` forces announcement, not a
fidelity drop.

---

## 4. What has not been validated, and why that matters

**No assistive technology has been used against any of this.** Specifically:

* **Orca has not read a Trust prompt.** The `spoken` string is well-formed
  English; whether Orca announces it at the right moment, whether the modal
  raises correctly in the AT-SPI tree, and whether the announcement interrupts or
  queues are all unknown. This project's own record
  (`desktop-alpha-validation-state`) is that *nothing that had never been pressed
  worked* — and none of this has been pressed.
* **No keyboard navigation has been performed.** `focusOrder` is a list. Whether
  GTK gives focus in that order, whether Escape reaches the handler before the
  window manager, and whether Tab escapes the modal are unmeasured.
* **No contrast ratio has been measured for the new tokens.**
  `tokens.json` states the WCAG 2.2 AA thresholds and `tests/accessibility`
  measures the *existing* palettes. The new `risk`, `standing` and `companion`
  tokens are names that resolve to existing palette colours, so they inherit those
  ratios — but the *combinations* (a warning marker on a modal surface over a
  solid scrim) have not been measured.
* **No large-text or 200 % scaling pass.** Whether the prompt body wraps rather
  than clipping at 200 % is unknown.
* **The GTK dialog itself is untested.** `GtkConsentSurface.ask` needs a display.

**A specific hazard this phase introduces.** The Trust prompt is the only modal
Bunny raises unasked, and it appears at a moment when the person is doing
something else. If it does not raise correctly in the AT-SPI tree, a screen-reader
user gets a *silent modal* — an application that appears to hang. That is a worse
failure than any this phase fixes, and it is the first thing to check.

---

## 5. What to do, in order

1. **Boot an image, enable Orca, trigger one permission prompt.** Does it
   announce? Does it interrupt? Can it be answered from the keyboard alone?
   Everything else is secondary to this one.
2. **Keyboard-only pass:** Tab order, Escape, Return, and whether focus can leave
   the modal.
3. **Measure the new token combinations** against the 4.5:1 and 3:1 thresholds
   already in `tokens.json`, and add them to `tests/accessibility`.
4. **200 % text scaling** on the prompt and the workspace panel.
5. **Text-only Companion end to end**, with the text consent surface, in a real
   session rather than over a pipe.
6. Then fold the results into `ACCESSIBILITY_REPORT.md` and
   `reviews/accessibility/REQUEST.md`, which remains the route to an independent
   assessment.

Items 1–5 need the existing Fedora builder and a VM. None needs money or hardware.

---

## 6. Honest summary

The design takes accessibility as a starting constraint rather than a later pass,
and the one structural decision — the text surface is the reference — is the one
most likely to keep it that way as surfaces are added.

**None of it has been used by anybody, with or without assistive technology.** Every
row marked *tested* above is a test of a data structure. The accessibility gap
remains, as `NEXT_PHASE.md` says, the one that risks harm rather than merely
missing evidence, and this phase has not closed it.
