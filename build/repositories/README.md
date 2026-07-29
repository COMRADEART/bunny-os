# Repository snapshots

Developer builds use the Fedora repositories configured by the digest-resolved base image and record exact RPM NEVRAs. Release builds fail unless this directory contains a reviewed `fedora-44-snapshot.repo` with the single ID `bunny-fedora-snapshot`, an HTTPS `baseurl`, and both package and repository metadata signature checks enabled.

The snapshot file must point to an immutable retained Fedora 44 snapshot and declare Fedora's reviewed public `gpgkey`. `install-packages.py` disables every other repository for that build. The actual snapshot URL is release evidence and intentionally not invented in Phase 1.

