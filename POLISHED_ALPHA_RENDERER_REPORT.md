# Polished Alpha: companion rendering modes

What this phase changed, what it measured, and what it deliberately did not do.

The brief asked for a three-mode companion with pre-rendered as the default, an
idle companion that costs nothing, renderer switching that does not disturb the
AI session, and graceful fallback. Most of the architecture it describes was
already here. This phase added the parts that were not, corrected one thing the
repository had backwards, and measured the result.

---

## 1. What already existed

Worth stating first, because it determined how much was written rather than
rebuilt:

| Brief section | Already implemented |
|---|---|
| §2 renderer abstraction | `CharacterRenderer` ABC with static, frame-sequence and 3D implementations |
| §2 semantic states | `CharacterState` — 27 states, priority-ordered, with per-state fallback chains |
| §7 state machine | `companion/states.py` — a transition *table*, not an `if` chain |
| §11 hardware detection | `companion/hardware.py` — hardware facts and operational probes kept separate |
| §14 permission UX | `trust/explain.py` — "Allow once" / "Allow while using" / "Always allow" / "Don't allow" |
| §15 fallback ladder | `AdaptiveRendererSelector` — hysteretic degradation, 3D → 2D → static → text |
| §16 switching | `CharacterRendererController` already swapped renderers preserving scale, position and bubble |

None of it was replaced.

---

## 2. The thing that was backwards

`POLICY_LADDER` started at `full-3d`. Every machine that could hold a GL context
selected the 3D character package on first boot. The brief says pre-rendered is
the default, and the repository did the opposite.

The fix is not a reordering of that ladder — the ladder is correct as a
*capability* ladder. What was missing was a second value: **which companion the
user asked for**, separate from **how much the machine can draw**.

```
RenderMode (a choice)          Presentation (a capability rung)
  prerendered  ──ceiling──▶      animated-2d
  2d           ──ceiling──▶      animated-2d
  3d           ──ceiling──▶      full-3d
```

Collapsing the two fails on the first machine that degrades: a user who chose 3D
and lost their GPU context would have had their *choice* rewritten to 2D by the
degradation, with nothing to restore it when the context came back. The mode is
what the person asked for and only a person changes it; the rung is what the
machine can currently honour.

**Measured effect.** On a machine reporting `eligible=full-3d`:

| mode | package selected | rung |
|---|---|---|
| *(before this phase)* | `bunny-default-3d` | full-3d |
| `prerendered` (new default) | `org.bunny-os.default-bunny` | animated-2d |
| `3d` | `bunny-default-3d` | full-3d |

The decision also records *why*, so a user asking why they are not seeing the 3D
Bunny is told it was a setting rather than their hardware.

---

## 3. New code

| File | What it is |
|---|---|
| `companion/character/modes.py` | The three modes, their ceilings, their fallback chains, the performance→frame-cap map |
| `companion/character/procedural_renderer.py` | `Procedural2DRenderer` — the interactive 2D renderer |
| `companion/character/quiescence.py` | When the companion stops drawing, and the states in which it never may |
| `scripts/renderer_mode_measure.py` | §12's measurements (`make companion-renderer-measure`) |
| `tests/companion/test_renderer_modes.py` | 57 tests |

### The interactive 2D renderer

Pre-rendered answers "which frame is this state" by looking it up. The
interactive renderer *solves* for it: each state names a target pose, and what
is drawn is the current pose easing toward that target plus continuous motion.

This is why it exists as a separate renderer rather than a mode of the frame
player: a frame sequence can only cross from `thinking` to `success` if somebody
drew that crossing, and 26 states is 650 ordered pairs nobody will author.
Easing produces all of them.

Nine normalised pose channels leave through `RenderedFrame.pose` (an optional
field — renderers that have nothing to say there still serialise exactly as
before). It opens no GL context and decodes one image, so `controller.py` can
import it without pulling a graphics library into every text-only client.

### Quiescence

The brief's "reduce processing as much as possible when idle" is not satisfied
by a low frame rate — a companion looping at 12 fps still wakes twelve times a
second forever. So the policy **stops**:

```
ACTIVE  ──8s idle──▶  DROWSY (8 fps)  ──6s──▶  QUIESCENT (no timer)
```

`frame_rate_cap == 0` is the load-bearing value: it means *cancel the timer*,
not "as slow as possible". The important half is `NEVER_QUIESCENT` — approval,
error, blocked, warning, waiting-for-user, listening, transcribing, speaking. A
companion that froze while asking permission is exactly the failure §15 names,
and a test asserts every one of those states still draws after a simulated hour.

---

## 4. Measurements

`make companion-renderer-measure`, run on the reference target (Fedora 44, as
`bunny`, on ext4), all three modes in one process so the figures are comparable:

| mode | renderer | startup | decoded images | frame compute (median) | idle-minute compute |
|---|---|---|---|---|---|
| **prerendered** | `animated-2d` | **0.14 ms** | 468 KiB | **0.0019 ms** | **1.7 ms** |
| 2d | `interactive-2d` | 0.12 ms | **36 KiB** | 0.0388 ms | 33.9 ms |
| 3d | `full-3d` | 41.40 ms | 277 KiB | 0.3298 ms | 288.2 ms |

Renderer switching: **0.056 ms** median, 0.084 ms p95, session preserved.

Reading these:

- **3D startup is ~296× pre-rendered's.** This is the number behind §9's "do not
  make the user wait for heavy graphics systems" at first boot.
- **Pre-rendered costs ~170× less compute over an idle minute than 3D**, and
  ~20× less than interactive 2D.
- **Pre-rendered loses on memory** — 468 KiB against 36 KiB — because it holds
  every decoded frame where the interactive renderer holds one. The default
  trades half a megabyte of RAM for two orders of magnitude of CPU wakeups,
  which is the right trade on battery-powered hardware, but it *is* a trade and
  the report says so rather than claiming pre-rendered is cheapest outright.

### Caveats stated where they matter

- The 3D figures are **llvmpipe** — software rasterisation under WSL2. They are
  pessimistic against real hardware and must not be quoted as GPU numbers.
- Frame time is time to **compute** a frame, never to present one. Presenting
  needs a compositor.
- Idle cost is reported as *ticks that drew*, not a CPU percentage: a percentage
  measured over a synthetic clock measures the harness, not the companion.
- `ticksThatDrew` is identical across modes by design — quiescence sits above
  the renderer. Equal counts there are **not** evidence that two modes cost the
  same, and the JSON says so in the output rather than only here.

### Not measured

Named rather than omitted, and emitted as `NOT_RUN` with a reason: boot time
(needs a booted image), idle GPU (nothing here touches a GPU), desktop
responsiveness (needs a compositor and a session).

---

## 5. Defects found and fixed

Five, four of them mine, found by measuring and by running on Linux:

1. **The idle oscillator was an integrator.** The breathing sine was added into
   the stored pose channel each tick, so every tick eased from an
   already-displaced value and displaced it again. An idle character drifted to
   ~8× the intended amplitude and stayed there. The breath is now a displacement
   applied when the frame is built and never written back.
2. **The first frame was always neutral.** A companion appearing in an error
   state rose out of a neutral pose; one quiesced before its first tick stayed
   neutral. The first draw now snaps to the target.
3. **Switching mode lost the user's scale.** `set_mode` unloaded and nulled the
   renderer, so the swap path saw no predecessor and could not carry scale,
   opacity or placement across. §16 says only the presentation layer changes.
4. **The controller's default mode silently capped 3D.** Making pre-rendered the
   *controller's* default capped every caller that had a capability plan
   permitting 3D and had never heard of modes — including the 3D slice whose
   entire job is to draw 3D. **Found only on Linux**, which runs the GL tests
   Windows skips. The mode ceiling is now opt-in (`mode=None` means no ceiling);
   the product default lives in settings and the character policy, where policy
   belongs.
5. **The viseme table was invented.** My first `_VISEME_OPENING` used plausible
   phoneme names (`aa`, `mbp`, `fv`) that the real `MouthShape` enum does not
   contain, so every viseme would have rendered as a closed mouth. A test now
   iterates the enum and asserts each member is mapped.

Two states — `SLEEPING` and `GREETING` — were in the enum, the priority order,
every fallback chain and the package contract, with **nothing anywhere able to
produce them**. Both now have inputs (`dormant`, `greeting`), and a test asserts
neither can mask an approval, an error or a live microphone.

---

## 6. Verification

| target | tests | failures | note |
|---|---|---|---|
| Windows baseline (before) | 2013 | 3 | evidence-tree bookkeeping, TTS provenance, a shell test's encoding |
| Windows (after) | 2072 | 3 | same three |
| Linux baseline (before) | 2028 | 4 | the three above minus one Windows-only, plus two CLI-slice failures |
| Linux (after) | 2087 | 4 | **same four** |

Zero regressions on either target. The Linux baseline was measured separately
and deliberately: Windows skips 65 tests Linux runs, so "it failed on Linux and
not on Windows" is not by itself evidence a change caused it — and in this case
two of the four Linux failures were pre-existing while one was genuinely mine
(defect 4 above).

Linux runs were performed as `bunny` from an ext4 clone. Running from `/mnt/c`
or as root produces false failures and is not the reference measurement.

---

## 7. What was deliberately not done

- **No AI motion system.** §6 asks the 3D renderer to be *designed* so one can
  be added; it already is (`three_d/procedural.py` sits behind the animation
  controller). Building it would be the feature explosion §20 forbids.
- **No new 3D work.** §20 ranks 3D refinement eighth. 3D is unchanged.
- **No image build or VM boot.** Agreed at the outset. Boot time and desktop
  responsiveness are consequently unmeasured, and are reported as such rather
  than estimated.
- **No settings UI.** The mode is settable through the existing settings path
  (`bunny-os companion settings set character render_mode 3d`), which validates
  and persists it. A GNOME Shell panel for it is UI work, not architecture.

---

## 8. Open

- The two pre-existing Linux CLI-slice failures (steps 17 and 21, presentation
  pressure and hysteresis recovery) are untouched by this phase and unexplained.
  They predate it and should be diagnosed separately.
- `contextual_reactions` is enforced (`CharacterRendererController.look_at`
  returns `False` when it is off, and when the frame player is running, which
  cannot react), but **nothing routes pointer motion to the companion yet**. The
  gate is real and tested; the source of the events is not wired. That is a
  shell-side change, not a renderer one.
- 3D has been measured only on llvmpipe. A real GPU figure needs hardware this
  phase did not have.
