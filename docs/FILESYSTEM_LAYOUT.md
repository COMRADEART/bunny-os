# Filesystem layout

| Path | Ownership and lifecycle |
|---|---|
| `/` | ext4 root deployment assembled by image-builder; image-managed, not claimed universally read-only |
| `/boot`, `/boot/efi` | bootc/image-builder-managed boot artifacts and UEFI ESP; never written by Bunny |
| `/usr` | OCI-authored base and Bunny OS integration binaries; replaced by deployment |
| `/etc` | persistent administrator configuration with deployment merge semantics; credentials do not belong here |
| `/var` | persistent system state; separate from image content |
| `/home/<user>` | per-user files, Bunny XDG data/config/cache, credentials via Secret Service; Linux DAC and sessions isolate users |
| `/opt/bunny/releases/<version>` | verified, read-only Bunny release deployment |
| `/opt/bunny/current` | image-authored symlink selecting the packaged Bunny release |
| `/var/lib/bunny` | reserved for explicitly shared/system Bunny data; not the default per-user Bunny database |
| `/var/lib/bunny-os/update` | root-only manifest status, highest accepted sequence, staging metadata |
| `/var/lib/bunny-os/recovery` | root-only one-shot recovery marker and protected recovery metadata |
| `/var/lib/bunny-os/support` | non-listable searchable directory; each redacted bundle is mode 0600 and owned by its authenticated requesting user; 14-day retention |
| `/var/cache/bunny` | optional shared caches, 30-day retention; disposable |
| `/var/log/bunny` | system integration logs where files are unavoidable; journald is primary, 14-day file retention |
| `/run/bunny` | volatile socket/token/runtime directory; recreated each boot |
| `/recovery` | reserved future encrypted/removable recovery-data mount; not created or trusted by Phase 1 |

Upstream Bunny 0.2.0 currently uses per-user XDG paths. Bunny OS does not silently relocate or duplicate that data. General assistant models live under the user's Bunny data area, outside the OS image, with future quota controls. The one explicit exception is the Alpha offline speech-recognition model under `/usr/share/bunny-os/speech-models`: it is immutable OS feature data, byte-manifested and updated with the image. Plugins, model files, checkpoints, and OS deployment snapshots are different namespaces: a Bunny checkpoint never claims to roll back an OS image.

Application binaries are mode `0555`/`0444` and verified against `bunny-artifact.json`. User credentials use libsecret/Secret Service references. No provider token, static broker password, signing private key, prompt history, or user document enters an image or support bundle.
