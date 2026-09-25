"""The host facts an eye-control evaluation result carries -- and the ones it refuses to.

`yazses.eyeeval.runner` is pure: it turns a task, a set of trial records and a
`Provenance` into a validated result document. This module is the impure half that
reads the machine, kept separate so every rule in the runner is testable with a
*fake* provenance and never has to touch the host.

`design/eye-control/METRICS.md` asks for the same provenance discipline
`paper/benchmark/_common.py` already uses -- "a number without the machine/software/config
that produced it is not a reproducible measurement". This maps that dataclass onto the
result envelope's `software`/`machine` sections. It deliberately does **not** import it:
`paper/` is not shipped, and `_common.py` pulls numpy and psutil at module scope, neither
of which a base install has.

## What is collected, and what cannot be

`METRICS.md` "Machine provenance" lists five things that must never be collected:
hostname, login username, serial number, MAC address, full device UUID. This module has
no function that reads any of them, and `runner.privacy_problems()` sweeps the finished
document for them anyway -- `local_identifiers()` exists **only** to feed that sweep, and
its values are never written into a result.

Two collection choices follow from that and are worth stating, because both were the
tempting shortcut:

* `platform.uname()` and `platform.node()` are not used. `uname()` carries the node name
  in field 1, so a single `asdict()` of it would have put the hostname in every result
  ever produced. Each field is read individually instead.
* the CPU model is read from `/proc/cpuinfo` (Linux) or `platform.processor()`, never from
  a subprocess. `paper/benchmark/_common.py` shells out to `lscpu`/`sysctl` for a better
  string; here the file read is preferred because it cannot spawn anything, which keeps
  this module outside the reach of `tests/test_egress_inventory.py`'s shell-out scan and
  makes a camera-less CI run cheaper.

Nothing here opens a camera, a socket or a file outside `/proc` and `/etc/os-release`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: A session type from `schema.SESSION_TYPES`, chosen from the environment.
_WAYLAND_DESKTOPS = (("gnome", "wayland_gnome"), ("kde", "wayland_kde"), ("plasma", "wayland_kde"))

#: Package versions worth recording next to an eye-control number. Only names -- the
#: version string comes from the installed distribution, and a package that is absent is
#: simply not listed rather than recorded as "0".
_RELEVANT_PACKAGES = ("mediapipe", "opencv-python", "numpy", "yazses")


@dataclass(frozen=True)
class Provenance:
    """Everything needed to interpret one eye-control evaluation result.

    Frozen and plain-data so a test can build one by hand; `collect()` is the only thing
    that reads the machine. Field names map onto the result envelope's sections rather
    than inventing a second vocabulary (`design/eye-control/METRICS.md`).
    """

    yazses_version: str = "unknown"
    git_commit: str | None = None
    python_version: str = "unknown"
    os_name: str = "unknown"
    os_version: str = "unknown"
    kernel: str = "unknown"
    arch: str = "unknown"
    cpu_model: str = "unknown"
    logical_cpus: int = 0
    ram_gb: float | None = None
    session_type: str = "headless"
    displays: tuple[dict[str, Any], ...] = ()
    packages: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalIdentifiers:
    """The strings that identify *this* machine or *this* person.

    Collected so `runner.privacy_problems()` can prove none of them reached the document.
    Never written into a result, never logged, never passed to anything else.
    """

    hostname: str = ""
    usernames: tuple[str, ...] = ()
    home_paths: tuple[str, ...] = ()


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


def _os_name_version() -> tuple[str, str]:
    """A distribution/OS name and its version, split so a table can group by name.

    `platform.platform()` would answer both at once and is what the benchmark harness
    uses, but it returns one opaque string -- "Linux-6.14.0-32-generic-x86_64-..." -- that
    no reader can group two hosts by. The split matters here because the platform
    validation matrix in `design/eye-control/EVALUATION.md` is written per OS bucket.
    """
    if sys.platform == "win32":
        return "Windows", platform.version() or platform.release()
    if sys.platform == "darwin":
        return "macOS", platform.mac_ver()[0] or platform.release()
    name = _os_release_field("NAME")
    version = _os_release_field("VERSION_ID") or _os_release_field("VERSION")
    if name:
        return name, version or "unknown"
    return platform.system() or "unknown", platform.release() or "unknown"


def _cpu_model() -> str:
    """The CPU's marketing name, without spawning a process.

    `platform.processor()` answers "x86_64" on Linux, "arm" on macOS and "" on some
    Windows builds, so it alone would stamp several unlike hosts with the same
    uninformative name -- and latency numbers may never be merged across unlike hosts,
    which is the comparison this field exists to keep honest. `/proc/cpuinfo` gives the
    real string on the one platform where the fallback is worst.
    """
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("model name", "Model"):
                return value.strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def _ram_gb() -> float | None:
    """Installed RAM in GB, or None where this OS will not say without a dependency.

    None rather than 0.0 on purpose, and for the same reason `METRICS.md` forbids
    encoding a missing metric as zero: a machine with no RAM does not exist, so a zero
    here could only ever be a failure to measure wearing the costume of a measurement.
    """
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return round(pages * page_size / 1e9, 1)
    except (AttributeError, ValueError, OSError):
        pass
    if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
        try:
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            kernel32 = getattr(ctypes, "windll").kernel32
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullTotalPhys / 1e9, 1)
        except Exception:  # noqa: BLE001 - provenance must never fail a run
            pass
    return None


def session_type(environ: dict[str, str] | None = None) -> str:
    """The `schema.SESSION_TYPES` member describing this desktop session.

    Pure given *environ*, so the mapping is tested directly rather than on whatever
    session happened to run the suite. "headless" is the honest answer for a CI runner
    and for a session type this does not recognise: guessing "x11" there would put a
    wrong bucket on an `EVALUATION.md` platform-matrix row.
    """
    env = os.environ if environ is None else environ
    if sys.platform == "win32" and environ is None:
        return "windows"
    if sys.platform == "darwin" and environ is None:
        return "macos"
    kind = env.get("XDG_SESSION_TYPE", "").strip().lower()
    if kind == "x11":
        return "x11"
    if kind == "wayland":
        desktop = env.get("XDG_CURRENT_DESKTOP", "").lower()
        for token, name in _WAYLAND_DESKTOPS:
            if token in desktop:
                return name
        return "wayland_other"
    return "headless"


def _displays() -> tuple[dict[str, Any], ...]:
    """Each display's logical rectangle, or `()` when the display server cannot be asked.

    Reuses the gaze programme's existing X11 topology reader rather than adding a second
    one, imported inside the function because a headless run must not pay for it. The
    connector name it carries (`eDP-1`) is dropped: an index is enough to tell two
    monitors apart in a result, and every field that is not needed is a field that cannot
    leak.
    """
    try:
        from yazses.gaze.display import build_topology_provider

        provider = build_topology_provider()
        if provider is None:
            return ()
        topology = provider.current_topology()
    except Exception:  # noqa: BLE001 - an unreadable desktop is "unknown", not a failure
        return ()
    return tuple(
        {
            "index": index,
            "x": display.x,
            "y": display.y,
            "width": display.width,
            "height": display.height,
            "scale": display.scale,
            "primary": display.primary,
        }
        for index, display in enumerate(topology.displays)
    )


def _package_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    out: dict[str, str] = {}
    for name in _RELEVANT_PACKAGES:
        try:
            out[name] = dist_version(name)
        except PackageNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - a broken dist-info must not fail a run
            continue
    return out


def _git_commit() -> str | None:
    """The checkout's commit SHA when this is a source tree, else None.

    Hex only, and never the branch name. A branch is free text a contributor chose and can
    carry a name, a ticket or an employer; the SHA carries nothing. `METRICS.md` asks for
    the commit "when available", and for an installed wheel it simply is not -- None, not
    a guess.
    """
    try:
        import yazses

        root = Path(yazses.__file__).resolve().parents[2]
        dot_git = root / ".git"
        if dot_git.is_file():  # a worktree or submodule: `.git` points elsewhere
            pointer = dot_git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            dot_git = Path(pointer.split(":", 1)[1].strip())
        head = (dot_git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            head = (dot_git / head.split(":", 1)[1].strip()).read_text(encoding="utf-8").strip()
        if len(head) == 40 and all(c in "0123456789abcdef" for c in head):
            return head[:12]
    except Exception:  # noqa: BLE001 - provenance is best effort, never a failure
        pass
    return None


def collect() -> Provenance:
    """Read this machine's safe provenance. The only function here that touches the host."""
    from yazses import branding

    os_name, os_version = _os_name_version()
    return Provenance(
        yazses_version=branding.version(),
        git_commit=_git_commit(),
        python_version=platform.python_version(),
        os_name=os_name,
        os_version=os_version,
        kernel=platform.release() or "unknown",
        arch=platform.machine() or "unknown",
        cpu_model=_cpu_model(),
        logical_cpus=os.cpu_count() or 0,
        ram_gb=_ram_gb(),
        session_type=session_type(),
        displays=_displays(),
        packages=_package_versions(),
    )


def local_identifiers() -> LocalIdentifiers:
    """The identifiers a result must not contain, so the sweep can prove it does not.

    Read here and nowhere else. `getpass.getuser()` is consulted as well as the
    environment because a daemon started from a unit file may have neither `USER` nor
    `USERNAME` set, and the sweep is worth nothing if it does not know the name it is
    looking for.
    """
    names: list[str] = []
    for var in ("USER", "USERNAME", "LOGNAME"):
        value = os.environ.get(var, "").strip()
        if value:
            names.append(value)
    try:
        import getpass

        names.append(getpass.getuser())
    except Exception:  # noqa: BLE001 - no account name is not an error here
        pass
    homes: list[str] = []
    for candidate in (os.path.expanduser("~"), os.environ.get("HOME", "")):
        cleaned = candidate.strip()
        if cleaned and cleaned not in ("/", "") and cleaned not in homes:
            homes.append(cleaned)
    return LocalIdentifiers(
        hostname=platform.node().strip(),
        usernames=tuple(dict.fromkeys(n for n in names if n)),
        home_paths=tuple(homes),
    )


def fingerprint(payload: Any) -> str:
    """A stable `sha256:<16 hex>` over any JSON-serialisable value.

    Used for the display topology and the config digest. Truncated because the field is a
    change detector, not a commitment, and a 64-character hash in a report a human reads
    is noise. Sorted keys and no spaces, so the same topology fingerprints identically on
    two machines.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def as_sections(prov: Provenance) -> dict[str, Any]:
    """`software`, `machine`, `os_session` and `display` exactly as the schema wants them."""
    displays = [dict(d) for d in prov.displays]
    return {
        "software": {
            "yazses_version": prov.yazses_version,
            "git_commit": prov.git_commit,
            "python_version": prov.python_version,
            "packages": dict(prov.packages),
        },
        "machine": {
            "os_name": prov.os_name,
            "os_version": prov.os_version,
            "kernel": prov.kernel,
            "arch": prov.arch,
            "cpu_model": prov.cpu_model,
            "logical_cpus": prov.logical_cpus,
            "ram_gb": prov.ram_gb,
        },
        "os_session": {"session_type": prov.session_type},
        "display": {
            "display_count": len(displays),
            "displays": displays,
            "topology_fingerprint": fingerprint(displays),
        },
    }


def asdict(prov: Provenance) -> dict[str, Any]:
    """The whole dataclass as plain data, for a test that wants to diff two of them."""
    return dataclasses.asdict(prov)
