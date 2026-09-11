# Product-vision host demo

This is the strongest honest demonstration of the user-facing product vision
that a development host can run **without** a Fedora 44 image-builder, nested
KVM guest, or GNOME session.

It is **not** a stable release, **not** a pilot GO, and **not** boot
evidence. `gate-stable-release` remains `NO-GO`. Physical hardware,
independent reviews, and production keys are unchanged.

## One command

From the repository root:

```text
python3 demos/10-product-vision/run.py
```

or, with `make`:

```text
make demo-product-vision
```

The run writes a timestamped directory under `demos/10-product-vision/out/`
and points `out/latest` at it. Open:

- `out/latest/WALKTHROUGH.md` — what to show a reviewer
- `out/latest/report.json` — machine-readable result
- `out/latest/frames/*.html` — Visual Keys, appearance, outcomes, memory,
  first-run, voice
- `out/latest/screenshots/*.png` — state-bound frames (Chrome, when present)

Checked-in copies of a successful cloud-host run live under `evidence/`.

## What the command actually does

| Step | Surface | Needs |
|---|---|---|
| Host probe | KVM / QEMU / Chrome / display | nothing |
| Unit tests | `tests.companion.test_product_vision` | Python |
| Visual Keys 1–3 | speech bubble, character state, reactive scene | Python |
| Appearance | Full 3D / Lightweight 2D / Minimal on simulated machines | Python |
| Outcomes | local vs offline refuse vs memory pressure; no model shop | Python |
| Memory | session / durable / cloud deny-by-default | Python |
| First run | "Hi. I'm Bunny." → "Ready." | Python |
| Voice story | Vosk → bounded intent → TTS | Python; STT/mic/model `NOT_RUN` if missing |
| Screenshots | Chrome `--app` + ffmpeg x11grab | optional |

AT-SPI inside GNOME is **NOT_RUN** on a host without the guest desktop.
Simulated hardware is labelled as simulated. Missing Vosk / microphone /
TTS is `NOT_RUN`, not PASS. No GGUF or Vosk model bytes are vendored.

## Related demos

| Demo | Command | What it is |
|---|---|---|
| Host Trust (#38) | `python3 demos/08-visible-trust/run.py` | Allow / Deny prompt on the host |
| Guest Trust (#39) | `python3 demos/09-guest-trust/run.py` | Fedora guest AT-SPI; `NOT_RUN` without QCOW2 |
| This demo | `python3 demos/10-product-vision/run.py` | Companion face + routing + memory + first-run + voice |

## What still needs Fedora + KVM / hardware / reviews / keys

The guest photograph is a different demo. On a Fedora 44 image-builder host:

```text
make build-shell-test-image
python3 demos/09-guest-trust/run.py
```

See `demos/09-guest-trust/README.md`. A host with `/dev/kvm` and QEMU but no
`image-builder` records `NOT_RUN` rather than faking a guest.

Also still required, and **not** claimed here:

- Physical microphone + packaged Vosk model for a live STT PASS
- Physical Secure Boot / TPM / Orca qualification
- Independent security / privacy / accessibility reviews
- Production signing keys

## Security boundaries

- Deny-by-default: session, durable and cloud memory stay off until turned on.
- Cloud context is `none` or `minimized` only. There is no full-share mode.
- Cloud shares need an explicit field allow-list and still honour the remote
  transfer ceiling.
- No `Always allow everything` control is drawn.
- Outcome routing does not offer a model shop (`modelsOffered` is always empty).
- Voice never plans an unrestricted shell. Unrecognised utterances plan nothing.
- Appearance override cannot force 3D on a machine that cannot honour it.
