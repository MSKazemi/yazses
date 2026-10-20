"""Host reads shared by more than one OS backend and owned by none of them.

Lives beside `base.py` rather than under `platform/linux/` because the macOS bundle ships no
Linux backend (see the note on `BSD_PREFIXES` in `base.py`): a shared helper that sat in
`platform/linux/` would crash a frozen .app that merely wanted to know how much RAM it has.
"""
from __future__ import annotations

import os


def sysconf_ram_gb() -> float | None:
    """Installed RAM in GB from ``os.sysconf``, or ``None`` where the OS will not say. Pure of
    side effects beyond the read; ``None`` and never ``0.0`` -- see ``HostInfo.ram_gb``."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return round(pages * page_size / 1e9, 1)
    except (AttributeError, ValueError, OSError):
        pass
    return None
