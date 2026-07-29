# Local-model integration

Bunny's upstream verified model/runtime registry remains authoritative. Bunny OS reports local hardware evidence but never converts device detection into runtime support. Bunny must run its benchmark/health check before marking a backend verified and safely fall back to CPU or a disclosed hosted provider only after user choice.

Models live in the owning user's Bunny data area outside the image. First boot downloads none. First use must show model size/license, request confirmation, enforce a configurable quota, verify digest/runtime compatibility, and avoid provider credentials in model workers. Shared models and system-wide model service are postponed until multi-user ACL, quota, update and eviction behavior are designed.

