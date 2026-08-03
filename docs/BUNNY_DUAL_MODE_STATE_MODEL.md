# Bunny dual-mode state model

> VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN

`visual-mode` selects `regular` or `character`; `layout-mode` independently
selects `normal`, `compact`, or `focus`. Both dimensions feed one presentation
snapshot and one shared action registry.

| Observed assistant state | Character pose | Required guard |
| --- | --- | --- |
| Ready | `idle-neutral` | Bunny enabled |
| Typing | `typing` | Bunny enabled |
| Thinking | `thinking` | Bunny enabled |
| Waiting for approval | `requesting-approval` | A real approval request exists |
| Running | `task-running` | Backend reports active work |
| Completed | `task-completed` | `resultConfirmed=true` |
| Celebrating | `celebrating` | Confirmed result and milestone |
| Warning | `warning` | Recoverable concern is observed |
| Failed | `error` | Failure is confirmed |
| Offline | `offline` | Connectivity state is offline |

Regular Mode bypasses this mapping and renders activity, context, suggestions,
and privacy information in the same space. No character placeholder survives.

