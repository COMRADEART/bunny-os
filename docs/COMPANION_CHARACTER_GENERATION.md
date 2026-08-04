# Generating Bunny Companion character assets

Generated assets are external inputs until `companion.characters` validates and imports them. Generation does not establish authorship, license, likeness consent, voice ownership, safe content, renderer compatibility, or integrity. Keep the original source, generator terms, creator/license statement, and hashes with the package. Do not put API keys, provider credentials, executable code, scripts, or model plug-ins in a character package.

Use the prompts in `docs/templates/companion-character-prompts.md` as starting points. Replace bracketed values with a reusable identity specification. Keep clothing, proportions, palette, markings, accessories, and camera conventions identical across prompts. Reference sheets use neutral lighting and a plain background; sprites/poses use a transparent background. Ask for no embedded text, watermark, UI, logo, or signature.

The version 1 package manifest is described by `schemas/companion-character-package.schema.json`. A package needs a licensed creator identity, supported renderer, thumbnail, static raster fallback, declared/hash-pinned assets, rig/skeleton metadata, every required animation mapping, lip-sync metadata, expression mapping, honest resource estimates, minimum renderer, and optional prompt/generation provenance. `docs/templates/character-package.template.json` is intentionally not importable until every placeholder and digest is replaced.

Voice is separate from a character package. Bunny OS does not clone a voice, accept an ownership assertion on the user's behalf, or upload a voice sample automatically. A future voice-import workflow must obtain explicit consent and documented ownership before any sample leaves the device.
