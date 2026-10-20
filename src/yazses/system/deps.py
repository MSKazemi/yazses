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
    packaging world. Three kinds of environment can never accept a package:

    * a snap — read-only squashfs plus Debian's PEP 668 marker (see
      :mod:`yazses.system.snap`);
    * any other install format with a fixed payload — the macOS ``.app``, the
      Windows ``.exe`` (and the Chocolatey/Scoop/WinGet channels that install it),
      the MSIX and the flatpak (see :func:`fixed_payload_reason`);
    * any install whose site directory we cannot write (a root-owned
      system install run as a normal user, a read-only image).
    """
    if in_snap(env):
        return dependency_install_advice(packages, env)
    fixed = fixed_payload_reason(packages, env)
    if fixed is not None:
        return fixed
    target = sysconfig.get_paths().get("purelib")
    if target and not os.access(_nearest_existing(Path(target)), os.W_OK):
        return (
            f"this Python environment is not writable ({target}), so the "
            "libraries it needs cannot be installed. Install them yourself "
            "with sufficient permissions:\n    " + " ".join(install_command(packages))
        )
    return None


def fixed_payload_reason(
    packages: Sequence[str], env: Mapping[str, str] | None = None
) -> str | None:
    """Why a frozen or confined install cannot add *packages*, or ``None``.

    The install format is read from the packaging matrix in
    :mod:`yazses.cameraperm.matrix` (``PackageProfile.can_add_runtime``) rather
    than from a second hand-written ``sys.frozen`` check, so the answer `doctor`
    gives on its Camera row and the answer `features enable` gives here cannot
    disagree (EYE-PERM-001, #414).

    The case it exists for: in a PyInstaller bundle ``sys.executable`` is the
    YazSes executable itself, so :func:`install_command` would hand pip a program
    that is not a Python interpreter, and the purelib writability check below
    can pass on a per-user install directory. Without this, ``yazses features
    enable gaze --force`` in the ``.app`` or the ``.exe`` wrote ``[gaze] enabled
    = true`` and then ran an install that could never work — a config key no
    code in that package can honour.
    """
    from yazses.cameraperm.matrix import current_profile

    profile = current_profile(dict(env) if env is not None else None)
    if profile.can_add_runtime:
        return None
    wanted = " ".join(packages)
    return (
        f"this is {profile.label}, whose payload is fixed when it is built, so "
        "extra Python libraries can never be installed into it.\n"
        f"This capability needs: {wanted}\n"
        "To use it, install YazSes from PyPI instead — same app, every capability:\n"
        "    pipx install yazses\n"
        "then run the same `yazses features enable` command again; it installs "
        "the libraries for you."
    )


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
    """A parsed ``uv-receipt.toml`` requirement dict back into a PEP 508 string.

    The environment marker is part of the requirement, not decoration. uv records
    ``--with "onnxruntime>=1.23.2,<1.24; sys_platform == 'darwin' and
    platform_machine == 'x86_64'"`` as ``{name, specifier, marker}`` (checked
    against uv 0.12.21 in an offline ``UV_TOOL_DIR``). Rendering it without the
    marker turned an Intel-Mac-only ceiling into a ceiling for *every* platform the
    next time a feature was enabled, beside the ``>=1.27`` the other half of the
    pair demands: an install that cannot resolve at all.
    """
    name = entry.get("name", "")
    extras = entry.get("extras") or []
    specifier = entry.get("specifier") or ""
    marker = entry.get("marker") or ""
    suffix = f"[{','.join(extras)}]" if extras else ""
    rendered = f"{name}{suffix}{specifier}"
    return f"{rendered}; {marker}" if marker else rendered


def _read_receipt(receipt: Path) -> tuple[str, list[str], list[str]] | None:
    """``(target, target_extras, other requirements)`` from a uv receipt, or None.

    *target* is the rendered ``yazses`` requirement exactly as recorded (a version
    pin and an extra such as ``[desktop]`` included), so a reinstall built from it
    neither drops the pin nor the extra. ``None`` for an unreadable or malformed
    file: every caller treats that as "cannot do better than the plain path".
    """
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    requirements = data.get("tool", {}).get("requirements", [])
    target = _TOOL_NAME
    target_extras: list[str] = []
    withs: list[str] = []
    for entry in requirements:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        if not name:
            continue
        if _requirement_name(name) == _TOOL_NAME:
            target = _render_requirement(entry)
            target_extras = [str(e) for e in entry.get("extras") or []]
        else:
            withs.append(_render_requirement(entry))
    return target, target_extras, withs


def _merged_install_argv(
    target: str, withs: Sequence[str], packages: Sequence[str], *, upgrade: bool = False
) -> list[str]:
    """``uv tool install [--upgrade] --with … <target>`` keeping every requirement.

    A package named in *packages* replaces **every** recorded requirement of the
    same distribution, rather than only an identically-spelled one. A feature's
    requirements arrive as a complete set — ``read-back`` names onnxruntime twice,
    once per platform marker — so keying on the name alone used to keep only the
    second of the pair, and keying on the exact string would keep an old floor
    beside a new one. Replacing the whole group by name is the only rule that is
    right for both.
    """
    new_names = {_requirement_name(p) for p in packages}
    kept = [w for w in withs if _requirement_name(w) not in new_names]
    cmd = ["uv", "tool", "install"]
    if upgrade:
        cmd.append("--upgrade")
    for spec in dict.fromkeys([*kept, *packages]):
        cmd += ["--with", spec]
    cmd.append(target)
    return cmd


def _extra_requirement_names(extras: Iterable[str]) -> set[str]:
    """Distributions the installed yazses pulls in through *extras* (canonical).

    A receipt whose target is ``yazses[desktop]`` already keeps PySide6 across an
    upgrade even though PySide6 is not a ``--with`` of its own, so it must not be
    reported as "about to be dropped". Read from the installed distribution's own
    metadata, which is what uv resolves the extra from. Best effort: an unreadable
    metadata block answers "nothing covered", which can only make the upgrade
    command longer, never drop a package.
    """
    wanted = {str(e) for e in extras}
    if not wanted:
        return set()
    try:
        from importlib.metadata import requires

        from packaging.requirements import Requirement

        covered: set[str] = set()
        for raw in requires(_TOOL_NAME) or []:
            req = Requirement(raw)
            if req.marker is None:
                continue
            if any(req.marker.evaluate({"extra": extra}) for extra in wanted):
                covered.add(_requirement_name(req.name))
        return covered
    except Exception:  # noqa: BLE001 - metadata is a courtesy here, never fatal
        return set()


def uv_tool_upgrade_command(
    required: Sequence[str],
    *,
    receipt: Path | None = None,
    covered: Iterable[str] | None = None,
) -> list[str] | None:
    """An upgrade argv that keeps *required* installed, or ``None`` if none is needed.

    ``uv tool upgrade yazses`` rebuilds the tool's environment from its receipt and
    **removes** anything the receipt does not list. Reproduced offline against uv
    0.12.21: ``uv pip install`` a package into the tool venv, run ``uv tool
    upgrade yazses``, and uv prints ``- extra-a==1.0`` — even on a no-op upgrade of
    a pinned install. Every package `features enable` installed before
    :func:`_persist_uv_tool_extras` existed, and every one that reached the
    fallback path inside :func:`install_packages`, is in exactly that position.

    So when an enabled feature's requirement is missing from the receipt, the
    upgrade is issued as ``uv tool install --upgrade --with <recorded> --with
    <missing> <target>`` instead: the same version move (``--upgrade`` with the
    target unchanged, pins included) and the requirements recorded, so the *next*
    plain ``uv tool upgrade`` keeps them too. Both properties were checked in the
    same offline experiment (1.0 → 2.0, extras present afterwards and after a
    second plain upgrade).

    ``None`` — "the plain command is already right" — when this is not a uv tool
    install, the receipt cannot be read, or every requirement is already recorded
    (directly, or through an extra of the target such as ``[desktop]``). *receipt*
    and *covered* are injectable for tests.
    """
    if not required:
        return None
    path = receipt if receipt is not None else _uv_tool_receipt()
    if path is None:
        return None
    parsed = _read_receipt(path)
    if parsed is None:
        return None
    target, target_extras, withs = parsed
    recorded = {_requirement_name(w) for w in withs}
    recorded |= set(covered) if covered is not None else _extra_requirement_names(target_extras)
    missing = [r for r in required if _requirement_name(r) not in recorded]
    if not missing:
        return None
    return _merged_install_argv(target, withs, missing, upgrade=True)


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
    parsed = _read_receipt(receipt)
    if parsed is None:
        return False
    target, _extras, withs = parsed
    cmd = _merged_install_argv(target, withs, packages)
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
