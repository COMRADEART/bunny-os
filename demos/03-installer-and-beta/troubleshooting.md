# Troubleshooting

- No artifact: provision the Fedora builder and inspect the first failed prerequisite; do not invent an output filename.
- Media failure: stop, reacquire media/key metadata, and do not continue after a critical signature error.
- No target: check installation-media, mounted, read-only, size, sector, RAID/multipath, and firmware warnings.
- Display failure: boot Safe Graphics; do not disable Secure Boot as a first remedy.
- Install failure: export redacted logs, record the exact stage, unmount/close mappings through the adapter, and do not blindly retry writes.
- Boot failure: use Recovery Tools and existing firmware entries; keep the original OS entry intact.

