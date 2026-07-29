# Branching and releases

`main` is integration; `release/beta` and `release/stable` are protected release lines; `maintenance/<version>` receives approved backports; `security/<issue>` is restricted during embargo. Direct pushes to release/maintenance branches are prohibited. Required review, green protected gates, signed commits/tags, and source/artifact provenance apply.

Backports are minimal cherry-picks with original issue/evidence and all affected tests. Conflict resolution receives a new review. Stable tags are annotated and signed only after release approval. Hotfixes follow the security process and create a new version/candidate; no artifact or tag is reused.
