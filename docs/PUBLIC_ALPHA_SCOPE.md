<!-- SPDX-FileCopyrightText: 2026 ComradeArt -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Bunny OS — Public Alpha 0.1 scope

This document is the feature freeze. It says what Alpha 0.1 **is**, what it
**is not**, and what happens to a proposal that arrives while the freeze is in
force. It is normative: a change that adds something this document defers is a
change that has to move this document first, in a review, and the reviewer's
question is not "is it good?" but "does the Alpha success path fail without it?"

The freeze exists because the companion stack reached feature-complete faster
than the product around it did. Seven branches added a runtime, a character
renderer, a voice, speech input, agent providers, desktop actions and a 3D
renderer. None of them added the thing a person downloads. Alpha 0.1 is that
thing, and it is bounded so that it can be finished rather than extended.

## 1. The success path

Alpha 0.1 is defined by one path working, end to end, on a machine that has
never run Bunny OS before:

```text
download image → boot → install (or supported live mode) → login
  → Bunny Companion starts automatically
  → 3D character when eligible, fallback renderer otherwise
  → user types, or push-to-talks
  → local AI is selected when available
  → Bunny responds
  → user requests a harmless desktop action
  → Approval Centre displays the exact effect
  → user approves → action executes → result is spoken or displayed
  → reboot → Bunny starts healthy again
```

**No terminal is required at any point on this path.** That is a scope
statement, not an aspiration: a step that can only be completed by typing a
command is an Alpha defect, classified against §44 of the phase brief like any
other.

## 2. In scope — Alpha 0.1 contains

Each line is a thing that must work on the success path, on the reference
platform, without a terminal.

### The operating system

| Feature | What "works" means for Alpha |
| --- | --- |
| Bootable Bunny OS image | UEFI x86-64 boots to a login screen from the shipped medium |
| Login / desktop session | GDM presents a session; the Bunny Wayland session starts |
| Installation | Whole-disk UEFI install from the live medium, with destructive confirmation |
| Upgrade | Alpha build *N* → *N+1* through the defined mechanism, settings preserved |
| Rollback / recovery | A failed update leaves a bootable system or a documented recovery mode |
| Version identity | One build identity, visible in settings, diagnostics, release metadata, installer and filename |
| Release channel | `development` and `alpha` only |

### The companion

| Feature | What "works" means for Alpha |
| --- | --- |
| Companion autostart | The runtime service and exactly one window start with the graphical session |
| 3D character | Selected on capable systems by the default-selection policy (§4 below) |
| Animated 2D / static / text fallback | Every rung of the presentation ladder is reachable and usable |
| Typed input | A text request produces a task, always, on every configuration |
| Push-to-talk | Bounded capture with an on-screen indicator when speech resources exist |
| Local speech recognition | Vosk plus an eligible model; typed fallback when either is missing |
| Typed fallback | Never removed. Speech is an addition to the text surface, never a replacement |
| Local text-to-speech | Spoken output through the local voice runtime when audio exists |
| Local AI providers | Ollama, llama.cpp server, llama-cli — detected, probed, selected when eligible |
| Remote providers | Only when explicitly configured by the user; never automatic |
| Task runtime | Sessions, tasks, events, recovery of interrupted work |
| Approval Centre | Every desktop action is described exactly before it happens |
| Desktop action broker | The nine bounded actions below |
| Notifications | Desktop notification through the portal or the session bus |
| Application launch | A named, catalogued desktop entry |
| Volume | Set, with undo |
| Do not disturb | Where the session supports it |
| Clipboard copy | Text only, size-bounded |
| URI opening | Approved schemes only, where a handler exists |
| File reveal | Where a file-manager service is actually activatable |
| Task history | Persistent, per-user, survives reboot |
| Recovery | A user-accessible surface when the companion fails to start |
| Safe mode | A reduced companion that starts when the normal one cannot |
| Diagnostics | Local export, inspectable before sharing, no automatic upload |

### Accessibility, which is in scope and not negotiable

Keyboard navigation, screen-reader labels, reduced motion, no-animation,
text-only operation, caption-only operation, high-contrast compatibility,
scalable UI, optional speech input, optional voice output, optional 3D. **No
essential information may exist only in an animation or only in audio.** This is
a scope line because it is the one that a schedule pressure always tries to move.

## 3. Deferred — Alpha 0.1 does not contain

Deferred is not rejected. It means: not in 0.1, not built during this branch,
and a proposal to add it defaults to *no*.

| Deferred | Why it is deferred rather than dropped |
| --- | --- |
| Wake word | Always-on audio is a privacy posture change, not a feature; it needs a design review Alpha does not have time for |
| Passive / continuous listening | Same. The microphone opens only while a key is held |
| Browser automation | Unbounded authority over a signed-in browser session; no approval model exists that makes it safe |
| Arbitrary keyboard / mouse control | Same class: a general input synthesiser can perform any action the approval model was built to mediate |
| General shell execution | The desktop broker's whole value is that its action set is closed |
| New provider ecosystems | Four adapter families are enough to prove the routing; a fifth proves nothing new and adds surface |
| Full autonomous workflows | Multi-step self-directed execution needs a supervision model Alpha does not have |
| Production character marketplace | Third-party content distribution needs signing, revocation and review. The importer stays local-only |
| Cloud account system | Alpha has no server, and adding one changes the privacy story completely |
| Mobile companion | No second platform |
| Multi-user synchronisation | No shared state between machines |
| New AI-provider families | Frozen |
| New desktop action classes | Frozen at nine |
| New agent autonomy | Frozen |
| New character-rendering architecture | Frozen at 3D / animated-2D / static / text |
| New speech engines | Frozen at Vosk |
| New task runtimes | Frozen |

### Telemetry

Bunny OS Alpha 0.1 has **no telemetry**. Not "off by default" — absent. There is
no counter, no ping, no crash upload and no usage measurement. The debugging
need that would otherwise justify telemetry is met by local diagnostics export,
which the user runs, reads, and chooses whether to send. Adding telemetry "just
for Alpha" is the single change this document most exists to prevent.

## 4. Default character policy

The out-of-the-box character is chosen by capability, once, and then never
changed without the user asking:

```text
if full-3d eligible and the default 3D package validates  → bundled 3D Bunny
else if lightweight-3d eligible                           → lightweight 3D
else if animated-2d available                             → animated 2D
else if static available                                  → static
else                                                      → text-only
```

The rules that make this a *default-selection* policy rather than an automatic
package change:

* **first boot may select the repository-owned default.** No selection exists
  yet, so choosing one is not overriding anything.
* **once the user explicitly selects another character, that choice is
  preserved.** The policy does not run again on a machine that has a recorded
  user selection, on any boot, at any capability level.
* **renderer degradation changes presentation level, not selected package.** A
  machine that loses its GPU draws the selected character with a lower renderer;
  it does not become a different character.
* **recovery restores the selected package** when capability permits, rather
  than leaving the machine on whatever the fallback was.
* **nothing silently replaces a user-selected character.** A selected package
  that cannot be drawn produces a degraded presentation and a diagnostic, not a
  substitution.

## 5. Default security posture

The first boot of a freshly installed Alpha system:

| Setting | Alpha default |
| --- | --- |
| Remote AI | Off unless the user configures a provider and a credential |
| Continuous microphone | Not implemented |
| Wake word | Not implemented |
| Desktop actions | Approval required, every time, with the exact effect shown |
| Secret transfer to a remote provider | Blocked by the privacy filter |
| Local AI | Preferred over remote whenever an eligible local provider exists |
| 3D | Adaptive — selected when eligible, degraded when not |
| Telemetry | Absent |
| Update checks | Only through the defined update mechanism, disabled by default in this build |

## 6. What happens to a new proposal

During `feature/public-alpha-integration`, a feature proposal is **deferred by
default**. It is admitted only if the Alpha success path in §1 is broken without
it. Two consequences worth stating plainly:

* a defect that breaks §1 is in scope to fix, however deep the fix goes. Fixing
  existing behaviour is not a feature.
* a feature that would make §1 *nicer* is out of scope. "Nicer" is 0.2.

Classification uses the four levels from the phase brief — P0 prevents boot or
install or creates an authority violation; P1 breaks a normal Alpha workflow;
P2 leaves a degraded path; P3 is cosmetic. **No P0 or P1 defect is postponed
past public distribution.**

## 7. What this document does not claim

Alpha 0.1 is not a release candidate and this branch makes no reproducibility
claim. Build inputs are being frozen and recorded so that a later qualification
branch can make one; recording an input is not qualifying a candidate. See
`PUBLIC_ALPHA_INTEGRATION_REPORT.md` §42 for the qualification prerequisites
this phase leaves behind, and `KNOWN_LIMITATIONS.md` for what is measured and
what is not.
