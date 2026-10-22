"""Limits and choices for packs: size, disk space, deadline, capability, GC (pure).

Every number a pack install is judged by lives here, so the install transaction, the
CLI price line and the tests read one source.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from yazses.packs.manifest import IndexEntry

__all__ = [
    "BASE_DEADLINE_S",
    "DISK_MARGIN",
    "MIN_RATE_BYTES_PER_S",
    "PACK_INSTALL_METHODS",
    "PACK_MAX_BYTES",
    "Capability",
    "GcPlan",
    "capability",
    "deadline_s",
    "disk_problem",
    "disposition",
    "gc_plan",
    "human_bytes",
    "max_download_bytes",
    "required_free_bytes",
    "size_problem",
]

#: Under GitHub's "under 2 GiB" per-release-asset limit (ADR-028 §4a).
PACK_MAX_BYTES = int(1.9 * (1 << 30))
#: Free space needed beyond archive + unpacked tree (ADR-028 §5: "plus 10 %").
DISK_MARGIN = 0.10
#: The floor a size-proportional deadline assumes: 50 kB/s (ADR-028 §4a).
MIN_RATE_BYTES_PER_S = 50_000
#: Equal to ``installer_update.DOWNLOAD_DEADLINE_S`` — restated rather than imported so
#: the runtime hook's import closure stays free of ``urllib``; a test pins the equality.
BASE_DEADLINE_S = 30 * 60.0

#: Install methods whose users may install packs. Phase 1 is the Inno ``.exe`` (winget
#: rides with it: ADR-027 records that the two cannot be told apart). Chocolatey and
#: Scoop join only after their checklist items pass (spec Phase 2) — until then they
#: keep the "install from PyPI" answer, which is the conservative one.
PACK_INSTALL_METHODS = frozenset({"windows-installer"})


def human_bytes(n: int) -> str:
    """``0.3 MB``, ``21 MB``, ``1.2 GB`` — decimal, as download sizes are quoted."""
    if n < 1_000_000:
        return f"{max(n, 0) / 1e6:.1f} MB" if n >= 50_000 else f"{max(n, 0) / 1e3:.0f} kB"
    if n < 10_000_000:
        return f"{n / 1e6:.1f} MB"
    if n < 1_000_000_000:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e9:.1f} GB"


def size_problem(entry: IndexEntry) -> str | None:
    if entry.size > PACK_MAX_BYTES:
        return (
            f"the {entry.name} add-on is {human_bytes(entry.size)}, above the "
            f"{human_bytes(PACK_MAX_BYTES)} ceiling, so it was not downloaded"
        )
    return None


def max_download_bytes(entry: IndexEntry) -> int:
    """What ``download_verified`` may accept: the index's exact size, never the default
    installer cap (ADR-028 §4a)."""
    return min(entry.size, PACK_MAX_BYTES)


def required_free_bytes(entry: IndexEntry) -> int:
    return math.ceil((entry.size + entry.unpacked_bytes) * (1 + DISK_MARGIN))


def disk_problem(entry: IndexEntry, free_bytes: int | None) -> str | None:
    """Why the disk cannot take this pack, or ``None``. Unknown free space is not a
    refusal: the download's own failure will say so, and a guard that fires on "could
    not tell" is the kind ADR-021 says teaches people to ignore guards."""
    if free_bytes is None:
        return None
    need = required_free_bytes(entry)
    if free_bytes < need:
        return (
            f"the {entry.name} add-on needs {human_bytes(need)} free and only "
            f"{human_bytes(free_bytes)} is available. Free some space and try again"
        )
    return None


def deadline_s(size: int) -> float:
    """``max(30 min, size / 50 kB/s)``: a big pack on a slow link is not cut off, and a
    stalled connection still dies on the 30 s read timeout."""
    return max(BASE_DEADLINE_S, size / MIN_RATE_BYTES_PER_S)


@dataclass(frozen=True)
class Capability:
    ok: bool
    reason: str = ""
    #: ``ok``, ``not-frozen``, ``unsupported`` (OS or package format), ``method``
    #: (a channel not yet allowed) or ``elevated`` — so a caller can tell "fall back to
    #: the existing answer" from "refuse and say why".
    code: str = "ok"


def capability(
    *,
    frozen: bool,
    runtime_supported: bool,
    profile_can_add_packs: bool,
    profile_label: str,
    install_method: str,
    elevated: bool,
) -> Capability:
    """May this process install and mount packs? ``reason`` is a user sentence when not.

    Elevation is checked last, so a non-capable install gets the more useful answer
    (where to get the feature) rather than "run unelevated".
    """
    if not frozen:
        return Capability(False, "this install is not a frozen bundle; it installs "
                                 "libraries from PyPI instead", "not-frozen")
    if not runtime_supported or not profile_can_add_packs:
        return Capability(False, f"add-ons are not available in {profile_label} yet",
                          "unsupported")
    if install_method not in PACK_INSTALL_METHODS:
        return Capability(False, (
            f"add-ons are not enabled yet for a YazSes installed with {install_method}; "
            "the installer from the releases page supports them"
        ), "method")
    if elevated:
        return Capability(False, (
            "YazSes is running as administrator. Add-ons are never loaded or installed "
            "in an elevated process, because their files are writable by your user "
            "account. Run YazSes normally"
        ), "elevated")
    return Capability(True)


def disposition(status: str | None, *, complete: bool, damaged: bool) -> str:
    """What to do with one installed tree: ``mount``, ``stale``, ``quarantine`` or
    ``skip``.

    * no ``COMPLETE`` marker: ``skip`` — a partial tree never mounts, and it is not
      ours to delete at startup (an install may be finishing it);
    * another build id: ``stale`` — left alone for rollback, never quarantined;
    * refused (same build, wrong fields) or damaged: ``quarantine``;
    * otherwise ``mount``.
    """
    if not complete:
        return "skip"
    if status == "stale":
        return "stale"
    if status != "ok" or damaged:
        return "quarantine"
    return "mount"


@dataclass(frozen=True)
class GcPlan:
    keep: tuple[str, ...]
    delete: tuple[str, ...]


def gc_plan(
    builds: Mapping[str, float], current: str, *, started_ok: bool
) -> GcPlan:
    """Which build directories to keep (ADR-028 §6, *Rollback*).

    ``builds`` maps each build directory to the time its newest pack was installed.
    The current build is always kept. Until the current build has completed one good
    start, the most recent *other* build is kept too, because a failed ADR-027 update
    relaunches the old version and it needs its packs. Everything else goes.
    """
    keep = {current}
    others = sorted((c for c in builds if c != current), key=lambda c: builds[c], reverse=True)
    if not started_ok and others:
        keep.add(others[0])
    delete = tuple(c for c in sorted(builds) if c not in keep)
    return GcPlan(tuple(sorted(keep)), delete)
