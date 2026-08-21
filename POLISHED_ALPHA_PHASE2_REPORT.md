# Polished Alpha Phase 2: Companion Experience & Interaction

What changed, what was found, and what was deliberately left alone.

The brief asked for a coherent interaction loop rather than new subsystems. Most
of the machinery existed; the work was making it *reach the user*. Three of the
things this phase "added" were already written and simply had no caller.

---

## 1. Three subsystems that existed and did nothing

The most useful finding of the phase, and the reason it needed little new code.

| Subsystem | State before | State now |
|---|---|---|
| `character.dock` | validated, persisted, serialised — **read by nothing** | drives placement |
| `PositionStore` / `saved_from_decision` | fully implemented, atomic, display-aware — **no caller anywhere** | wired; position survives logout |
| Presenter construction from settings | window called `CharacterPresenter(root)` with **no arguments** | every persisted preference passed |

The consequence a user would have reported: *"it forgets where I put it, and the
settings page does nothing."* Both were true. The companion drew its defaults on
every login however the settings file read.

The tests for §7 are written against that observable shape — change a thing,
build a **second presenter over the same root**, expect the change to still be
there — because that is the only shape that catches a store nobody invokes.

---

## 2. Placement: one vocabulary instead of two that disagreed

`CharacterSettings.dock` accepted `top-left`, `top-right` and `center`. The
placement engine could express none of them. The engine offered `dock-left`,
`dock-right` and `compact-floating`; the settings field rejected all three. The
divergence had never been noticed because nothing consumed the setting.

Now one vocabulary — `Placement`'s — with the old names normalised for files
already on disk. `Placement` gained `TOP_LEFT` and `TOP_RIGHT` rather than the
alias table quietly folding them onto a bottom corner: they named positions a
user had asked for and the engine had always been able to compute.

§6's "Hidden" is a separate flag rather than a placement value, so a user who
hides the companion and shows it again gets it back where they left it.

---

## 3. The attention model, and why it is not new states

§2 asks for a centralized attention model and forbids a second state system.
`companion/character/attention.py` is therefore a **pure projection over
`CharacterState`** — no state, no decisions about what happens next — that
answers §2's five questions *together*, in one `AttentionDecision`. Asking them
separately is what lets a surface be invisible and animating at once.

`ATTENTION` and `AVAILABLE` are the two distinctions the character vocabulary
genuinely lacked:

| | meaning |
|---|---|
| `IDLE` | nothing happening, nobody here |
| `AVAILABLE` | nothing happening, Bunny can be asked |
| `ATTENTION` | somebody is engaging, **microphone not open** |

`ATTENTION` is a *level*, not a `CharacterState`, and that was forced by
evidence rather than taste: adding it to `REQUIRED_CHARACTER_STATES` obliges
every bundled package to gain a `stateMap` entry (a test requires the bundled
manifest to map every required state), which changes the package digest — and
that digest is recorded in `qualification/public-alpha/gate-vm-*.json`, evidence
taken from a real VM boot that cannot be regenerated without another one. Ten
states' worth of vocabulary is not worth invalidating a boot's evidence.

---

## 4. Invariants, asserted exhaustively

`tests/companion/test_interaction_invariants.py` enumerates every phase against
every on/off combination of the eight client flags, and asserts inside the loop.
§4's six prohibitions are covered, plus §12, §13 and §15:

- permission cannot be skipped, masked, or looped away
- `completed` is reachable **only** from `presenting`; only the `success` phase
  can render as success
- a live microphone always wins; `listening` is never shown without one
- no flag combination lowers urgency below a security-critical phase
- every non-terminal task state can reach a terminal one (breadth-first over the
  real transition table)
- nothing can be invisible and animating, or urgent and quiescible
- the two independently maintained "when may it freeze" lists are cross-checked
  against each other rather than kept in step by hand

---

## 5. Defects found

Five, and the two most interesting were caused by this phase.

1. **A live microphone could be invisible.** The mapper gated `listening` behind
   `_REFINABLE_PHASES`, so a client whose runtime had gone away rendered as
   `disconnected` while its microphone was still open — a person being recorded
   with nothing on screen saying so. Promoted to an always-permitted upgrade,
   ranked below approvals and errors so it still cannot take the surface from a
   question.

2. **A shadowed function would have silently disabled accessibility.** I added a
   `_character_preferences` to `gtk_shell.py`; one of that name already existed,
   translating accessibility preferences. Mine shadowed it, and because mine
   catches every exception the accessibility preferences would have become `{}`
   — taking reduced motion and high contrast with them. Renamed, with a test
   pinning it.

3. **The first-run greeting broke the vertical slice.** Constructing the
   greeting unconditionally meant every fresh directory looked like a first
   boot, so the slice opened on `greeting` and failed its step 4 asserting a
   static idle state. **This is the Phase 1 mistake repeating**: a mechanism
   quietly asserting a product policy breaks every caller that only wanted the
   mechanism. Greeting is now opt-in and the session launcher turns it on — the
   same shape as the renderer-mode fix a phase earlier.

4. **Animation intensity erased expression.** `procedural_renderer`'s docstring
   promised intensity 0 "still changes expression enough to be readable"; the
   code exempted only `eye_open`, so at intensity 0 a success, an error and a
   permission request wore an identical flat brow — the three states §7 says a
   user must never have to guess between, made indistinguishable in exactly the
   configuration a motion-sensitive user would choose. Expression channels are
   now exempt; only the body and its motion scale.

5. **My own test had the microphone ordering backwards.** It asserted
   `transcribing` outranks `listening`. The existing order is right and the
   reason matters: `listening` means the microphone is open *now*, and the live
   device is the privacy-critical fact.

---

## 6. §18 — the two unexplained Linux failures

**Investigated first, as instructed, and not fixed.**

They are genuine baseline failures — present with no Phase 1 or Phase 2 changes
— and they are **intermittent**, which is a different classification from what
Phase 1's report implied:

| evidence | result |
|---|---|
| warm baseline runs | **0 / 6** reproduced |
| cold-clone runs (fresh clone, caches dropped) | **1 / 3** reproduced, on attempt 1 |
| the slice run standalone | **0 / 4** — passes every time |
| the module run alone | **0 / 4** — passes every time |

Roughly 2 in 12 baseline runs, always on a *first* run. The slice waits on a
real clock for the runtime to come up; on a cold start that wait expires and the
steps after it are evaluated against a task that had not got where the slice
thought.

This is independently corroborated by the measurement harness: **the first
measurement in every batch is 2–3× slower than the ones that follow** (§7's
control table below shows 0.0043 ms then 0.0017 ms on the *same tree*).

Classification: a harness timing sensitivity in the slice's real-clock waits,
not a product defect, and it does not touch the companion experience. Left
alone, with the baseline classification preserved.

---

## 7. §16 — measurements, and a control that changed the conclusion

First re-measurement after Phase 2 came out roughly **double** Phase 1's
figures. Rather than report a regression, the Phase 1 tree was measured
**interleaved with** the Phase 2 tree, same machine, same minute:

| tree | prerendered | 2d | 3d (frame / startup) |
|---|---|---|---|
| phase 1 (first in batch) | 0.0043 ms | 0.0735 ms | 0.6221 ms / 72.6 ms |
| phase 2 | 0.0019 ms | 0.0388 ms | 0.3314 ms / 38.1 ms |
| phase 1 again | 0.0017 ms | 0.0383 ms | 0.3347 ms / 45.2 ms |
| phase 2 again | 0.0020 ms | 0.0369 ms | 0.3252 ms / 37.2 ms |

Warm, the two trees are identical. **Phase 2 changed no performance
characteristic**, and the apparent doubling was host load — a session's worth of
suites and clones. The absolute figures are not comparable across days; only
interleaved ones are.

Final figures (Fedora 44 under WSL2, as `bunny`, on ext4; 3D on llvmpipe and
therefore pessimistic):

| mode | startup | decoded | frame | idle-minute | transition | permission |
|---|---|---|---|---|---|---|
| **prerendered** | 0.21 ms | 468 KiB | 0.0019 ms | 1.7 ms | 0.040 ms | 0.040 ms |
| 2d | 0.12 ms | 36 KiB | 0.0388 ms | 33.9 ms | 0.047 ms | 0.046 ms |
| 3d | 38.06 ms | 277 KiB | 0.3314 ms | 289.6 ms | 0.340 ms | 0.338 ms |

Renderer switch: **0.055 ms** median, 0.077 ms p95, session preserved.
Attention projection: **0.0023 ms** per frame.

These match Phase 1's original report to the fourth decimal, which is the
strongest available evidence that nothing regressed.

---

## 8. Verification

| target | tests | failures |
|---|---|---|
| Windows | 2146 | 3 — all pre-existing |
| Linux (`bunny`, ext4) | 2161 | 2 — both pre-existing |

Zero regressions on either target. 155 tests added across three modules.

---

## 9. Deliberately not done

- **No new AI capability, plugin surface, procedural motion or 3D redesign** —
  §19.
- **No image build or VM boot.** Boot time and desktop responsiveness remain
  unmeasured and are emitted as `NOT_RUN` with reasons rather than estimated.
- **No settings UI.** Every preference is settable and validated through the
  existing path; a GNOME Shell panel is UI work, not architecture.
- **The permission prompt was not rewritten.** `trust/explain.py` already
  produced what/why/scope with the required vocabulary and says so explicitly
  when a reason is unknown. §12 asked for polish and synchronisation, and what
  was missing was the *assertion* that the companion state and the prompt cannot
  diverge — both derive from one projection, and a test now says so.

---

## 10. Open

- `look_at` is gated, tested and reachable, but **nothing routes pointer motion
  to the companion yet**. The gate is real; the event source is shell-side work.
- 3D has still only been measured on llvmpipe.
- The two intermittent slice failures remain, classified and documented above.
- Both phases are uncommitted in the working tree.
