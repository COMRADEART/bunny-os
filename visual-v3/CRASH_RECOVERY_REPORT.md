# Crash recovery report

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## Result

**Bounded restart holds: True.** No scenario produced an unbounded restart loop.

## Scenario: compositor exits 1 immediately, every time

- `automaticRestartStopped`: True
- `crashRecords`: 2
- `elapsedSeconds`: 0.199
- `endedInRecovery`: True
- `guidanceMentionsGnome`: True
- `infiniteLoop`: False
- `noCredentialInRecords`: True
- `recoveryOfferedGnome`: True
- `recoveryUsableWithoutCharacterMode`: True
- `restartsAttempted`: 1
- `supervisorExitCode`: 3

## Scenario: real compositor killed with SIGKILL

- `attempts`: [{'attempt': 1, 'decision': 'restart', 'outcome': 'terminated by SIGKILL'}, {'attempt': 2, 'decision': 'recover', 'outcome': 'terminated by SIGKILL'}]
- `clientsPreserved`: False
- `clientsPreservedNote`: Wayland clients connect to the compositor's socket. When the compositor process dies the connection is lost and the clients exit. Preserving them would need a socket-handover design that smithay does not provide.
- `finalDecision`: recover
- `recoveryMarkerWritten`: True
- `restartsUsed`: 1
- `signalledDeathDetected`: True
- `stoppedRestarting`: True
- `uptimeBeforeEachKillSeconds`: [2.52, 2.52]

## The policy

The restart budget is absolute rather than rate-limited: at most three restarts for the lifetime of a session, and at most one consecutive restart after a rapid crash. A crash following a long healthy run resets the *consecutive* counter but never the *total* budget, which is what makes an endless loop impossible regardless of crash timing.

When the budget is exhausted the supervisor writes a recovery marker, prints plain-text guidance that names GNOME as the supported session, and exits 3. The systemd unit treats 3 as a handled outcome rather than a failure to restart.

## What is not preserved

**Open clients do not survive a compositor restart.** A Wayland client's connection is to the compositor's socket; when the process exits the connection is lost and the client exits with it. Preserving clients would need a socket-handover design that Smithay does not provide and V3 did not attempt. This is recorded in every crash record rather than implied.

## Usable without Character Mode

The recovery path is text only, deliberately. It has to work when Character Mode is off, when the compositor cannot start at all, and when nothing but a virtual terminal is available. A test asserts the guidance mentions GNOME and does not mention the character.
