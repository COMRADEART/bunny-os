<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Pocket TTS default engine milestone

Candidate: `feature/bunny-desktop-shell` at **`4d7e9a4`** — the commit the image
was built from. Later commits in the table are documentation and evidence;
because `docs/` is a build COPY root, a rebuild at a later commit would not be
this image.

Measured on the Fedora 44 reference host (22 cores, 15 GiB), as user `bunny`
on ext4, unless a line says otherwise.

## Result

```text
TTS milestone            PARTIAL - the engine work is complete and proved on
                         the built image; the booted end-to-end run is not
Default engine           Pocket TTS - PASS, on the image itself
Pocket real audio        PASS  on the built image, recognised back at WER 0.00
Kitten real audio        PASS  on the built image, recognised back at WER 0.00
eSpeak fallback          PASS
Automatic fallback       PASS
Interruption             PASS  (0.06s to stop a running utterance)
Image built              PASS  shell-test at 4d7e9a4, 543-package snapshot
Tests                    4620 passed, 0 failed, 7 skipped
Source gate              PASS, exit 0
Spoken "Open Files"      NOT RUN in a booted session
Settings UI at 2 sizes   NOT VALIDATED
```

The honest headline: **Pocket TTS is the default engine and it really speaks
inside a Bunny OS image that was built from this source.** What has not been
done is drive it from a microphone through a booted graphical session. The
section "What is not proved" says exactly what that leaves open.

## Proved on the built image, not on a staging host

The strongest evidence here is that the probe below ran **inside
`localhost/bunny-os-shell-test:4d7e9a4736f7`** — the real image, its own
interpreter, its own `/usr/bin` launcher, its own trusted-directory rules and
the provider registry the companion actually builds. 11 of 11 checks passed.

```text
PyTorch CPU wheel expanded into the image      695 MiB, staging wheel removed
vendored Pocket runtime installed              /usr/lib/bunny-os/voice-runtime
neural worker launcher in a trusted directory  /usr/bin/bunny-voice-neural-worker
Pocket English model installed                 /usr/share/bunny-os/voice/pocket
Kitten nano INT8 model installed               /usr/share/bunny-os/voice/kitten
companion voice package importable             /usr/lib/bunny-os/python
configured default engine is Pocket            pocket
Pocket reports READY on the installed image    worker, english model and
                                               Bunny Default (Caro Davy) loaded
registry selects Pocket with no preference     selected=pocket
pocket synthesises real audio on the image     36480 frames @24kHz, RTF 0.33
kitten synthesises real audio on the image     67000 frames @24kHz, RTF 0.24
```

Both WAVs were then copied **out** of the image and recognised back with Vosk:

```text
pocket   expected "files is open"   heard "files is open"   WER 0.00
kitten   expected "files is open"   heard "files is open"   WER 0.00
```

So the default engine, on a freshly built image, produces audio that is the
sentence it was asked for.

## What was wrong when this session started

The stack existed and was well-shaped. None of it had ever run. Four defects
in Kitten's phonemization, one protocol gap and one performance defect were
found by running it, and every one of them was invisible to reading.

| # | Defect | How it presented |
| --- | --- | --- |
| 1 | `--quiet` is not an eSpeak NG option | eSpeak prints a complaint and **exits 0**. Only the empty stdout stopped it, so Kitten had never produced a sample. |
| 2 | `--voice=en-us` is prefix-matched to `--voices` | eSpeak printed its **voice table** to stdout and exited 0. Non-empty output passes the guard, so the table would have been phonemized and spoken as the utterance. |
| 3 | Token vocabulary missing `U+201C`/`U+201D` | Every letter and IPA index shifted by two against the table the ONNX model was trained on, so each phoneme selected its neighbour's embedding. |
| 4 | `--ipa=3` tie characters tokenized as punctuation | Joined with spaces, and space is a real index, so the model read a word boundary inside every diphthong: "your" came out "you are". |
| 5 | `settings_voice_get`/`settings_voice_set` absent from the wire schema | The protocol declared them and the service implemented them, but the contract a peer validates against did not list them. |
| 6 | OpenMP pool unbounded | `torch.set_num_threads(1)` bounds PyTorch and not the OpenMP runtime beneath it. Pocket ran at 3.1× slower than real time while burning 17 cores. |

Defects 1–4 all failed the same way: **loud, fluent, confident audio that was
not the sentence requested.** Amplitude assertions pass on all of them. That is
why the intelligibility check below exists.

## How "it produced audio" was separated from "it produced the right words"

Every synthesised utterance is recognised back with the Vosk model Bunny
already ships, and scored as word error rate against the input text. A voice
table read aloud is loud too; only recognition distinguishes it from speech.

The control matters: eSpeak NG's own output scores 0.44 through the same
pipeline, because Vosk finds its robotic voice hard. Pocket scores 0.00. The
harness is therefore good enough to certify a natural voice and is *not*
sensitive enough to judge eSpeak — so eSpeak is reported as "produces audio",
not "scored".

Kitten before and after the four fixes, same sentence, same pipeline:

```text
before   WER 1.56   "imho close it itll be who you are not worth cool occurs no no"
after    WER 0.00   "hello i am bunny and your system is ready"
duration 5.89s -> 4.67s
```

## Benchmark

Identical sentences, real worker, real models, wall clock. Pocket's numbers are
after the OpenMP fix; the before-column is included because it is the size of
that one defect.

| Category | Pocket synth | Pocket audio | Pocket RTF | Kitten synth | Kitten audio | Kitten RTF |
| --- | --- | --- | --- | --- | --- | --- |
| "Hello. I am Bunny, and your system is ready." | 2.21s | 3.84s | **0.58** | 0.91s | 4.67s | **0.19** |
| "Your Downloads folder contains five files." | 1.93s | 3.36s | 0.57 | 0.96s | 5.34s | 0.18 |
| "You have 7.8 gigabytes of memory available." | 2.16s | 3.76s | 0.57 | 1.00s | 5.69s | 0.18 |
| "Files is open." | 0.94s | 1.60s | 0.59 | 0.52s | 2.79s | 0.19 |
| "Would you like me to open the newest document?" | 1.36s | 2.40s | 0.57 | 0.78s | 4.32s | 0.18 |
| Three-sentence answer | 3.57s | 6.40s | 0.56 | 1.38s | 8.12s | 0.17 |

```text
                        Pocket              Kitten
cold initialization     1.6 - 3.2s          0.4s
warm re-initialization  0.001s              0.001s
warm first audio        2.33s               0.85s
peak worker RSS         1109 MiB            223 MiB
real-time factor        0.56 - 0.59         0.17 - 0.19
word error rate         0.00 (all but one)  0.00 (all but one)
```

The OpenMP defect, on the benchmark sentence:

```text
as shipped          12.05s wall   209.24s CPU   17.4x   RTF 3.14
OMP_NUM_THREADS=1    2.00s wall     2.66s CPU    1.3x   RTF 0.57
OMP_NUM_THREADS=2    1.57s wall     5.58s CPU    3.6x   RTF 0.43
OMP_NUM_THREADS=4    1.35s wall     9.99s CPU    7.4x   RTF 0.36
```

One thread was chosen: six times faster than the default, seventy-nine times
less processor, and it cannot oversubscribe a two-core machine. Two and four
are faster still but spend multiples of the whole machine to save tenths of a
second. Pinned to two cores, Pocket still measures RTF 0.56 and Kitten 0.19,
so neither engine depends on the reference host's core count.

**A measurement that is deliberately not reported:** CPU-seconds for Kitten.
The host reports 8.68 CPU-seconds inside a 0.93s wall window with the worker's
eleven threads verified confined to two CPUs — a 1.87s ceiling. That is
impossible, so WSL2's accounting over-reports for many spinning threads and no
CPU-second figure from this host is trustworthy for a multi-threaded engine.
Wall clock and RSS are unaffected, and the Pocket result above is a wall-clock
result.

## Quality observations

Both engines are intelligible on all six categories. Two notes:

- **Numbers.** "7.8" recognised back as "seven eight" from Pocket and "seven
  point eight" from Kitten. Whether Pocket omits "point" or Vosk drops it is
  not resolved by this method; it needs a listener.
- **Length.** Kitten speaks the same sentence appreciably slower than Pocket
  (4.67s against 3.84s) at its packaged speed prior of 0.8.

## Image size

Uncompressed installed bytes, because a 650 MiB dependency that compresses
well is still 650 MiB on the disk of a modest machine.

```text
Pocket runtime: PyTorch CPU wheel, expanded          650.7 MiB
Pocket runtime: vendored pocket_tts source             0.4 MiB
Pocket model: english                                208.9 MiB
Pocket prepared voice: caro_davy                       5.0 MiB
                                            Pocket   865.1 MiB

Kitten model: nano INT8 ONNX                          23.2 MiB
Kitten built-in voices (8)                             3.1 MiB
                                            Kitten    26.4 MiB

                                             TOTAL   891.5 MiB
```

Plus supporting Fedora packages newly named by this milestone — onnxruntime
38.9, numpy 41.7, scipy 64.5, sympy 84.3, networkx 18.3 MiB and smaller ones,
about 260 MiB of the 316.4 MiB measured across the whole named set.

**So making Pocket the default costs roughly 1.1 GiB uncompressed, about ten
times what Kitten alone would cost (~107 MiB including its ONNX runtime and
numpy), to buy real-time factor 0.57 instead of 0.19 and a more natural
voice.** That is the trade the default now takes, stated plainly because it is
a large one for a system aimed at modest hardware.

## Provider behaviour, measured against the real registry

Real providers, real worker at `/usr/bin/bunny-voice-neural-worker`, real
models under `/usr/share/bunny-os/voice`. 12 of 12 checks passed.

```text
readiness       pocket READY, kitten READY, espeak-ng READY, speech-dispatcher READY
default         pocket selected with no preference expressed
synthesis       pocket, kitten and espeak-ng each produced real audio
fallback        pocket model unusable          -> kitten selected
                pocket and kitten unusable     -> espeak-ng selected
                every provider unusable        -> nothing selected, no exception,
                                                  four refusals each with a reason
cancellation    a running Pocket utterance stopped 0.06s after the signal
```

Readiness is not executable presence: a provider reports READY only after its
manifest, every pinned file digest, its prepared voice and its worker
initialization have all succeeded.

## Tests

```text
4620 run, 0 failed, 7 skipped        (python3 -m unittest discover -s tests -t .)
```

Six tests were added for defects 1–4 and the thread pin. Each was verified by
reintroducing its defect and confirming the test fails — the tie-handling test
did **not** fail on the first attempt, because it exercised the helper while
the caller had stopped calling it, so the whole token path is now one method
with no call site left to get wrong.

No existing voice test was weakened or removed.

## Source gate

```text
python3 scripts/release.py gate --kind source
source gate: PASS
  ok  baselineRecorded          ok  qualificationSuitesPass
  ok  licenceGatePassed         ok  repositoryValidation
  ok  minimisationComplete      ok  sourceSuitesPass
exit code 0
```

## Byte-accounting defects fixed on the way

Two, both of the class where a checkout's platform changes a recorded fact:

- `assets/voice/tts/**` and `assets/voice/runtime/**` were not marked `-text`.
  Pocket's `config.yaml`, Kitten's `config.json` and its model card are text
  members of a set pinned by size and SHA-256; a Windows checkout rewrites
  exactly those three to CRLF, and an unmodified tree then reports
  `MODEL_CORRUPT`.
- `assets/voice/licenses/**` likewise, which made `PROVENANCE.json`'s declared
  byte total disagree with itself by the 200 line endings between a Windows and
  a Linux checkout. Both checkouts now measure 436,603,718 bytes.

## What is not proved

Stated as flatly as the passes:

1. **Nothing has been driven through a booted graphical session.** The image
   exists and its voice stack works when exercised directly; GDM, the Bunny
   session, the companion service starting on its own and the shell talking to
   it have not been observed in this session.
2. **The spoken "Open Files" acceptance (criterion 20) has not been run.** No
   real microphone, real STT, real launch action and real Pocket audio have
   been exercised end to end inside Bunny OS in this session. A VM also cannot
   supply a real microphone without a null-sink/loopback arrangement, which is
   the technique this project has used before and which was not set up here.
3. **The settings UI has not been validated at 1920×1080 or 1366×768.** The
   Voice Output page is implemented and provider-neutral by inspection, and
   has not been rendered and looked at.
4. **Character TALKING synchronisation is not confirmed against playback.**
   The provider returns audio and the audio path is unchanged, but the
   state transition was not observed in a running session.
5. **Streaming is not implemented.** Pocket synthesises complete utterances;
   `supports_streaming` is declared `False` rather than simulated by cutting a
   finished WAV into pieces. Time to first audio is therefore whole-utterance
   synthesis time — 0.94s for "Files is open.", 2.2s for a typical sentence.
6. **Quality is scored by a recogniser, not a listener.** No human has heard
   any of this audio.

## Commits

| Commit | What |
| --- | --- |
| `488f4bd` | Pocket as default engine: providers, worker, assets, packaging |
| `aa41051` | The four Kitten phonemization defects |
| `8bb970b` | Tests for those defects, thread pin, licence byte accounting |
| `21d4b48` | Voice settings operations added to the wire schema |
| `bf6e8a1` | OpenMP pool bounded in the neural worker |
| `4d7e9a4` | **Package set relocked: 543 packages, snapshot `fedora-44-beta-20260810-tts`. This is the commit the image was built from.** |

## Build

```text
profile        shell-test
commit         4d7e9a4, clean tree
base           quay.io/fedora/fedora-bootc:44@sha256:c466de53…  (verified retention)
snapshot       fedora-44-beta-20260810-tts, 543 packages,
               every checksum and signature verified, installed over file://
container      localhost/bunny-os-shell-test:4d7e9a4736f7, 6.6 GB
voice payload  /usr/lib/bunny-os/voice-runtime 701 MiB
               /usr/share/bunny-os/voice        241 MiB
```

The lock had to be refreshed before any of this was possible: the profile named
ONNX Runtime, numpy, safetensors and the PyTorch wheel's dependencies while the
lock still described the 474-package set resolved before they existed, so no
candidate image could have contained the default speech engine.
