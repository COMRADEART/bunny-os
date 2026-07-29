# System requirements

Evidence-backed stable minimums are not established. The existing conservative planning profiles are x86-64 UEFI, at least 4 GiB RAM/40 GiB storage for base desktop; 8 GiB/64 GiB cloud profile; 16 GiB/96 GiB small local model; 32 GiB/160 GiB medium model; and 16 GiB/128 GiB developer profile. These are installation guards, not measured stable performance claims.

Graphics/device support is model-specific. Network is optional for local-only operation. Secure Boot and TPM are not qualified; TPM is never mandatory and cannot replace password/recovery fallback. Legacy BIOS and ARM64 are unsupported in the current design. Local-model CPU/RAM/VRAM needs must be measured for each signed model/runtime.
