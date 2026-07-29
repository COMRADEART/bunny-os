# Bunny Terminal

Bunny Terminal launches the normal GNOME Terminal. Tabs, profiles, splits where the terminal supports them, copy/paste, search, shell startup, and exit status remain conventional terminal features; Bunny does not replace the user's shell.

`bunny-terminal propose` creates a non-executing command proposal. It shows the exact command, resolved working directory, leading environment assignments, classification, sandbox/checkpoint requirements, approval requirement, dry-run availability, editability, and cloud-history disclosure. `executesAutomatically` is always false.

The classifier tokenizes shell structure, splits pipelines/compound commands, inspects executable and subcommand semantics, and treats redirects as writes. Categories are `read_only`, `workspace_write`, `network_action`, `system_change`, `destructive`, and `unknown`. Shell wrappers, command substitution, and unknown executables are high risk. This is a policy aid, not a replacement for Bunny capability checks or OS sandbox enforcement.

```text
bunny-terminal
bunny-terminal propose --cwd /project -- git status
bunny-terminal propose --cwd /project -- npm install
bunny-terminal propose --cwd /project -- rm -rf build
```

A future Execute button must revalidate the edited proposal, request any required Bunny permission, create a checkpoint where required, display environment and cwd again, and enter the selected sandbox. Terminal history may not be sent to a provider without disclosure and approval.
