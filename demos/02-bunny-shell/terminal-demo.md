# Terminal demo

Open the normal terminal with Super+T. Compare:

```text
bunny-terminal propose --cwd "$PWD" -- git status
bunny-terminal propose --cwd "$PWD" -- npm install
bunny-terminal propose --cwd "$PWD" -- rm -rf build
bunny-terminal propose --cwd "$PWD" -- mystery-tool --go
```

Verify cwd/environment/risk/editability/dry-run/checkpoint/sandbox/approval fields and `executesAutomatically: false`. Do not execute the destructive fixture.
