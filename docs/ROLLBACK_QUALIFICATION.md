# Rollback qualification

Test kernel, graphics, shell, broker, portal, migration, health-check, and user-requested rollback from an installed signed candidate. Compare content-free preservation manifests for home, Bunny database/memory, credential references, plugins, models, workspaces, applications, settings, checkpoints, and documents.

Image-managed system files roll back with the deployment; persistent `/var` and user data do not automatically reverse. Irreversible database/config migrations must be declared before update. No rollback execution is recorded, so rollback is unqualified.
