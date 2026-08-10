# Generating Bunny Companion character assets

Generated assets are external inputs until `companion.characters` validates and imports them. Generation does not establish authorship, license, likeness consent, voice ownership, safe content, renderer compatibility, or integrity. Keep the original source, generator terms, creator/license statement, and hashes with the package. Do not put API keys, provider credentials, executable code, scripts, or model plug-ins in a character package.

Use the prompts in `docs/templates/companion-character-prompts.md` as starting points. Replace bracketed values with a reusable identity specification. Keep clothing, proportions, palette, markings, accessories, and camera conventions identical across prompts. Reference sheets use neutral lighting and a plain background; sprites/poses use a transparent background. Ask for no embedded text, watermark, UI, logo, or signature.

The version 1 package manifest is described by `schemas/companion-character-package.schema.json`. A package needs a licensed creator identity, supported renderer, thumbnail, static raster fallback, declared/hash-pinned assets, rig/skeleton metadata, every required animation mapping, lip-sync metadata, expression mapping, honest resource estimates, minimum renderer, and optional prompt/generation provenance. `docs/templates/character-package.template.json` is intentionally not importable until every placeholder and digest is replaced.

Voice is separate from a character package. Bunny OS does not clone a voice, accept an ownership assertion on the user's behalf, or upload a voice sample automatically. A future voice-import workflow must obtain explicit consent and documented ownership before any sample leaves the device.
# Producing Bunny Companion Character Assets

This workflow applies equally to hand-drawn, photographed, procedurally
generated, and generative-tool output. Bunny OS does not call a commercial
image or video API. Creators use tools outside the package, review the output,
convert it to static PNG/WebP frames, write a data-only manifest, and send the
result through the same validator/importer as every other package.

## 1. Establish a reference

Choose a fixed canvas no larger than 4,096 by 4,096 pixels. Record character
scale, camera, lighting, clothing, accessories, palette, and the transparent
safe margin. Create a reference sheet with front, three-quarter, side, and back
views in a neutral pose and neutral light. Use a plain background while
designing; remove it during export. Reject text, watermarks, cropped limbs,
camera changes, and inconsistent accessories.

The reusable reference-sheet prompt is in
`docs/templates/companion-character-prompts.md`. Generated provenance and source
prompt metadata are optional. If retained, keep them descriptive and remove
credentials, private URLs, personal data, seeds that encode secrets, and tool
session identifiers.

## 2. Produce state references

Create expression references for neutral, listening, thinking, speaking,
happy/success, concerned, warning, error, and sleeping. Create motion references
for idle, listening, thinking, typing/working, speaking, success, warning,
error, and walking/repositioning. Each piece of required information must also
have a text description; do not rely on color or motion alone.

Use fixed camera/canvas/scale and consistent frame spacing. A loop must end in a
pose that joins its first frame cleanly. Avoid flashes, rapid high-contrast
changes, camera motion, embedded captions, and decorative motion that cannot be
disabled.

## 3. Export safe frames

Export each frame as a static PNG or static WebP. All render frames in one
schema-1 package must share the declared canvas size. APNG, animated WebP, SVG,
HTML, video, Lottie, fonts, shaders, scripts, and executable project files do
not belong in a package. Keep editable source files outside the installable
package.

Use short, package-relative POSIX paths such as `assets/idle-01.png`. Do not use
absolute paths, `..`, backslashes, URLs, links, or files outside the root. Keep
every frame under 64 MiB encoded and 64 MiB decoded. Use at most 240 frames in
one animation and no more than 512 assets in a package.

## 4. Build the manifest

For every file, calculate SHA-256 and exact byte size. For raster assets, record
width and height. Define at least an idle animation, a static fallback, a
thumbnail, a non-empty license file, the bubble anchor, bounding box, safe
margins, and the state/expression/mouth maps. Per-frame `durationMs` is the
timing authority.

Start from the normative schema and reference implementation:

```text
schemas/companion-character-package-v1.schema.json
assets/companion/characters/default-bunny/manifest.json
```

Do not copy the reference package's digests. Digests must describe the exact
bytes in the new package. Do not put API tokens, passwords, authorization
headers, private keys, or provider credentials in provenance or prompt
metadata.

## 5. Validate and import

Run validation before sharing:

```text
bunny-os --json companion character validate /path/to/package
```

Then exercise missing-state resolution and the renderer:

```text
bunny-os --json companion renderer explain
bunny-os --json companion renderer demo
```

Import only after validation:

```text
bunny-os --json companion character import /path/to/package-or.zip
bunny-os --json companion character select <package-id> --digest <package-digest>
```

Import verifies integrity and installs to a digest-qualified directory. It does
not establish that the creator is trustworthy. Keep the editable source,
license evidence, and generation notes separately; packages deliberately
contain only runtime data and tracked metadata.

## 6. Review checklist

- All views, clothing, accessories, scale, canvas, and camera are consistent.
- No watermark, text, cropped limb, surprise object, or background residue.
- Alpha edges look correct at 0.5x, 1x, 2x, and 3x scale.
- Idle and work loops join cleanly and remain legible at reduced frame rate.
- Listening, speaking, warning, error, and approval meanings are distinct in
  shape/text, not only color.
- Reduced-motion first frames communicate the same state without animation.
- Mouth shapes return to neutral and missing shapes have a useful fallback.
- Bubble anchor and safe margins work on both sides and near every screen edge.
- License/copyright/creator fields are accurate and the license file is present.
- Every package file is declared, hashed, bounded, and data-only.
- The validator, importer, fallback diagnostics, and vertical slice pass.
