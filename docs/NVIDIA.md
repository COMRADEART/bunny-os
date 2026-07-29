# NVIDIA policy

The Phase 3 beta definition does not bundle or automatically install NVIDIA proprietary drivers. Fedora's available open path and Safe Graphics are the conservative defaults, labelled experimental until tested.

An optional proprietary path requires all of the following before it can appear: exact PCI device and supported branch detection; reviewed Fedora-compatible repository and redistribution/legal policy; exact kernel ABI; signed package and module provenance; Secure Boot/MOK enrollment; Wayland and XWayland tests; suspend/resume and multi-display; local-model CUDA isolation; update/rollback; and safe removal through a prior bootc deployment.

Vendor detection alone is insufficient. A driver cannot be described as Secure Boot compatible merely because enrollment UI exists. The hardware report must distinguish package validation in CI from a real NVIDIA system test.

