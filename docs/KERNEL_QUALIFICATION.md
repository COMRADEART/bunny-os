# Kernel qualification

No stable kernel is selected. Candidate qualification must cover boot, LUKS, Secure Boot positive/negative, graphics, Wi-Fi, Bluetooth, audio, suspend/resume, NVMe, USB, virtual machines, and optional local-model acceleration on named systems. Record default, optional hardware-enablement, and emergency fallback kernels with supported lifetime, tested update cadence, and rollback policy.

The machine-readable record is `operations/data/kernel-qualification.json`; every current test is `NOT_RUN`. Kernel changes require a new immutable candidate.
