# Schemas

- `bunny-os-contract.schema.json` is contract `1.0.0`, independent of Bunny app protocol v3.
- `bunny-os-update-manifest.schema.json` is update-manifest schema 1. Signatures cover canonical UTF-8 JSON with the `signature` field removed.
- `bunny-artifact.schema.json` describes a digest-pinned Bunny Desktop/Core artifact accepted into `/opt/bunny/releases/<version>`. A placeholder is explicit and cannot be mistaken for a verified Bunny build.

Schema removals or meaning changes require a major version. Additive optional fields require a schema update, generated compatibility fixtures, and one full image gate.
