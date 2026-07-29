#!/usr/bin/bash
set -euo pipefail

/usr/bin/systemctl start bunny-health-check.service
/usr/bin/systemctl is-active --quiet bunny-system-broker.socket
/usr/bin/test -s /var/lib/bunny-os/health/status.json

