# Power, pressure, and performance qualification

Measure idle power, suspend drain/wake, display/Wi-Fi/Bluetooth/GPU power, Bunny background work, local-model idle state, indexing, boot stages, interactive shell, and desktop startup on each named test system. Use actual `systemd-analyze`, power, memory, storage, and hardware logs; host Python microbenchmarks are not substitutes.

Power saver, Balanced, and Performance remain platform profiles when supported. Local-model servers start on demand and stop before user applications under pressure. OOM handling records events, pauses unattended work safely, warns the user, and never silently kills user applications by Bunny policy. Storage preflight protects `/home`, reserves update space, previews cleanup, and bounds logs/crash/model/checkpoint/Flatpak growth. No candidate measurements exist.
