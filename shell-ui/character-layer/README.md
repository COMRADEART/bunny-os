# Character layer

> BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
> DEFAULT SESSION

This directory has no executable, and that is the design.

The guide character is a **widget inside an approved panel**, never a surface of
its own. Making it a compositor-level surface would mean it could float over an
application window, appear on the wallpaper, or survive the panel that gave it
meaning — all of which the character policy forbids. Because it has no surface,
those rules are structural rather than enforced by checks that could be missed.

It also cannot take keyboard focus, because a `Gtk.Picture` with `can-focus` and
`can-target` both false is not in the focus chain and does not receive input.

The implementation is `apps/common/bunny_shell_v3/character.py`. It uses the
canonical V2 character family unchanged; V3 created no new artwork.
