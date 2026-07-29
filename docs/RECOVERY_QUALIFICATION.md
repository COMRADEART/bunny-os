# Recovery qualification

Independent signed recovery media must boot without the installed deployment and handle bootloader failure, invalid deployment, broken graphics/kernel, encrypted-volume issues, Bunny/plugin/shell loops, failed update, and corrupt configuration. Required tools are previous deployment, safe graphics, Safe Shell, Bunny/plugin disable, redacted diagnostics, image verification, boot repair, and qualified backup restore.

Access to encryption requires user-provided credentials that are never logged. A recovery operation records media hash/signature and preserves data. The repository has only recovery source definitions; no independent recovery ISO or execution exists.
