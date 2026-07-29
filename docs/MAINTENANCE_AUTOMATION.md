# Maintenance automation

Read-only jobs may alert on update metadata, vulnerability feeds, package state, keys/metadata expiry, broken mirrors, stale recovery images, unsupported kernels, and deprecated application runtimes. Alerts include source, timestamp, severity, owner, and proposed action.

Automation cannot sign, publish, revoke, close an issue, lower severity, alter protected branches, or approve a gate. `operations/maintenance.py` emits `alert-only` actions. Release changes require protected human approvals.
