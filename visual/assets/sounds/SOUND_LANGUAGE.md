# Bunny sound language

Sounds are optional, short (80–420 ms), soft, recognizable, non-musical, and
non-startling. They follow the system event-sound setting and accessibility
preferences. No state relies on sound alone.

| Event | Character | Maximum |
| --- | --- | ---: |
| Login | two quiet rising air tones | 420 ms |
| Logout | two quiet descending air tones | 360 ms |
| Notification | one rounded dry tap | 180 ms |
| Approval requested | paired low wood taps | 280 ms |
| Approval granted | soft upward interval | 260 ms |
| Approval denied | single muted downward tone | 240 ms |
| Action completed | short clear breath | 220 ms |
| Action failed | two low dry pulses | 300 ms |
| Critical warning | three spaced, bounded pulses | 420 ms |

Sound generation and mastering are deferred until real hardware loudness and
assistive-technology coexistence can be tested. Visual V1 defines the event
contract and never installs placeholder audio that could imply a false result.
