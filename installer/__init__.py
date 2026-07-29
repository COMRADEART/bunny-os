"""Bunny OS installer planning and policy package.

The package is deliberately safe to import on a developer host.  It contains no
implicit disk writes and the reference backend is simulation-only; production
execution is delegated to the selected Anaconda/Blivet/bootc adapter.
"""

PROTOCOL_VERSION = 1

