# V3 screenshots

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

**These are not mockups.** Visual Phase V2 shipped SVG mockups, clearly labelled
as such, because there was no running shell to photograph. V3 has one, so these
PNGs are the compositor's own framebuffer read back through `ExportMem` — a
photograph of what it actually drew.

## What is in them, and what is not

`regular-desktop.png` and `character-desktop.png` show the composited Bunny
desktop in each visual mode. The two files differ, which is itself the evidence
that the mode selection reaches the renderer: Regular Mode and Character Mode
use different backdrop values.

**They do not show the shell chrome, and that is a measurement failure rather
than a design.** In a nested run the host compositor decides when our window is
presented, and the capture happens inside the render path. On the measurement
host the host compositor stopped presenting frames after the first two — before
the top bar, dock, assistant panel and command palette had mapped — so the late
capture never ran and the harness fell back to capturing the first frame. The
fallback and its reason are recorded in `visual-v3/reports/screenshots.json`
rather than left for a reader to infer from an empty picture.

The chrome demonstrably works; it is just not in these frames. The evidence for
it is the compositor's own log of the layer surfaces it mapped, at the geometry
it assigned them:

```
layer surface mapped: namespace=bunny-top-bar   layer=Top     role=TopBar         geometry=2560x32+0+0
layer surface mapped: namespace=bunny-dock      layer=Top     role=Dock           geometry=2560x64+0+1536
layer surface mapped: namespace=bunny-assistant layer=Top     role=AssistantPanel geometry=460x1480+2084+48
layer surface mapped: namespace=bunny-approval  layer=Overlay role=ApprovalPanel  geometry=640x520+960+120
layer surface mapped: namespace=bunny-command-palette layer=Overlay role=CommandPalette geometry=720x420+920+96
layer surface mapped: namespace=bunny-quick-settings  layer=Overlay role=QuickSettings  geometry=380x520+2164+40
layer surface mapped: namespace=bunny-notification-center layer=Top role=NotificationCenter geometry=420x1520+2124+40
```

## How they were captured

`--capture-frame <path>` is an **operator-only** flag read at start-up. There is
no Wayland interface for it, no client can request it, and it cannot be
triggered by a running application. The rule that ordinary clients may not
screenshot through the compositor is unchanged:
`unrestricted_compositor_screenshot_permitted()` returns false for every
application, and capture through the portal path additionally requires a visible
privacy indicator.

Regenerate with:

```
python3 visual-v3/tools/screenshot.py
```
