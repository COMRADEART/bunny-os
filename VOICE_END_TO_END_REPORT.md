<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny voice end-to-end and desktop visual acceptance

Candidate: `feature/bunny-desktop-shell` at **`ce7f7a1`**.

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
Character lifecycle      NOT OBSERVED - the shell's own activation paths are
                               both blocked; see "What is not proved"
Tests                    4646 run, 0 failed, 7 skipped
Source gate              re-run pending
```

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

1. **The character's state machine was not observed.** The interaction was
   driven through `bunny-shell-assistant listen` — the exact program
   `VoiceService` spawns — so everything from the shell's process boundary
   inwards is proved. The GJS half is not: the shell only moves the character
   for an interaction *it* started, and both of its starting paths are blocked.
   The microphone button is in the desktop content layer, which takes no pointer
   input; and no extension keybinding fired in the iteration guest, which ran
   the extension from `~/.local/share` where its schema is not in the global
   source. See KNOWN_LIMITATIONS.md.
2. **No human has heard any of this audio.**
3. **The exact image was not built or booted from this candidate.** The
   attempt failed on the host's disk: C: reached zero bytes free, the WSL
   virtual disk could not grow, and the build died with block-layer I/O errors.
4. Settings UI at 1920×1080 and 1366×768, the spoken telemetry and file-search
   queries, the Pocket→Kitten fallback, the all-providers-unavailable case, the
   offline command and the interruption latency all have harnesses written and
   staged, and none of them has been run.

## Tests

```text
4646 run, 0 failed, 7 skipped     (as bunny, on ext4, at ce7f7a1)
```

Twenty-six new, in four groups: every extension module parsed as strict-mode ES
with a planted-fault control; the ownership rule inside and outside a user
namespace, with the group-writable half asserted not to travel with the fix;
the PipeWire default-device metadata for both backends; and `audio_started`
naming its provider. One portability defect was found in the new tests
themselves — Python encoded the child's stdin with the platform codec, so the
first module containing an emoji raised `UnicodeEncodeError` on Windows.
