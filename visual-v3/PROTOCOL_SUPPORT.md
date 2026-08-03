# Protocol support

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## How this was established

Compilation is not evidence. Every row below was checked by running `wayland-info` — an independent protocol client — against the running compositor and recording which globals it could actually bind.

**19 globals advertised**, 22 protocols assessed.

A protocol claimed working that the client could not see, or claimed absent that the client *could* see, is reported as a contradiction and fails the harness. Contradictions in this run: **0**.

## Matrix

| Protocol | Status | Advertised | Version | Notes |
|---|---|---|---|---|
| `wl_compositor` | inherited from framework | yes | 5 | Core. Provided by smithay's compositor module. |
| `wl_shm` | inherited from framework | yes | 2 | Core shared-memory buffers. |
| `wl_seat` | inherited from framework | yes | 9 | Core input seat. |
| `wl_output` | implemented | yes | 4 | Bunny creates and configures the output globals. |
| `xdg_wm_base` | implemented | yes | 6 | Bunny implements the window-management policy on top. |
| `xdg_activation` | implemented | yes | 1 | Honoured as attention, never as a focus grant. |
| `xdg_decoration` | implemented | yes | 1 | Server-side decorations are requested. |
| `xdg_output` | inherited from framework | yes | 3 | Enabled via OutputManagerState::new_with_xdg_output. |
| `presentation-time` | inherited from framework | yes | 2 | Clock is CLOCK_MONOTONIC. |
| `viewporter` | inherited from framework | yes | 1 | Surface scaling and cropping. |
| `fractional-scale` | inherited from framework | yes | 1 | Needed for 4K at 200% and mixed-DPI layouts. |
| `relative-pointer` | inherited from framework | yes | 1 | Required by games and 3D applications. |
| `pointer-constraints` | not implemented | no | — | Available in smithay but not wired up in V3. Pointer lock and confinement do not work; applications that need them will misbehave. |
| `text-input` | inherited from framework | yes | 1 | The client half of input methods. |
| `input-method` | not implemented | no | — | The compositor half needs popup placement policy V3 did not write. Without it there is no on-screen keyboard and no CJK input method, which is an accessibility and internationalisation gap, not a cosmetic one. |
| `idle-inhibit` | implemented | yes | 1 | Tracked so a video player can hold the screen on. |
| `linux-dmabuf` | not implemented | no | — | Needs a GPU device to advertise formats against. The nested software renderer on this host has none, so clients fall back to wl_shm. Required for hardware video decode. |
| `screencopy` | intentionally unsupported | no | — | smithay 0.7 implements no screencopy protocol at all. This is the blocker behind the screencast portal, and it is a framework gap rather than a Bunny decision. |
| `layer-shell` | implemented | yes | 4 | Every piece of Bunny chrome depends on it. |
| `session-lock` | implemented | yes | 1 | The lock screen's surface role. |
| `foreign-toplevel-management` | not implemented | no | — | Available in smithay. Not enabled in V3: it lets any client enumerate every window, so it wants a security-context restriction before it is turned on. |
| `data-control` | intentionally unsupported | no | — | Deliberately off. It grants unrestricted clipboard read to any client that binds it, which is a clipboard-stealing capability with no consent step. |

## What is missing, and what it costs

6 of the evaluated protocols are not advertised. The consequences are not cosmetic:

- **`pointer-constraints`** — not implemented. Available in smithay but not wired up in V3. Pointer lock and confinement do not work; applications that need them will misbehave.
- **`input-method`** — not implemented. The compositor half needs popup placement policy V3 did not write. Without it there is no on-screen keyboard and no CJK input method, which is an accessibility and internationalisation gap, not a cosmetic one.
- **`linux-dmabuf`** — not implemented. Needs a GPU device to advertise formats against. The nested software renderer on this host has none, so clients fall back to wl_shm. Required for hardware video decode.
- **`screencopy`** — intentionally unsupported. smithay 0.7 implements no screencopy protocol at all. This is the blocker behind the screencast portal, and it is a framework gap rather than a Bunny decision.
- **`foreign-toplevel-management`** — not implemented. Available in smithay. Not enabled in V3: it lets any client enumerate every window, so it wants a security-context restriction before it is turned on.
- **`data-control`** — intentionally unsupported. Deliberately off. It grants unrestricted clipboard read to any client that binds it, which is a clipboard-stealing capability with no consent step.

## Bunny defines no private protocol

Every interface the shell speaks is a standard one. A private protocol would make every Bunny shell component unusable outside Bunny and would put Bunny in the position of maintaining an interface contract — a cost worth paying only for a capability no standard protocol covers, and V3 found none.

The one candidate for V4 is a privileged channel for approval surfaces that an ordinary client must not be able to impersonate. See `SECURITY_MODEL.md`.
