# Data preservation

Tests compare SHA-256 manifests, never content, for `/home`, Bunny database/memory, provider credential references, local models, plugins, workspace metadata, user applications/settings, checkpoints, and documents. Apply this to update, rollback, recovery, preserve-data reinstall, failed update, and failed migration.

Any unexpected digest change fails the scenario and names only the dataset. Expected migrations require a versioned reversible plan or a pre-migration backup with verified restore. No data-preservation VM execution has run.
