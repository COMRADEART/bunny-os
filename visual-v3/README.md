# Bunny OS Visual Phase V3 — native Wayland shell feasibility prototype

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

This phase answers one question with measured evidence: **could Bunny OS
eventually replace the GNOME Shell visual layer while keeping a mature Linux
application ecosystem?**

It is a feasibility prototype. It is not a desktop replacement, and it is not
on a path to production without a separate V4 phase.

## Where things are

| Path | Contents |
|---|---|
| `compositor/bunny-shell/` | The Rust/Smithay compositor |
| `shell-ui/` | Shell chrome as GTK 4 layer-shell clients |
| `portals/` | Portal integration surfaces |
| `sessions/bunny-shell-experimental.*` | The additive experimental session |
| `visual-v3/` | Specifications, reports and evidence |
| `tests/compositor_v3/`, `tests/shell_ui_v3/`, `tests/security_v3/`, `tests/accessibility_v3/`, `tests/performance_v3/`, `tests/protocol_v3/` | Test suites |

V1 (`visual/`) and V2 (`visual-v2/`) sources are untouched.

## Documents

| Document | Answers |
|---|---|
| [FRAMEWORK_DECISION.md](FRAMEWORK_DECISION.md) | Why Smithay, and what would overturn it |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the pieces fit and where the privilege boundary sits |
| [PROTOCOL_SUPPORT.md](PROTOCOL_SUPPORT.md) | Which protocols work, verified by a real client |
| [SECURITY_MODEL.md](SECURITY_MODEL.md) | What the compositor may and may not do |
| [ACCESSIBILITY_MODEL.md](ACCESSIBILITY_MODEL.md) | The accessibility architecture and its gaps |
| [PERFORMANCE_MODEL.md](PERFORMANCE_MODEL.md) | Targets, and the measured results against them |
| [COMPATIBILITY_MATRIX.md](COMPATIBILITY_MATRIX.md) | Which real applications ran |
| [MULTI_DISPLAY_REPORT.md](MULTI_DISPLAY_REPORT.md) | Multi-output and scaling behaviour |
| [CRASH_RECOVERY_REPORT.md](CRASH_RECOVERY_REPORT.md) | What happens when the shell dies |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | What does not work |
| [V4_PRODUCTION_REQUIREMENTS.md](V4_PRODUCTION_REQUIREMENTS.md) | What production would need |

The phase verdict is in `BUNNY_WAYLAND_SHELL_V3_REPORT.md` at the repository
root.

## Commands

```
make bunny-shell-setup               # record the host toolchain
make bunny-shell-build               # build the compositor
make bunny-shell-run-nested          # run inside your existing session
make bunny-shell-run-vm              # run in a disposable VM
make bunny-shell-test                # unit tests, Rust and Python
make bunny-shell-protocol-test       # enumerate globals with a real client
make bunny-shell-a11y-test           # accessibility assessment
make bunny-shell-security-test       # adversarial security tests
make bunny-shell-performance-test    # measure against the targets
make bunny-shell-compatibility-test  # run real applications
make bunny-shell-package             # build the additive review bundle
make bunny-shell-clean
```

Direct entry points, for use without `make`:

```
python3 visual-v3/tools/visual_v3.py <command>
cargo build  --release --manifest-path compositor/bunny-shell/Cargo.toml
cargo test   --release --manifest-path compositor/bunny-shell/Cargo.toml
./compositor/bunny-shell/target/release/bunny-shell --self-check
```

`run-nested` opens the shell in a window inside your current desktop and never
replaces your session. `run-vm` requires a disposable overlay disk and refuses
to run without one.

## Running it

The shell fails closed. It refuses to start unless:

```
BUNNY_SHELL_EXPERIMENTAL=1
```

is set, GNOME is still installed as a selectable session, the shell is not
configured as anyone's default session, and no qualification run is in
progress. `--self-check` reports each gate without starting anything.
