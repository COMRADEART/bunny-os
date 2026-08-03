# Compositor framework decision

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## Decision

**Smithay** (Rust) is selected for the V3 feasibility prototype.

This is a decision for a *prototype*, and it is deliberately reversible. It is
not a commitment that Bunny OS will ship a Smithay compositor. Section
"What would overturn this decision" states the conditions under which V4 should
reopen the choice.

## Evidence basis

Facts below are labelled:

- **observed** — measured on the V3 builder on 2026-08-03 and recorded in
  `visual-v3/reports/framework-survey.json`;
- **documented** — taken from upstream project documentation, not measured here;
- **inferred** — a judgement drawn from observed and documented facts.

Environment for the observed facts: Fedora Linux 44 on WSL2, kernel
6.18.33.2-microsoft-standard-WSL2, rustc 1.97.1, dnf5 5.4.1.0.

## Candidates evaluated

### Smithay — selected

- **observed** Published on crates.io with 13 released versions, none yanked.
- **observed** Builds against the Fedora 44 system Wayland, xkbcommon, libinput,
  udev, libseat, gbm, EGL, GLES, pixman and DRM development packages; the V3
  compositor in `compositor/bunny-shell/` compiles and runs against it.
- **documented** A *library*, not a compositor. It provides protocol
  implementations, a rendering abstraction, backends (winit, udev/DRM) and
  window-management primitives; the consumer writes the shell policy.
- **documented** Used by shipped compositors including Cosmic and Niri, so the
  library-consumer path is a supported use, not an experiment of ours.

Why it fits Bunny OS:

1. **It is composed, not forked.** The instruction not to fork or rewrite a
   compositor is satisfied structurally: Bunny writes shell policy and consumes
   protocol implementations as a dependency, which keeps upstream security fixes
   arriving through a normal dependency bump.
2. **Memory safety on a high-value surface.** A compositor holds every keystroke,
   every frame and the lock-screen boundary. Rust removes the memory-corruption
   class from Bunny's own shell policy code. This does not extend to the C
   libraries underneath it (Mesa, libinput, xkbcommon), and the security model
   states that limit explicitly.
3. **Bunny already owns its policy layer.** The V2 work established that Bunny's
   value is in mode control, approvals and privacy indicators, not in window
   management. Smithay lets Bunny own exactly that layer.
4. **The privilege boundary is ours to draw.** Smithay does not impose a session
   or authentication model, so the V3 rule that the compositor never validates
   passwords and never decides approvals can be enforced at the source level.

Costs accepted:

- **inferred** Smithay carries the least shell-adjacent code of the candidates,
  so Bunny implements more itself — every protocol beyond the core set is work
  Bunny schedules and maintains.
- **observed** No accessibility architecture is inherited. See
  `ACCESSIBILITY_MODEL.md`; this is the prototype's weakest area and the honest
  reason V3 cannot claim GNOME parity.

### wlroots — strong second

- **observed** Packaged in Fedora 44 as `wlroots` / `wlroots-devel` 0.20.2, so
  it is distribution-supported and would arrive through normal package updates.
- **documented** Mature, broad protocol coverage, and the reference
  implementation for `layer-shell` and `session-lock` — the two protocols
  Bunny's top bar, dock and lock screen depend on most.
- **inferred** Rejected for the prototype on language boundary, not on quality.
  Consuming it from Rust means either C or a binding layer; writing the shell in
  C places Bunny's own security-critical policy code in a memory-unsafe language,
  and a binding layer adds a dependency Bunny would have to maintain.
- **inferred** This is the correct fallback if Smithay's maintenance or
  protocol coverage proves insufficient in V4.

### Mutter as a library or downstream shell — viable, and initially mis-stated

- **observed** Fedora 44 ships `mutter` 50.3 and `mutter-devel`, and libmutter
  has **real downstream consumers beyond GNOME Shell**: `gala` (Pantheon),
  `gnome-kiosk` and `lumina-desktop` all link it.
- This corrects an assumption worth recording: "libmutter cannot be used as a
  downstream shell library" is **false**. Three shipped projects do exactly that.
- **inferred** Rejected for this prototype for a different and narrower reason:
  the phase question is whether Bunny can *replace* the GNOME Shell visual layer.
  Building on libmutter answers a different question — whether Bunny can build a
  different shell on GNOME's compositor — and leaves Bunny inside GNOME's
  release cadence and C/GObject stack.
- **inferred** This is genuinely the lowest-risk path to a shipping product and
  V4 should evaluate it on its merits rather than treating it as excluded. It is
  the recommended comparison arm for V4.

### Mir — not selected

- **observed** Packaged in Fedora 44 as `mir-devel` 2.26.0.
- **documented** A compositor-construction library with a stable ABI and a
  deliberate focus on kiosk and embedded shells.
- **inferred** Rejected because its centre of gravity is single-purpose and
  embedded shells, and its governance is concentrated in one vendor. Neither is
  disqualifying; both add strategic risk Bunny does not need to take while a
  distribution-neutral library is available.

### KDE KWin scripting or extension path — not selected

- **observed** Packaged in Fedora 44 as `kwin-devel` 6.7.3.
- **inferred** Rejected because it repeats the V2 constraint in a new place.
  V2 was a GNOME Shell extension and was limited by what the host shell allowed;
  a KWin script would be limited by what KWin allows, and would additionally
  move Bunny's application ecosystem toward Qt while Bunny's applications are
  GTK 4 / libadwaita. It also does not answer the phase question, which is
  whether Bunny can own the visual layer.

## Decision matrix

Weights reflect Bunny's stated priorities: a trustworthy privilege boundary,
an owned policy layer, and retention of the GTK application ecosystem.

| Criterion | Weight | Smithay | wlroots | Mutter | Mir | KWin |
|---|---|---|---|---|---|---|
| Bunny owns the shell policy layer | 5 | 5 | 5 | 3 | 4 | 1 |
| Memory safety of Bunny-authored code | 5 | 5 | 1 | 1 | 1 | 2 |
| Avoids forking a compositor | 5 | 5 | 5 | 4 | 5 | 5 |
| Protocol coverage inherited | 4 | 3 | 5 | 4 | 3 | 4 |
| Accessibility inherited | 4 | 1 | 1 | 5 | 1 | 4 |
| Distribution packaging in Fedora | 3 | 2 | 5 | 5 | 4 | 4 |
| Governance neutrality | 3 | 4 | 5 | 2 | 2 | 3 |
| Keeps the GTK 4 ecosystem primary | 3 | 5 | 5 | 5 | 4 | 2 |
| **Weighted total** | | **129** | **125** | **113** | **103** | **89** |

The matrix is close between Smithay and wlroots, and that is the honest result.
The tie is broken by criterion 2: Bunny is writing the security-critical policy
code itself, and that code is safer in Rust.

Two entries deserve emphasis rather than burial in a table. Smithay scores
*worst* of all candidates on inherited accessibility, and only Mutter and KWin
score well there. If accessibility parity became the dominant requirement, this
matrix would select Mutter, not Smithay.

## What would overturn this decision

V4 should reopen the framework choice if any of these hold:

1. **Accessibility cannot be built.** If no viable AT-SPI path exists for a
   non-GNOME shell at acceptable cost, the accessibility criterion should
   dominate and Mutter becomes the correct choice.
2. **Protocol gaps prove expensive.** If the protocols Bunny must implement
   itself exceed what a small team can maintain, wlroots' inherited coverage
   outweighs the language advantage.
3. **Maintenance risk materialises.** Smithay is a smaller project than wlroots
   or Mutter. A sustained drop in upstream activity should trigger reselection.
4. **The product question changes.** If Bunny only needs a *different shell*
   rather than an *owned visual layer*, libmutter is a cheaper and lower-risk
   answer and should be chosen.

## Selected stack

| Layer | Choice |
|---|---|
| Language | Rust |
| Compositor framework | Smithay |
| Display protocol | Wayland, with optional XWayland |
| Shell UI toolkit | GTK 4 / libadwaita |
| Shell UI surface mechanism | `wlr-layer-shell-v1` |
| Audio and capture transport | PipeWire |
| Application integration | `xdg-desktop-portal` |
| Service bus | D-Bus |
| Session management | systemd user session |

This is the preferred initial direction stated for the phase. The prototype
adopted it because the evaluation supported it, not because it was suggested;
where the evaluation contradicted an assumption — the libmutter claim above —
the correction is recorded rather than hidden.
