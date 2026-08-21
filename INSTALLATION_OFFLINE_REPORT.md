# Offline setup report

Date: 2026-08-16  
Evidence: `qualification/installer-journeys/evidence/journey-c-offline/`  
Result: **a complete installation with no network interface in the machine.**
Findings empty; wall-clock indistinguishable from the online run.

## Why a separate run existed at all

Every interactive journey ran with a user-mode NIC attached. Whether or not
the guest ever used it, none of those runs can answer the
`offline-installation` scenario: the network was *there*. Offline is a claim
the run has to earn, so `BUNNY_INSTALL_NET=none` (harness commit `24c6dae1`)
removes the device entirely — `-nic none`, no interface for anything in the
guest to quietly reach.

## The run

Journey C (unencrypted, defaults changed nowhere), no NIC:

- driver outcome **complete**, all 15 stages, target verified by the guest;
- disk verdict findings `[]`, boot entry present, account `alex`, no LUKS —
  identical in every checked property to the online journey C;
- **186 s** from launch to driver completion, against 182 s online. There is
  no offline penalty; nothing in the flow waits on a network that is not
  there.
- the network stage offers **"Continue without network"** as a first-class
  button (`result.json` shows the driver pressing it — the same button every
  journey pressed, which is the point: the flow's normal path never needed
  the network);
- the top bar in `screens/t60.png` shows no network indicator — the medium
  itself knows it has no interface. Compare the same screen in
  `journey-c/screens/`, where the indicator is present.

## Scope, stated plainly

This proves installation from the medium alone: payload, bootloader, account
and policy all come from the ISO. It does not exercise a network that
*disappears mid-install* (a different scenario), does not cover the
network-dependent parts of first-run (provider sign-in is deferred by design,
§33), and the offline variant ran journey C only — the encrypted path was
proven online. The installed system's own offline behaviour (§11's degraded
modes) is a desktop concern outside this report.
