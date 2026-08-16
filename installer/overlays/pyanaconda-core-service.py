# SPDX-FileCopyrightText: 2021 Red Hat, Inc.
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Derived from pyanaconda/core/service.py, which is GPL-2.0-or-later; that
# licence permits distribution under a later version, and this modified copy
# is distributed with the rest of installer/ under GPL-3.0-or-later. The
# original notice follows.
#
# Copyright (C) 2021  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ---------------------------------------------------------------------------
# BUNNY MEDIUM OVERLAY of pyanaconda/core/service.py from anaconda-core
# 44.30-2.fc44, installed by the `live-pyanaconda-service` route onto the
# installation medium only. The installed system never carries this file.
#
# Two surgical changes, both born from Journey A runs 18-24, where six
# consecutive installations died at "Error enabling service chronyd: 1"
# after the disk was fully written:
#
# 1. `enable_service` now captures systemctl's stdout+stderr and puts them
#    in the exception, because anaconda's module processes have no
#    program-log handler — the helper's words were dropped at birth, and six
#    runs produced an exit code with no sentence under it.
#
# 2. A failed enable is tolerated WHEN the unit is already wanted on the
#    target, decided by looking at the target's own filesystem rather than
#    by asking systemctl again. On this payload chronyd is preset-enabled —
#    the wants symlink ships in the image's /etc — so the enable that keeps
#    failing is semantically a no-op: the installed system runs chronyd
#    either way. A unit that is NOT already wanted still fails the install,
#    exactly as loudly as before, with better words.
#
# Everything else is byte-identical to the original.
# ---------------------------------------------------------------------------

import glob
import os
import subprocess

from pyanaconda.anaconda_loggers import get_module_logger
from pyanaconda.core.util import execWithCapture, execWithRedirect

log = get_module_logger(__name__)

__all__ = [
    "disable_service",
    "enable_service",
    "is_service_installed",
    "is_service_running",
    "restart_service",
    "start_service",
    "stop_service",
]


def _run_systemctl(command, service, root):
    """Runs 'systemctl command service'

    :param str command: command to run on the service
    :param str service: name of the service to work on
    :param str root: root to run the command in
    :return: exit status of the systemctl run
    """

    args = [command, service]
    if root != "/":
        args += ["--root", root]

    ret = execWithRedirect("systemctl", args)

    return ret


def _run_systemctl_captured(command, service, root):
    """Like _run_systemctl, but keep systemctl's own words.

    The module processes drop helper output at INFO, so the only way the
    sentence under an exit code survives is to hold on to it here.

    :return: (exit status, combined stdout+stderr)
    """
    args = ["systemctl", command, service]
    if root != "/":
        args += ["--root", root]
    try:
        completed = subprocess.run(args, capture_output=True, text=True,
                                   timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _unit_wanted(service, root):
    """Is the unit already wanted on the target, by its own filesystem?

    Asked of the files rather than of systemctl, because a systemctl that
    just failed is not the tool to adjudicate its own failure.
    """
    if not service.endswith(".service"):
        service += ".service"
    pattern = os.path.join(root, "etc/systemd/system", "*", service)
    return bool(glob.glob(pattern))


def start_service(service):
    """Start a systemd service in the installation environment

    Runs 'systemctl start service'.

    :param str service: name of the service to start
    :return: exit status of the systemctl run
    """
    return _run_systemctl("start", service, "/")


def stop_service(service):
    """Stop a systemd service in the installation environment

    Runs 'systemctl stop service'.

    :param str service: name of the service to stop
    :return: exit status of the systemctl run
    """
    return _run_systemctl("stop", service, "/")


def restart_service(service):
    """Restart a systemd service in the installation environment

    Runs 'systemctl restart service'.

    :param str service: name of the service to restart
    :return: exit status of the systemctl run
    """
    return _run_systemctl("restart", service, "/")


def is_service_running(service):
    """Is a systemd service running in the installation environment?

    Runs 'systemctl status service'.

    :param str service: name of the service to check
    :return: was the service found
    """
    ret = _run_systemctl("status", service, "/")

    return ret == 0


def is_service_installed(service, root="/"):
    """Is a systemd service installed?

    Runs 'systemctl list-unit-files' to determine if the service exists.

    :param str service: name of the service to check
    :param str root: path to the sysroot, defaults to installation environment
    """
    if not service.endswith(".service"):
        service += ".service"

    args = ["list-unit-files", service, "--no-legend"]

    if root != "/":
        args += ["--root", root]

    unit_file = execWithCapture("systemctl", args)

    return bool(unit_file)


def enable_service(service, root="/"):
    """ Enable a systemd service in the sysroot.

    Runs 'systemctl enable service'.

    :param str service: name of the service to enable
    :param str root: path to the sysroot, defaults to installation environment
    """
    ret, output = _run_systemctl_captured("enable", service, root)

    if ret != 0:
        if root != "/" and _unit_wanted(service, root):
            log.warning(
                "systemctl enable %s --root=%s exited %s, but the unit is "
                "already wanted on the target's own filesystem; the enable "
                "is a no-op and the installation continues. systemctl said: %s",
                service, root, ret, output.strip())
            return
        raise ValueError("Error enabling service %s: %s [%s]"
                         % (service, ret, output.strip()[:400]))


def disable_service(service, root="/"):
    """ Disable a systemd service in the sysroot.

    Runs 'systemctl disable service'.

    :param str service: name of the service to disable
    :param str root: path to the sysroot, defaults to installation environment
    """
    ret = _run_systemctl("disable", service, root)

    # we ignore the error so we can disable services even if they don't
    # exist, because that's effectively disabled
    if ret != 0:
        log.warning("Disabling %s failed. It probably doesn't exist", service)
