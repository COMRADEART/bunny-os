# Bunny Wayland Shell V3 prototype notice

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

This branch is a bounded feasibility prototype for a native Bunny OS Wayland
shell. It exists to answer one question with measured evidence: could Bunny OS
eventually replace the GNOME Shell visual layer while keeping a mature Linux
application ecosystem?

## What this branch is not

It is not a desktop replacement, not a release candidate, and not an input to
any qualification. It does not change a release qualification target, archive
target, installed-system record, encrypted-unlock record, physical-hardware
record, security gate, stable or pilot gate, signing record, reproducibility
record, production key, default session, or historical evidence file.

## GNOME remains the supported session

GNOME is the supported fallback session and remains selectable at the login
screen. `Bunny Shell Experimental` is additive. It never becomes the default,
never replaces a GNOME session file, and never changes a user's preferred
session without consent.

## The qualified image is untouched

The experimental session, its systemd units and the compositor binary are
staged only into `build/visual-v3/` and packaged as an additive review bundle.
They are deliberately kept out of `systemd/` and `systemd/user/`, because
`build/scripts/install-root.py` copies those trees wholesale into the qualified
image. Nothing on this branch is installed by an image build.

## Refusal to run by accident

The session launcher refuses to start unless `BUNNY_SHELL_EXPERIMENTAL=1` is
set explicitly. No installable Bunny OS image may be published from this
branch.
