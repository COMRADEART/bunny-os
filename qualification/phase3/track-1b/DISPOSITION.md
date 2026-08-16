# Track 1b — Retained-input package publication

**Disposition: NOT_RUN — AUTHENTICATION BLOCKED**

Recorded 2026-08-16, Phase 3 (User Journey, Persistence & Legacy Issue
Closure), Part 15.

## What was attempted

Publication of the retained build inputs (base image, builder image,
package snapshot) to GitHub Packages via
`scripts/supply-chain/publish-retained-inputs.sh` requires a GitHub token
with `write:packages` in the environment that runs the script (the Fedora
WSL builder, where the retained inputs live under
`/var/lib/bunny-retention`).

Two credential paths were tried in this session and both were refused by
the session's permission policy — correctly, since each moves a live
credential across an environment boundary:

1. Piping `gh auth token` from the Windows host into a file readable by
   the WSL builder.
2. Invoking `gh.exe` (Windows credential store) through WSL interop from
   inside the builder.

No workaround was attempted. No publication happened. No
package-publishing evidence exists, and none is claimed.

## Verified while investigating

The Windows-side `gh` login exists and its token carries the
`write:packages` scope (checked with `gh auth status` on the host; the
token itself never left the host).

## Exactly what remains required

An operator (not the agent) runs, in a Windows terminal:

```
wsl -d FedoraLinux-44 -u root -- bash -lc 'cd /root/bunny-os && GITHUB_TOKEN=$(gh.exe auth token) bash scripts/supply-chain/publish-retained-inputs.sh --kind base'
```

then the same command with `--kind builder` and `--kind snapshot`.

The interop call resolves the token inside the operator's own session, so
the credential is used where it lives; the script logs the digests it
pushes, which become the Track 1b evidence when this is run.
