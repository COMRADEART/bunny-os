# Recovery keys

When encryption is enabled, the installer generates a high-entropy, human-transcribable key with unambiguous characters. The user can display, print, or explicitly save it to removable or selected secure storage. A re-entry or equivalent confirmation is required before completion.

The key is never automatically saved to the installed system, embedded in initramfs, written to a Kickstart output, logged, included in diagnostics, or uploaded. Skipping is allowed only if the selected Anaconda path permits it and after a clear permanent-data-loss warning.

The UI explains that the key may be needed after TPM failure, firmware/Secure Boot change, motherboard replacement/reset, password loss, or recovery maintenance. Bunny cannot reconstruct a lost key. The user should keep at least one protected offline copy separate from the computer.

Host tests cover generation format, constant-time confirmation, incorrect-key rejection, and audit redaction. They do not demonstrate a LUKS keyslot or boot unlock.

