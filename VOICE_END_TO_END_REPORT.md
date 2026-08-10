<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny voice end-to-end and desktop visual acceptance

Candidate: `feature/bunny-desktop-shell` at **`fdab622`**. The spoken run and the
desktop photographs below were taken at `ce7f7a1`, the commit that carries the
three fixes; `fdab622` adds the packaging split, the settings round-trip test
and this report, and changes nothing the run exercised.

Measured on the Fedora 44 reference host, in a QEMU/KVM guest booted from the
`shell-test` image, unless a line says otherwise.

## Result

```text
Milestone                PARTIAL
Screenshot state         GNOME OVERVIEW - and not because the capture was
                         mistimed: the Bunny desktop had failed to load
Normal Bunny desktop     PASS after three fixes; photographed at 1920x1080
Microphone               PASS  a real PipeWire source carrying real PCM
STT                      PASS  Vosk, "open files", confidence 1.00
Structured action        PASS  launch_application org.gnome.Nautilus.desktop
Files launched           PASS  process, systemd unit, bus name, mapped window
Pocket selected          PASS  READY, no fallback recorded
Pocket synthesis         PASS
PipeWire playback        PASS  the emulated speaker's own recording says
                               "files is open"
Pointer input            PASS  root cause: GNOME's _coverPane, left shown
                               because this desktop stopped the startup
                               animation completing
Microphone button        PASS  pressed on screen; the whole flow follows
Character lifecycle      PASS  idle → listening → thinking → waiting →
                               working → talking → success → idle
Tests                    4649 run, 0 failed, 7 skipped
Source gate              PASS, exit 0, clean tree
Exact image              NOT BUILT - the host ran out of disk; see below
```

## Task #12: the dashboard could not be clicked

The dashboard received no pointer input at all — not the character, not a card,
not a Quick Access tile, not a suggestion chip, not the assistant's field, not
its microphone button. The top bar, the sidebar and the dock worked.

Asked of the compositor rather than guessed at — `get_actor_at_pos`, the same
picking the event path uses, at each failing coordinate:

```text
(360,414)  (1784,627)  (1420,547)  (1713,627)  (700,800)
  → Main.layoutManager._coverPane
    reactive=True visible=True mapped=True opacity=0
    stage={x:0, y:0, width:1920, height:1080}
    chain: ClutterActor < uiGroup < MetaStage

(991,1028) → StBoxLayout 'bunny-dock-tile' — the dock, which is chrome
```

`_coverPane` is GNOME's own full-screen, transparent, **reactive** actor. Its
only job is to swallow input while the startup animation runs, and
`_startupAnimationComplete` disposes of it. That animation eases `panelBox`
into place. This desktop hid `panelBox` at enable() and re-hid it on every
`notify::visible`, so the animation never completed and the pane was never
disposed of. It sits in uiGroup **above `window_group`**, so it was taking
events meant for application windows as well.

With `desktop-enabled false` in the same image, the same points picked ordinary
actors. That control condition is what pinned it on this desktop rather than on
GNOME.

The fix takes the panel only after `startup-complete` — or after a deadline, for
the case where that signal fired before this desktop enabled — keeps the
visibility watcher inert until then, and, if the pane is *still* shown at that
point, hides it explicitly. Nothing decorative was made reactive to win the
pick: the content layer is still non-reactive and `makeActivatable` is still the
only place reactivity is granted.

### Two more that only appeared once clicks arrived

**The companion had no display.** A spoken "Open Files" was transcribed, routed,
approved — and answered *"there is no graphical session, so a launched
application would have nowhere to appear"*, on a machine with a desktop on
screen. `bunny-companion.service` was ordered after
`graphical-session-pre.target`, so it started at 14:00:23 while the target was
reached at 14:00:25: before the compositor had created `wayland-0`. It spent the
session refusing every action needing a display. It hid because restarting the
service picks the variables up, and development restarts it constantly. The unit
is now ordered after the target, and the service adopts the display from the
runtime directory if it is still missing.

**Voice availability was asked once.** Ordering the companion later made the
shell's single startup check reliably precede the companion's socket, and the
microphone button read *"Speak to Bunny. Unavailable: the companion runtime is
unreachable"* with `sensitive=false` for the whole session. It is asked again,
bounded, and stops the moment the answer is yes.

## The shell-originated run

From a pointer press on the visible microphone button, with no injected
transcript, no manual action and no manually set character state:

```text
+0.0s   press at (1784,627) on 'Speak to Bunny'
+1.0s   listening        privacy indicator up
+5.7s   thinking         "open files", Vosk, confidence 1.00
+6.7s   waiting for permission (launch_application, irreversible)
        → allowed
+8.1s   working
+15.9s  talking          "Files is open."   Pocket, caro_davy
+17.5s  success → idle
```

Files really opened: process, `dbus-:1.2-org.gnome.Nautilus@0.service`, the
`org.gnome.Nautilus` bus name, and a showing frame at (0, 0, 890, 550).

## The other spoken acceptances

```text
"How much memory am I using?"
  spoken   "You are using 1.9 GiB of 5.8 GiB of memory (33%)."
  /proc    used 1.91 GiB of 5.77 GiB (33%)          — the same number

"Find PDF files in Downloads."
  spoken   "I found 2 matching files: bunny-test-one.pdf, bunny-test-two.pdf."
  on disk  those two, plus bunny-test-notes.txt, which was correctly not matched
  and with an empty Downloads the same question answered "I did not find any"

interruption
  audio stopped 116 ms after the cancel        (target < 250 ms)
  measured on the player process and the sink's own state, polled at 10 ms

Pocket unavailable (its model tree replaced by an empty directory)
  audio_started providerId=kitten implementationId=kitten-tts/0.8.1
                voiceId=Bella — and the configured engine stayed pocket

every provider unavailable (both models and both programs)
  the text answer was still correct and still displayed; the character went
  listening → thinking → success and never entered TALKING; no crash

networking down (every non-loopback link down, ping unreachable)
  "Open Terminal" → Terminal opened, spoken by pocket-tts/2.1.0 locally
```

## Performance, on the booted system

```text
                     Pocket        Kitten
cold synthesis       7.37s         1.12s      includes the worker's first load
warm synthesis       0.99, 1.12s   0.75, 0.93s
warm RTF             0.28          0.19-0.23
```

Worker RSS is **not** reported: the reader matched a 13 MiB process, which
cannot be the worker that holds a PyTorch model, so the number is wrong and a
wrong number is worse than none. GNOME Shell stayed responsive throughout —
every screenshot, pointer press and window operation in this report was taken
while this was running.

## What the screenshot actually showed

The 1920×1080 screenshot that prompted this work is GNOME's Activities
overview: its search entry, its workspace strip, its dash. The obvious reading
is that the harness photographed the wrong moment — GNOME opens the overview at
login when a session has no windows, and the desktop already dismisses it.

That reading is wrong, and the difference matters. Asked directly, the session
answered:

```text
OverviewActive                     true
extension state                    3   (ERROR)
extension error                    SyntaxError: 'arguments' can't be defined or
                                   assigned to in strict mode code
                                   @ …/lib/services/voice.js:367:14
```

**The Bunny desktop was not running at all.** GNOME had recorded the extension
as failed and carried on with its own desktop, which is why the screenshot
looks like an ordinary GNOME login — because it is one.

## Three defects, each of which cost the whole feature

### 1. A parameter named `arguments`

`lib/services/voice.js` had `_control(arguments, onLine = null)`. An ES module
is strict-mode code, binding that name in it is a SyntaxError, and GJS raises it
while *loading* the import graph — before `enable()` is called, so extension.js's
top-level try/catch never ran. `node --input-type=module --check` reproduces it
exactly, and now every one of the extension's 41 modules is parsed that way by
the suite, with a negative control that plants the same fault.

### 2. The dashboard was painted behind the wallpaper

With the extension loading, the desktop came up and the middle of the screen was
empty: no character, no cards, no greeting. The accessibility tree disagreed —
313 named controls, all with correct rectangles: `System overview` at
(232, 64, 304, 236), the character at (866, 325, 400, 600), `Bunny says:` with
this morning's text in it.

The content layer had been lowered below `global.window_group` in `uiGroup`.
GNOME's wallpaper is not behind window_group; it is the bottom child *inside*
it. So the whole dashboard was drawn behind an opaque full-screen image while
remaining built, allocated, and answering assistive technology.

It had been shipping since 9 August. The run of 9 August at 16:53 has the same
blank middle, and nothing caught it because no test compares pixels with the
tree. The wallpaper is now reparented into `uiGroup` immediately below the
content layer and put back on teardown, and `_assertDesktopContentIsDrawable`
writes the arrangement to the journal.

### 3. Speech input was refused on every shipped image

The microphone button was greyed with *"Voice recognition needs repair before it
can be used"*, and `speech_input_health` gave the reason:

```text
readinessState  STT_MODEL_CORRUPT
detail          vosk-model-small-en-us-0.15: is owned by uid 65534
                rather than root or this user
```

65534 is the kernel's overflow uid. `bunny-companion.service` is a *user* unit
with `ProtectSystem=strict`, so systemd gives it a user namespace, and its map
is one line:

```text
$ cat /proc/$(pgrep -f bunny-companion-service)/uid_map
      1000       1000          1
```

Root is not mapped, so every root-owned file — every file in `/usr`, including
the speech model and every `.desktop` file — is reported to that process as
65534, and the ownership rule refused all of them. The same rule guards
`companion/desktop/entries.py`, so application launching was refused for the
same reason.

Nothing in the suite could see it: every test runs outside that namespace, where
the same files report uid 0. `companion/ownership.py` now states the rule once
and accepts the overflow uid *only* when this process is in a namespace that
does not map root — where nothing inside can have written the file — and the
group/other-writable half of the rule is unchanged. The regression test
simulates the namespace rather than assuming it away.

## Two more, found by running the stack rather than reading it

**Both PipeWire backends read `node.default`, a property that does not exist.**
Every device came back `default=False`, selection fell through to "the first
non-monitor node in graph order", and capture ran against a silent line-in while
the selected microphone sat beside it in the same graph. The interaction ended
with *"the input device was lost"* — a true statement about the wrong device.
The default lives in the metadata object under
`default.configured.audio.source`; `companion/pipewire.py` reads it, and the
playback backend had the identical bug.

**`audio_started` did not name the provider** on the synthesise-and-play path,
so "which engine was heard" could only be inferred from configuration — wrong in
the one case worth reporting, a fallback.

## The spoken run

Every event below is the shipped bridge's own output, from a real capture
device, on the booted system.

```text
voice_started
microphone          {"active": true}
voice_phase         {"phase": "listening"}
partial             {"text": "open"}
partial             {"text": "open fire"}
partial             {"text": "open files"}
microphone          {"active": false}
voice_phase         {"phase": "transcribing"}
transcript          {"text": "open files", "confidence": 1.0, "providerId": "vosk"}
accepted            {"taskId": "task-4aa9581395e0…"}
phase               starting → understanding → planning → waiting_for_approval
approval            {"action": "launch_application",
                     "reason": "Open Files. The application starts and its window
                                appears. Discloses: nothing. This cannot be
                                undone (irreversible)."}
                    → allowed
phase               working → presenting_result
reply               {"text": "Files is open."}
speech_started      {"deviceId": "alsa_output.pci-0000_00_05.0.analog-stereo"}
phase               speaking
speech_finished
phase               success
finished            {"phase": "success"}
```

Launching an application raises a permission question, so the flow includes one
approval. That is the product being careful, and it is reported rather than
worked around.

Files really opened, on four independent signals:

```text
process     /usr/bin/nautilus --gapplication-service
unit        dbus-:1.2-org.gnome.Nautilus@0.service
bus name    org.gnome.Nautilus
window      frame 'Home', showing=True, extents (0, 0, 890, 550)
```

Pocket was the provider — `ready=True`, `status=READY`, `ttsFallbackWarning`
empty — and the reply was spoken through
`alsa_output.pci-0000_00_05.0.analog-stereo`, a real ALSA sink.

### The audio was recorded off the speaker and read back

QEMU's `wav` audiodev writes everything the guest's HDA codec is handed to a
file on the host. That file is what a microphone in front of the speaker would
have heard, and the recogniser the product ships was pointed at it:

```text
played-1786347412.wav: 2ch 44100Hz 16bit 6.48s peak=14957 nonzero=65957
  heard: 'files is open'
```

Synthesis, PipeWire, ALSA, the emulated codec and back through Vosk. It is not a
person listening, and it is not a WAV file on disk either.

## How the microphone was made real

A VM has no microphone, and QEMU's `wav` backend is output-only. The
arrangement, which the milestone permits and which passes real PCM through the
whole Linux audio stack:

```text
speaker      -device intel-hda -device hda-micro -audiodev wav,path=…
             a real ALSA sink, and everything played is captured on the host
microphone   pactl load-module module-pipe-source source_name=bunny-virtual-microphone
             file=/tmp/bunny-mic.fifo format=s16le rate=16000 channels=1
             plus a daemon holding the FIFO open and writing silence between
             utterances, and `pactl set-default-source`
```

Two things had to be learned the hard way. A null sink published as
`media.class=Audio/Source/Virtual` does *not* work: `pw-play --target` ignores
it and the audio lands on the default sink, and the recorder captures two
seconds of digital silence. And closing the FIFO between utterances makes
PipeWire drop the source, which the companion correctly reports as *"the input
device was lost"* — a microphone that exists only while something is being said
is not a microphone.

The injected speech is Kitten's, not Pocket's: Pocket is the engine under test
on the output side, and using it for the input as well would make the acceptance
a loop through one model. **No human voice was recorded**; that is stated
plainly rather than implied.

## What is not proved

1. **No human has heard any of this audio.** Every audibility claim ends at
   QEMU's recording of the emulated speaker, read back by a recogniser.
2. **The voice settings page was not seen working.** The defect that made it
   unreachable — no `companion` on `bunny-settings`'s path — is fixed in source
   and covered by a test, and the page was photographed at both resolutions
   still showing the old build, because the iteration overlay does not reach
   `/usr/lib/bunny-shell`. Nothing in this report claims the provider list or
   the readiness states have been looked at.
3. **The 1366×768 screenshots are sheared.** A screendump taken after the
   framebuffer is resized tears diagonally; the same artefact is described in
   DESKTOP_SHELL_ALPHA_VALIDATION.md. The accessibility measurement at that
   size is sound — 62 controls, **0 off-screen** — but the photograph is not
   presentable and no visual judgement should be made from it.
4. **The keyboard shortcut was not exercised end to end.** All four bindings
   now report successful registration in the journal, which is new; but this
   harness cannot deliver Super to Mutter at all — GNOME's own overlay-key does
   not fire either, while ordinary typing into a focused terminal works. The
   shortcut path was therefore replaced by the microphone button, which is the
   stronger claim anyway.
3. **The exact image was not built or booted from this candidate.** The
   attempt failed on the host's disk, not on anything in the tree: Windows C:
   reached zero bytes free, so the WSL `ext4.vhdx` could not grow, and writes
   into never-allocated regions failed at the block layer. `df` inside the
   guest still reported 421 GB free, which is why the first symptom was
   `podman: reading boot ID from runtime alive file: input/output error` rather
   than anything about space. The build reached step 20 of 32 and stopped.
4. Settings UI at 1920×1080 and 1366×768, the spoken telemetry and file-search
   queries, the Pocket→Kitten fallback, the all-providers-unavailable case, the
   offline command and the interruption latency all have harnesses written and
   staged, and none of them has been run.

## Package boundaries

`assets/voice/tts` was one install route carrying both engines, which made
"ship the small engine only" a source edit. It is now two:

```text
bunny-voice-core     speech-synthesis-runtime, speech-recognition-models,
                     speech-recognition-licenses, the companion package
bunny-tts-pocket     speech-synthesis-model-pocket  + the runtime above
                     ~1.1 GiB uncompressed, installed by default
bunny-tts-kitten     speech-synthesis-model-kitten
                     ~107 MiB including its ONNX runtime and numpy
bunny-tts-espeak     a Fedora package dependency, not an asset route
```

Same destinations, same bytes; the boundary is now where a profile can act on
it. `SpeechSynthesisService` is untouched — it selects by provider id and
descends a fixed fallback order over whatever is installed — and a test asserts
neither engine's tree can reach through the other's route.

## Settings contract

`settings_voice_get` and `settings_voice_set` are in `OPERATIONS`, in
`schemas/companion-protocol.schema.json`, and in the reachability test that
notices an operation being added. What was missing was a test of what the
listing is *for*, and it is there now: default Pocket → set Kitten → read back
Kitten → set Pocket → read back Pocket, with every read taken from the file
rather than from the object that wrote it. A provider id the registry does not
own is refused with `SettingsError` and leaves the stored choice alone.

## Tests and gate

```text
4649 run, 0 failed, 7 skipped     (as bunny, on ext4, at fdab622)

source gate: PASS                 (as bunny, on ext4, at fdab622, clean tree)
  ok  baselineRecorded          ok  qualificationSuitesPass
  ok  licenceGatePassed         ok  repositoryValidation
  ok  minimisationComplete      ok  sourceSuitesPass
exit code 0
```

The gate failed once in between, on `sourceSuitesPass`, and that failure was the
host rather than the source: `scripts/task.py test` re-run by hand at the same
commit passed 4646 and then 60, and the run that failed overlapped the disk
fault described below. A gate result taken while the block layer is returning
I/O errors says nothing about the tree.

Twenty-six new, in four groups: every extension module parsed as strict-mode ES
with a planted-fault control; the ownership rule inside and outside a user
namespace, with the group-writable half asserted not to travel with the fix;
the PipeWire default-device metadata for both backends; and `audio_started`
naming its provider. One portability defect was found in the new tests
themselves — Python encoded the child's stdin with the platform codec, so the
first module containing an emoji raised `UnicodeEncodeError` on Windows.
