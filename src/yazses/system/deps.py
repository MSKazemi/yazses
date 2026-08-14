"""Install a feature's optional Python dependencies into the running environment.

Some capabilities (e.g. Glance-Type gaze) ride on optional extras that a base
install omits. When the user enables such a feature we install its packages into
the *current* interpreter — whether that is a uv-tool venv, a plain venv, or a
pip environment — so ``yazses features enable <name>`` is turnkey.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from yazses.system.snap import dependency_install_advice, in_snap


def missing_modules(modules: Iterable[str]) -> list[str]:
    """Return the import names in *modules* that are not importable.

    ``find_spec`` returns ``None`` for an absent top-level module but *raises*
    ``ModuleNotFoundError`` for a dotted name whose parent package is absent —
    it has to import the parent to look inside it. Treating that as an error
    rather than as "missing" broke the one caller that asks about a dotted
    name (``pyannote.audio``): the exception escaped into
    ``recimport.factory._unavailable_detail``, whose blanket ``except`` then
    reported whatever unrelated error came first instead of the honest "install
    this extra". Both outcomes mean the same thing here, so both are reported
    the same way.

    ``ValueError`` covers a module already in ``sys.modules`` with no spec.
    """
    absent = []
    for name in modules:
        try:
            if importlib.util.find_spec(name) is None:
                absent.append(name)
        except (ModuleNotFoundError, ValueError):
            absent.append(name)
    return absent


def _nearest_existing(path: Path) -> Path:
    """The closest ancestor of *path* that exists (``purelib`` may not yet)."""
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def install_blocked_reason(
    packages: Sequence[str], *, env: Mapping[str, str] | None = None
) -> str | None:
    """Why installing *packages* here cannot work, or ``None`` if it can.

    Checked *before* pip runs, because a doomed install is worse than no
    install: the user waits, then reads an error written for a different
    packaging world. Two environments can never accept a package:

    * a snap — read-only squashfs plus Debian's PEP 668 marker (see
      :mod:`yazses.system.snap`);
    * any install whose site directory we cannot write (a root-owned
      system install run as a normal user, a read-only image).
    """
    if in_snap(env):
        return dependency_install_advice(packages, env)
    target = sysconfig.get_paths().get("purelib")
    if target and not os.access(_nearest_existing(Path(target)), os.W_OK):
        return (
            f"this Python environment is not writable ({target}), so the "
            "libraries it needs cannot be installed. Install them yourself "
            "with sufficient permissions:\n    " + " ".join(install_command(packages))
        )
    return None


def install_command(packages: Sequence[str]) -> list[str]:
    """Return the argv that installs *packages* into the running interpreter.

    Prefers ``uv pip install`` (how yazses is installed on most machines here);
    falls back to ``python -m pip install`` when uv is not on PATH.
    """
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, *packages]
    return [sys.executable, "-m", "pip", "install", *packages]


def daemon_interpreter_differs(lifecycle=None) -> str | None:
    """The daemon's Python, when it is not the one running this command.

    `install_packages` installs into the interpreter running the CLI. That is
    right for a single install and wrong the moment there are two — a `uv tool`
    install providing the daemon plus a checkout providing `yazses` on PATH, say.
    The extra then lands in the interpreter that will never load it, the daemon
    keeps reporting the feature as unavailable, and the message it prints tells
    the user to run the command they just ran.

    Returns the daemon's interpreter path when it differs, else None. Best
    effort: an unreadable process table means we say nothing rather than warn
    wrongly.
    """
    import os
    import sys

    try:
        from yazses.platform import get_platform

        life = lifecycle if lifecycle is not None else get_platform().lifecycle
        if not life.is_running():
            return None
        pid = life.read_pid()
        if not pid:
            return None
        # NOT /proc/PID/exe: a venv's `python` is a symlink to a base
        # interpreter, so two different virtualenvs built on the same base
        # resolve to the identical path and the check silently never fires.
        # argv[0] is the venv's own python, which is the thing that differs.
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        argv0 = raw[0].decode() if raw and raw[0] else ""
    except Exception:
        return None
    if not argv0:
        return None
    # `<env>/bin/python` -> `<env>`, which is what sys.prefix reports for ours.
    daemon_prefix = os.path.dirname(os.path.dirname(argv0))
    if not daemon_prefix or daemon_prefix == sys.prefix:
        return None
    return argv0


def install_packages(packages: Sequence[str], *, echo=print) -> bool:
    """Install *packages* into the current environment. Returns True on success."""
    if not packages:
        return True
    blocked = install_blocked_reason(packages)
    if blocked is not None:
        echo(blocked)
        return False
    cmd = install_command(packages)
    echo("Installing dependencies: " + " ".join(packages))
    other = daemon_interpreter_differs()
    if other is not None:
        import sys

        echo(
            "\n⚠ The running daemon uses a DIFFERENT Python:\n"
            f"    daemon:  {other}\n"
            f"    this:    {sys.executable}\n"
            "  These packages are going into the second one, so the daemon will\n"
            "  still report the feature as unavailable after a restart. Install\n"
            "  them into the daemon's environment instead, e.g.\n"
            f"    {other} -m pip install " + " ".join(packages) + "\n"
        )
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        echo(f"Automatic install failed ({exc}). Install manually:\n  {' '.join(cmd)}")
        return False
