# V3 demo

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

```
make bunny-shell-build
sh visual-v3/demo/run-demo.sh            # Regular Mode
MODE=character sh visual-v3/demo/run-demo.sh
```

Requires Linux with a Wayland session, GTK 4, gtk4-layer-shell and the compositor
build dependencies. The shell opens **inside a window in your current desktop**
and exits on its own after two minutes. Your session is never replaced and
nothing is installed.

`BUNNY_SHELL_EXPERIMENTAL=1` is set by the script; without it the shell refuses
to start.

## What to look at

- The top bar and dock are separate GTK 4 processes on `wlr-layer-shell-v1`,
  composited by the Bunny compositor like any other client. Nothing in the bar or
  dock is drawn by the compositor.
- `MODE=character` shows the guide inside the assistant panel and nowhere else —
  never on the backdrop, never in the bar or dock, never over a window.
- The command palette states what every result will do. Typing something that
  matches nothing produces nothing; there is no command fallback.
- Quick Settings shows no switch at all for controls with no backend, rather
  than a disabled switch that looks like it could be turned on.

## What you will not see

Screen sharing, X11 applications, an on-screen keyboard, and anything requiring
a second display. See `visual-v3/KNOWN_LIMITATIONS.md`.
