# Bunny OS Visual Phase V2

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

Visual Phase V2 is an isolated GNOME/Wayland prototype for one Bunny Desktop
with two runtime-selectable presentations:

- **Regular Mode** is the default professional desktop and loads no character
  artwork.
- **Character Mode** adds one canonical guide only inside approved educational
  and assistant surfaces.

The modes share the same applications, commands, settings, action model,
approval boundary, system services, and GNOME session. Switching the
`org.bunnyos.desktop.visual-v2 visual-mode` preference reflows live surfaces;
it does not restart GNOME Shell or start a second desktop stack.

The selectable session is named `Bunny Desktop Preview`. It is additive and
never becomes the default. GNOME remains available through the existing
session entries.

## Direct commands

```text
python visual-v2/tools/visual_v2.py setup
python visual-v2/tools/visual_v2.py build
python visual-v2/tools/visual_v2.py preview
python visual-v2/tools/visual_v2.py preview-nested
python visual-v2/tools/visual_v2.py test
python visual-v2/tools/visual_v2.py a11y
python visual-v2/tools/visual_v2.py screenshots
python visual-v2/tools/visual_v2.py package
python visual-v2/tools/visual_v2.py clean
```

Generated outputs live only in `build/visual-v2/`. Mock mode requires
`BUNNY_VISUAL_MOCK_MODE=1`, is visibly labelled, and is rejected by packaging.
