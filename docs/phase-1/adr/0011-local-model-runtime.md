# ADR 0011 — Local-model runtime strategy

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §13.4–13.5, §12.9

## Context
`src/local/` already downloads GGUF models from Hugging Face with resumable sha256-verified downloads and supervises llama.cpp's `llama-server` on loopback. It detects only total RAM, ships CPU-only engine builds, and verifies the model file but **not the engine binary**.

## Decision
**Retain llama.cpp as the adopted engine** (C15 — Bunny's local story is a packaging of llama.cpp-class engines, not an inference contribution). Four changes:

1. **Vendor a per-asset sha256 table for the engine binary.** Models are integrity-verified and the executable that runs them is not — an asymmetry with no defensible rationale.
2. **Hardware-aware asset selection.** Feed GPU detection into engine choice so a machine with a discrete GPU does not silently run CPU inference.
3. **Add `activeParams` to the catalog and add MoE entries.** The catalog is currently 100% dense; on identical hardware a 30B-A3B MoE ran 8.3× faster than a 32B dense model. `recommend()` changes its objective from *largest dense model that fits* to *highest capability at interactive throughput* — total parameters for the fit test, active parameters for the speed test.
4. **The inference service runs outside the task sandbox** as a broker-owned service with GPU device nodes mounted into *it*, never into a task sandbox (§12.9).

## Alternatives
- *Ollama or LM Studio as the runtime* — rejected: they wrap the same engine and would add a process Bunny does not control between it and the model.
- *A custom inference engine* — rejected outright by C15.
- *GPU inside the untrusted sandbox* — rejected: gVisor's NVIDIA support pins exact driver versions, Firecracker has no passthrough, and Kata's whole-device VFIO is impossible on a single-GPU laptop.

## Consequences
The inference service is a **confused-deputy risk** — a sandboxed task could ask it to run an exfiltrating prompt. Mitigated structurally: it has **no egress and no filesystem access beyond model files.** It is a pure function from tokens to tokens.

## Risks
Upstream llama.cpp publishes no signed checksums, so the pin is tag-plus-HTTPS until Bunny vendors its own table.

## Validation required
P23 (measured tok/s is a better routing input than a bandwidth probe), P24 (hardware detection correct-or-explicitly-absent on every declared support tuple).

## Phase 0 principles satisfied
C11, C12, C15, §11.
