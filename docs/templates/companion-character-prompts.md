# Bunny Companion character prompt templates

Use one identity block in every prompt:

> Reusable character identity: [name and species/body type]. Consistent [clothing], [proportions], [palette/markings], [hair/fur], and [accessories] in every frame and camera angle. Preserve silhouette and facial geometry. No embedded text, watermark, logo, UI, or signature.

## Character reference sheet

> [Identity block]. Professional animation character reference sheet with full-body front, exact side, three-quarter, and back views, plus a neutral face close-up. Neutral white lighting, orthographic-feeling camera, plain light-gray background, relaxed neutral pose, consistent scale and ground line. Show construction-relevant details without labels or embedded text.

## Front, side, and back views

> [Identity block]. Three separate full-body turnaround panels: straight front, exact 90-degree side, and straight back. Same neutral standing pose, same camera height and distance, neutral lighting, plain background, no perspective exaggeration, all limbs and accessories visible, no embedded text.

## Facial expressions

> [Identity block]. Consistent close-up expression grid for neutral, greeting, listening, thinking, focused work, speaking phoneme shapes, success, warning, error, waiting, and sleeping. Fixed camera and lighting, identical head proportions and accessories, plain background, no embedded text.

## Transparent-background poses

> [Identity block]. Full-body isolated poses for idle, greeting, listening, thinking, planning, typing, researching, speaking, presenting, success, warning, error, waiting, sleeping, and walking/repositioning. Transparent background, clean silhouette, consistent camera angle and scale, no crop, no shadow outside the character, no embedded text.

## Idle loop

> [Identity block]. Seamless [duration]-second idle loop, fixed camera, transparent or plain background, subtle breathing and occasional blink, first and last frame identical, no camera motion, no lighting change, no position drift, no embedded text.

## Listening loop

> [Identity block]. Seamless [duration]-second listening loop, fixed camera, attentive posture, one subtle ear/head response and breathing, first and last frame identical, transparent or plain background, no camera motion or position drift.

## Thinking loop

> [Identity block]. Seamless [duration]-second thinking loop, fixed camera, quiet eye movement and restrained thoughtful gesture, first and last frame identical, transparent or plain background, consistent lighting and proportions.

## Speaking loop

> [Identity block]. Seamless [duration]-second neutral speaking loop with restrained mouth shapes suitable for later lip-sync, fixed head position, transparent or plain background, first and last frame identical, no baked audio, no embedded text.

## Working loop

> [Identity block]. Seamless [duration]-second focused working/typing loop, fixed camera, hands and accessories remain structurally consistent, no prop appears or disappears, first and last frame identical, transparent or plain background.

## Success and error reactions

> [Identity block]. Two separate short animation clips: restrained success reaction and clear but non-alarming error reaction. Fixed camera, transparent or plain background, return to the neutral pose at the end, consistent proportions/accessories, no embedded text.

## 2D sprite sheet

> [Identity block]. Production 2D sprite sheet for idle, greeting, listening, thinking, planning, typing, researching, speaking, presenting, success, warning, error, waiting, sleeping, and walking/repositioning. Transparent background, identical cell dimensions, consistent ground point and scale, complete uncropped silhouette, each loop has evenly timed frames and matching first/last pose, no gutters containing text.

## 3D model reference

> [Identity block]. Neutral A-pose 3D modeling reference with front, exact side, back, and three-quarter views; neutral lighting and plain background; symmetrical anatomy where intended; clothing layers, accessory attachment points, hands, face, and mouth interior clearly visible; no foreshortening or embedded text.

## Texture reference

> [Identity block]. Flat, neutral-light material and texture reference showing exact palette, fabric/fur/skin response, roughness/metallic intent, markings, accessory materials, and front/side/back continuity. Plain background, color-stable lighting, no dramatic grading, no embedded text.
# Bunny Companion asset prompt templates

These are tool-neutral creative briefs. Replace bracketed fields, keep a copy
of the final text if provenance is desired, and review the result manually.
Generated output receives no special trust: export it as static frames and run
the normal Bunny package validator/importer.

## Character reference sheet

```text
Create an original character reference sheet for [CHARACTER NAME], a
[SHORT CHARACTER DESCRIPTION]. Show separate full-body front, three-quarter,
side, and back views, plus a neutral standing pose. Use neutral even lighting,
a plain [BACKGROUND COLOR] background, a fixed orthographic-like camera, and
the same character scale in every view. Keep [CLOTHING], [ACCESSORIES], colors,
proportions, markings, and silhouette exactly consistent. Show all limbs and
ears/tail/accessories fully inside the canvas. No action pose, no perspective
distortion, no text, no labels, no logo, no watermark, no cropped limbs, no
extra character, and no background objects. This sheet is a consistency
reference, not an animation frame.
```

## Expression sheet

```text
Using the approved [CHARACTER NAME] reference without changing clothing,
accessories, proportions, camera, scale, lighting, or palette, create a grid of
separate full-head or full-body expression references: neutral, listening,
thinking, speaking, happy/success, concerned, warning, error, and sleeping.
Keep the pose calm and the plain background uniform. Make each state readable
through silhouette, eyes, brows, posture, and mouth rather than color alone.
Avoid flashing motifs. No text, labels, watermark, cropped features, added
props, camera movement, or style drift.
```

## Animation reference set

```text
Create consistent animation reference poses for [CHARACTER NAME]: subtle idle
loop, attentive listening loop, thinking loop, typing/working loop, speaking
loop, short success reaction, warning reaction, error reaction, and
walking/repositioning loop. Preserve the approved reference design, fixed
camera, fixed character scale, fixed canvas, neutral lighting, and transparent
background. Each loop must return seamlessly to its first pose. Keep motion
small, readable, non-flashing, and suitable for a reduced-frame-rate fallback.
No camera movement, zoom, cuts, text, logo, watermark, changing clothing,
changing accessories, cropped limbs, or new objects.
```

## One animation

```text
Produce [FRAME COUNT] sequential reference frames for a seamless [STATE] loop
of [CHARACTER NAME] at [FPS] frames per second. Canvas: [WIDTH] x [HEIGHT].
Transparent background, fixed camera, fixed registration point, fixed character
scale, fixed lighting, and identical clothing/accessories in every frame. Keep
all pixels within the safe margin [TOP, RIGHT, BOTTOM, LEFT]. Frame spacing and
timing are uniform; the final pose joins the first with no pop. No camera motion,
parallax, motion blur, embedded text, watermark, cropped parts, changing canvas,
or palette drift. Deliver separate still frames, not an animated container.
```

## Mouth-shape reference

```text
Using the exact approved speaking pose for [CHARACTER NAME], create seven
registered still frames that differ only in the mouth area: closed, open-small,
open-medium, open-wide, rounded, smile, and neutral. Preserve eyes, head,
clothing, accessories, lighting, camera, canvas, scale, transparency, and pixel
registration exactly. No text, labels, watermark, additional phoneme symbols,
or motion blur. These are generic visual mouth shapes, not a claim of
phoneme-accurate lip sync.
```

## Negative constraints to append when supported

```text
text, caption, speech bubble, letters, logo, watermark, signature, cropped
limbs, cropped ears, cropped tail, duplicate limbs, extra fingers, extra
character, inconsistent costume, inconsistent accessory, changing camera,
changing scale, zoom, camera shake, background object, opaque background,
motion blur, frame border, sprite atlas labels, flashing light
```

## Sprite-production specification

Use this as a non-negotiable production note even when the generation tool does
not accept negative prompts:

```text
Canvas: [WIDTH] x [HEIGHT] pixels for every frame
Camera: fixed; no pan, tilt, zoom, roll, cut, or perspective change
Scale/registration: fixed character scale and anchor point
Background: transparent RGBA
Spacing: one still file per frame with zero-padded sequential names
Timing: [FPS] fps, also recorded as explicit durationMs per frame
Loop: last pose connects seamlessly to first
Content: no embedded text, caption, logo, watermark, or metadata overlay
Delivery: static PNG or static WebP frames; no APNG/animated WebP/video
```
