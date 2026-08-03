# Compatibility matrix

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## How this was established

Each application was launched against the running compositor on Fedora Linux 44 on WSL2, nested under WSLg, Mesa llvmpipe software renderer. An application counts as working only if the compositor observed it map a toplevel and identify itself over the protocol.

**No application was modified to make the shell appear compatible.** An application that is not installed on the measurement host is recorded as not tested — never as passing.

3 of 4 installed applications mapped a window; 14 were considered.

## Applications

| Application | Toolkit | Installed | Mapped a window | Identified as |
|---|---|---|---|---|
| GTK 4 Demo | GTK 4 | yes | yes | `org.gtk.Demo4` (wayland) |
| GTK 4 Widget Factory | GTK 4 | yes | yes | `org.gtk.WidgetFactory4` (wayland) |
| GTK 3 Demo | GTK 3 | no | — | not tested |
| Qt 6 application | Qt 6 | no | — | not tested |
| Electron application | Electron | no | — | not tested |
| Chromium | Chromium | no | — | not tested |
| Firefox | Firefox | no | — | not tested |
| foot terminal | terminal emulator | yes | yes | `foot` (wayland), `foot` (wayland) |
| Nautilus | file manager | no | — | not tested |
| GNOME Text Editor | code editor | no | — | not tested |
| Totem | media application | no | — | not tested |
| Flatpak application | Flatpak | no | — | not tested |
| xterm | XWayland (X11) | yes | **no** | — |
| xeyes | XWayland (X11) | no | — | not tested |

## Failures

- **xterm** — did not map a toplevel within 6s

### XWayland

X11 clients could not connect: V3 resolves XWayland state but does not start an Xwayland server, so no X11 client can run. The shell started and every Wayland client worked regardless, which is the property that mattered.


## Dimensions that were not measured

The phase asks about nine dimensions per application. Only *launches* was measurable here. The rest are recorded as not measured, with the reason, rather than assumed:

| Dimension | Why it was not measured |
|---|---|
| clipboardWorks | requires two cooperating clients and wl-clipboard, which is not installed |
| dialogsWork | requires interacting with each application's menus |
| inputWorks | requires synthetic input into a nested seat; the winit backend exposes no libinput seat to inject into |
| notificationsWork | requires a org.freedesktop.Notifications service, which V3 does not implement |
| portalsWork | requires a running xdg-desktop-portal session bus |
| resizingWorks | requires driving a window manager interaction; not automated in V3 |
| scalingWorks | requires a second output at a different scale; the nested backend has one output |
| screenSharingWorks | blocked: no screencopy protocol in smithay 0.7 |

## The honest summary

Native Wayland GTK 4 applications work: they connect, map, are identified from the protocol, and are composited. That is the core compatibility question and the answer is positive.

Everything else is unproven. Most of the requested ecosystem — Qt, Electron, Chromium, Firefox, a file manager, a code editor, a media player, Flatpak — was not installed on the measurement host and was therefore not tested at all. A compatibility claim covering those toolkits would be an invention.
