"""Linux (and, by reuse, the BSDs and any OS with no backend) host description."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from yazses.platform.base import HostInfo
from yazses.platform.hostfacts import sysconf_ram_gb


def _os_release_field(name: str) -> str:
    """One `KEY=value` from `/etc/os-release`, unquoted, or "" where there is no such file."""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key == name:
                return value.strip().strip('"')
    except OSError:
        pass
    return ""


class LinuxHost:
    """`platform.platform()` would answer name and version at once but as one opaque string
    ("Linux-6.14.0-32-generic-x86_64-...") that no reader can group two hosts by, so the
    distribution is read from os-release and split."""

    def describe(self) -> HostInfo:
        name = _os_release_field("NAME")
        version = _os_release_field("VERSION_ID") or _os_release_field("VERSION")
        if name:
            os_name, os_version = name, version or "unknown"
        else:
            os_name = platform.system() or "unknown"
            os_version = platform.release() or "unknown"
        return HostInfo(
            platform_name=sys.platform,
            os_name=os_name,
            os_version=os_version,
            ram_gb=sysconf_ram_gb(),
        )
