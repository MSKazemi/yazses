"""macOS host description."""
from __future__ import annotations

import platform
import sys

from yazses.platform.base import HostInfo
from yazses.platform.hostfacts import sysconf_ram_gb


class MacosHost:
    def describe(self) -> HostInfo:
        return HostInfo(
            platform_name=sys.platform,
            os_name="macOS",
            os_version=platform.mac_ver()[0] or platform.release(),
            ram_gb=sysconf_ram_gb(),
            fixed_session_type="macos",
        )
