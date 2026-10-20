"""Install a feature's optional Python dependencies into the running environment.

Some capabilities (e.g. Glance-Type gaze) ride on optional extras that a base
install omits. When the user enables such a feature we install its packages into
the *current* interpreter — whether that is a uv-tool venv, a plain venv, or a
pip environment — so ``yazses features enable <name>`` is turnkey.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from yazses.system.snap import dependency_install_advice, in_snap

# The only package this module ever installs dependencies *for*.
_TOOL_NAME = "yazses"


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

    ``ValueError`` covers a module in ``sys.modules`` whose ``__spec__`` is None --
    but only for one that is *not* already imported. A module present in
    ``sys.modules`` **is** importable; that is what the name means, and `find_spec`
    raising over its missing spec is a lookup artefact, not evidence of absence.
    Reporting it absent broke every caller that probes an in-tree adapter module: a
    test (or any code) that injects a stand-in with ``monkeypatch.setitem(sys.modules,
    ...)`` builds a bare ``ModuleType`` with no spec, and the probe then answered
    "not implemented in this build" about a module it could have imported on the
    next line.
    """
    absent = []
    for name in modules:
        if name in sys.modules:
            continue
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


def _uv_tool_receipt() -> Path | None:
    """The ``uv-receipt.toml`` for this install, if the running interpreter *is*
    a ``uv tool install`` of yazses. ``None`` for every other kind of install
    (pipx, a plain venv, a dev checkout's ``.venv``) — those have no receipt and
    must keep using :func:`install_command`.

    ``uv tool dir`` (never a hardcoded path) so a ``UV_TOOL_DIR`` override, or a
    future change to uv's default layout, cannot make this silently stop
    matching. Compared with the same not-symlink-resolved normalisation as
    :func:`_env_prefix` above and for the identical reason: resolving symlinks
    would collapse two different venvs built on the same base interpreter.
    """
    if not shutil.which("uv"):
        return None
    try:
        out = subprocess.run(
            ["uv", "tool", "dir"], capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.SubprocessError):
        return None
    tool_dir = out.stdout.strip()
    if not tool_dir:
        return None
    env_dir = Path(tool_dir) / _TOOL_NAME
    if _norm(str(env_dir)) != _norm(sys.prefix):
        return None
    receipt = env_dir / "uv-receipt.toml"
    return receipt if receipt.exists() else None


def _requirement_name(requirement: str) -> str:
    """``"onnx-asr[cpu,hub]>=0.12"`` -> ``"onnx-asr"``, canonicalised.

    Canonicalised (lowercase, ``_``/``.`` folded to ``-``) so a receipt entry and
    a newly-requested requirement for the same distribution are recognised as
    the same package even when their spelling differs, which is how PyPI itself
    treats package names.
    """
    name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _render_requirement(entry: dict) -> str:
    """A parsed ``uv-receipt.toml`` requirement dict back into a PEP 508 string."""
    name = entry.get("name", "")
    extras = entry.get("extras") or []
    specifier = entry.get("specifier") or ""
    suffix = f"[{','.join(extras)}]" if extras else ""
    return f"{name}{suffix}{specifier}"


def _persist_uv_tool_extras(receipt: Path, packages: Sequence[str]) -> bool:
    """Record *packages* in the uv tool's own receipt, so they survive the next
    ``uv tool upgrade`` — the upgrade command the tray's "Install update" and
    `yazses update` both run for this install method.

    Why this exists: ``uv tool upgrade`` rebuilds the tool's venv from exactly
    what its receipt lists. A package installed the other way this module knows
    — a bare ``uv pip install --python <venv>`` — never touches that receipt, so
    it looks to uv like something that should not be there, and the next upgrade
    removes it. Reproduced in isolation (a throwaway ``UV_TOOL_DIR``): installing
    `onnx-asr` via ``uv pip install`` and then running ``uv tool upgrade yazses``
    printed ``Modified yazses environment - onnx-asr==0.12.0`` and the package
    was gone, even though the yazses version itself did not change. This is
    almost certainly why a real install's Parakeet engine (an opt-in extra,
    enabled through this exact path) silently stopped loading and fell back to
    a smaller, less accurate model right after using the tray's own "Install
    update" button — with no error the user would ever see.

    The fix installs the same way ``yazses features enable <name>`` is
    documented to work everywhere else, but reissues it as
    ``uv tool install --with <every requirement already on the receipt> --with
    <the new ones> <the exact yazses spec already on the receipt>`` — because a
    bare ``uv tool install --with X yazses`` does not *add* X, it **replaces**
    the whole with-list, which would silently drop a second feature's extra the
    moment a third one is enabled. Confirmed the same way: enabling one extra,
    then a second with a second bare ``--with``, left only the second in the
    receipt.

    Best-effort: any failure to parse the receipt or run the command returns
    False so the caller can fall back to the plain install, which still enables
    the feature for *this* session even if it will not survive an upgrade.
    """
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    requirements = data.get("tool", {}).get("requirements", [])
    target = _TOOL_NAME
    withs: dict[str, str] = {}
    for entry in requirements:
        name = entry.get("name", "")
        if not name:
            continue
        rendered = _render_requirement(entry)
        if _requirement_name(name) == _TOOL_NAME:
            target = rendered
        else:
            withs[_requirement_name(name)] = rendered
    for pkg in packages:
        withs[_requirement_name(pkg)] = pkg
    cmd = ["uv", "tool", "install"]
    for spec in withs.values():
        cmd += ["--with", spec]
    cmd.append(target)
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, OSError, subprocess.SubprocessError):
        return False


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
        # argv[0] is whatever was typed, so it is routinely *relative* -- a
        # `.venv/bin/python` or `./venv/bin/yazses-daemon` started from a
        # checkout. Resolving it needs the process's own working directory, not
        # ours, and the two are not the same process.
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        return None
    if not argv0:
        return None
    daemon_prefix = _env_prefix(argv0, cwd)
    if not daemon_prefix or daemon_prefix == _norm(sys.prefix):
        return None
    return argv0


def _norm(path: str) -> str:
    """Absolute and normalised, but **not** symlink-resolved.

    `realpath` would defeat the whole check: a venv's `python` is a symlink to a
    base interpreter, so two different virtualenvs on the same base collapse to
    one path and the mismatch never fires.
    """
    import os

    return os.path.normpath(os.path.abspath(path))


def _env_prefix(argv0: str, cwd: str) -> str:
    """`<env>/bin/python` -> `<env>`, as an absolute path. Pure.

    Split out and made cwd-relative because the naive version compared a
    *relative* `dirname(dirname(argv0))` -- `.venv` -- against an absolute
    `sys.prefix`, which can never be equal. Every daemon started by typing a
    relative path was therefore reported as a different interpreter, and
    `features enable` told the user to install into `.venv/bin/python`: a path
    that means something different in every directory, and nothing in most.
    """
    import os

    if not os.path.dirname(argv0):
        return ""  # a bare name found on PATH says nothing about an environment
    absolute = argv0 if os.path.isabs(argv0) else os.path.join(cwd, argv0)
    return _norm(os.path.dirname(os.path.dirname(absolute)))


def install_packages(packages: Sequence[str], *, echo=print) -> bool:
    """Install *packages* into the current environment. Returns True on success."""
    if not packages:
        return True
    blocked = install_blocked_reason(packages)
    if blocked is not None:
        echo(blocked)
        return False
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

    # A `uv tool install` reinstalls this interpreter itself from its own
    # receipt on every `uv tool upgrade` — the command the tray's "Install
    # update" and `yazses update` both run for this install method. A package
    # landing here any other way looks, to that reconciliation, like it should
    # not be there, and disappears on the next upgrade with no error anyone
    # sees. Recording it in the receipt instead is what makes it survive.
    receipt = _uv_tool_receipt()
    if receipt is not None:
        if _persist_uv_tool_extras(receipt, packages):
            echo("Recorded in the uv tool install, so it survives future upgrades.")
            return True
        message = (
            "Could not update the uv tool install's own record of its dependencies "
            "— installing this session only. It may not survive the next update."
        )
        echo(message)
        # This exact path is how an enabled engine disappears: the install succeeds,
        # the caller is told it worked, and the next `uv tool upgrade` reconciles the
        # receipt and drops the package. The loss then surfaces much later as
        # dictation quietly using a different engine. Printed, it reaches only
        # someone already watching a terminal.
        from yazses.system.notify import notify_when_unattended

        notify_when_unattended(
            "YazSes may lose this feature on the next update",
            message + " Re-run `yazses features enable` after updating.",
        )

    cmd = install_command(packages)
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        echo(f"Automatic install failed ({exc}). Install manually:\n  {' '.join(cmd)}")
        from yazses.system.notify import notify_when_unattended

        notify_when_unattended(
            "YazSes could not install a feature's dependencies",
            f"The install failed ({exc}). Run this in a terminal:\n  {' '.join(cmd)}",
        )
        return False
