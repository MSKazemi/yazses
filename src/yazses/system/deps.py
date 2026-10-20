"""Install a feature's optional Python dependencies into the running environment.

Some capabilities (e.g. Glance-Type gaze) ride on optional extras that a base
install omits. When the user enables such a feature we install its packages into
the *current* interpreter — whether that is a uv-tool venv, a plain venv, or a
pip environment — so ``yazses features enable <name>`` is turnkey.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from yazses.system import install_txn
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
    if _externally_managed():
        return externally_managed_reason(packages)
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


def install_command(
    packages: Sequence[str],
    *,
    constraints: Path | None = None,
    no_deps: bool = False,
) -> list[str]:
    """Return the argv that installs *packages* into the running interpreter.

    Prefers ``uv pip install`` (how yazses is installed on most machines here);
    falls back to ``python -m pip install`` when uv is not on PATH.

    *constraints* is a ``--constraint`` file holding YazSes's own requirements
    (:func:`install_txn.constraint_lines`), so a feature cannot move a base
    dependency out of its range. *no_deps* is for the undo path, which restores
    exact previous versions and must not resolve anything new.
    """
    flags: list[str] = []
    if constraints is not None:
        flags += ["--constraint", str(constraints)]
    if no_deps:
        flags.append("--no-deps")
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, *flags, *packages]
    return [sys.executable, "-m", "pip", "install", *flags, *packages]


def uninstall_command(names: Sequence[str]) -> list[str]:
    """The argv that removes *names* from the running interpreter (the undo path)."""
    if shutil.which("uv"):
        return ["uv", "pip", "uninstall", "--python", sys.executable, *names]
    return [sys.executable, "-m", "pip", "uninstall", "-y", *names]


def pipx_inject_command(venv: str, packages: Sequence[str]) -> list[str]:
    """``pipx inject <venv> <packages>`` — the install pipx itself remembers.

    A package installed into a pipx venv any other way is not in
    ``pipx_metadata.json``, and ``pipx reinstall`` (which a Python upgrade forces)
    rebuilds the venv without it. Reproduced offline with pipx 1.4.3: a package
    installed with the venv's own pip was gone after ``pipx reinstall``; an injected
    one was put back.

    Markers are evaluated here (:func:`install_txn.applicable`) because pipx does not
    evaluate them — it installs every spec it is handed.

    No ``--pip-args``, and in particular no constraint file: pipx **stores** an
    injected package's pip arguments and replays them on ``pipx reinstall``. A
    temporary ``--constraint`` path was replayed after it had been deleted, pip
    failed, and the package was silently dropped from the venv *and* from the
    metadata — reproduced offline. The constraint is checked by a dry run first
    instead (:func:`_install_into_channel`).
    """
    return ["pipx", "inject", venv, *install_txn.applicable(packages)]


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
    # normcase: a no-op on POSIX; on Windows it folds case and slashes, so
    # `C:\Users\...` from uv and `c:/users/...` from sys.prefix still match.
    if os.path.normcase(_norm(str(env_dir))) != os.path.normcase(_norm(sys.prefix)):
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


# --- the running install's channel -------------------------------------------


def _externally_managed() -> bool:
    """True for a system interpreter its distribution manages (PEP 668).

    Only outside a venv: a venv never carries the marker's authority, even when its
    base interpreter does.
    """
    if sys.prefix != sys.base_prefix:
        return False
    stdlib = sysconfig.get_paths().get("stdlib")
    if not stdlib:
        return False
    return (Path(stdlib) / "EXTERNALLY-MANAGED").is_file()


def externally_managed_reason(packages: Sequence[str]) -> str:
    """Why YazSes will not install into the distribution's own Python, and what will.

    The case: ``pip install --user --break-system-packages yazses``. The old answer
    was "this environment is not writable; install them yourself with sufficient
    permissions" followed by a ``uv pip install --python /usr/bin/python3`` that pip
    and uv both refuse on exactly this marker — a remedy that cannot work.
    """
    wanted = " ".join(packages)
    return (
        "this is the system Python, which your distribution manages (PEP 668), so "
        "YazSes will not install libraries into it — doing that can break the "
        f"system's own tools.\nThis capability needs: {wanted}\n"
        "Install YazSes in its own environment instead — same app, every capability:\n"
        "    pipx install yazses\n"
        "then run the same `yazses features enable` command again; it installs "
        "the libraries for you."
    )


def _pipx_venv() -> str | None:
    """The pipx venv name when this interpreter *is* a pipx-managed venv, else None.

    pipx writes ``pipx_metadata.json`` at the venv root and names the venv after
    the package (plus any ``--suffix``), which is what ``pipx inject`` takes. With
    no ``pipx`` on PATH there is nothing to call, so the plain path is used.
    """
    prefix = Path(sys.prefix)
    if not (prefix / "pipx_metadata.json").is_file():
        return None
    if not shutil.which("pipx"):
        return None
    return prefix.name


def _editable_checkout() -> bool:
    """True when ``yazses`` is an editable install (a source checkout, `uv sync`).

    PEP 610's ``direct_url.json`` sits beside ``METADATA`` in the ``.dist-info``
    directory, which is located through the distribution's own file list rather
    than ``Distribution.read_text`` so the read names its encoding like every
    other text read here.
    """
    try:
        from importlib.metadata import distribution

        dist = distribution(_TOOL_NAME)
        meta = next(f for f in dist.files or () if f.name == "METADATA")
        path = Path(str(dist.locate_file(meta.parent / "direct_url.json")))
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:  # noqa: BLE001 - no metadata means "not editable", never an error
        return False
    return bool((data.get("dir_info") or {}).get("editable"))


def install_channel(
    *, receipt: Path | None = None, env: Mapping[str, str] | None = None
) -> str:
    """Which :mod:`install_txn` channel a feature install takes here."""
    return install_txn.classify(
        snap=in_snap(env),
        frozen=fixed_payload_reason((), env) is not None,
        uv_receipt=(receipt if receipt is not None else _uv_tool_receipt()) is not None,
        pipx_venv=_pipx_venv() is not None,
        editable=_editable_checkout(),
        in_venv=sys.prefix != sys.base_prefix,
    )


def _yazses_requires() -> list[str]:
    try:
        from importlib.metadata import requires

        return list(requires(_TOOL_NAME) or [])
    except Exception:  # noqa: BLE001 - no metadata: no constraints, no base check
        return []


def _installed_snapshot() -> dict[str, str]:
    """canonical name → version of every distribution this interpreter sees, now.

    ``invalidate_caches`` first: the metadata finder caches directory listings, and
    a snapshot that cannot see what the install just wrote would report no change.
    """
    importlib.invalidate_caches()
    try:
        from importlib.metadata import distributions

        return install_txn.snapshot(distributions())
    except Exception:  # noqa: BLE001 - an unreadable set disables undo, not the install
        return {}


def _state_files(receipt: Path | None) -> dict[Path, bytes]:
    """The channel records an install edits, so an undo can put them back too."""
    files: dict[Path, bytes] = {}
    for path in (receipt, Path(sys.prefix) / "pipx_metadata.json"):
        if path is None:
            continue
        try:
            files[path] = path.read_bytes()
        except OSError:
            continue
    return files


def _undo(before: Mapping[str, str], state: Mapping[Path, bytes], *, echo) -> bool:
    """Put the environment back to *before*. True when nothing differs afterwards."""
    change = install_txn.diff(before, _installed_snapshot())
    uninstall, reinstall = install_txn.restore_specs(change)
    commands: list[list[str]] = []
    if uninstall:
        commands.append(uninstall_command(uninstall))
    if reinstall:
        commands.append(install_command(reinstall, no_deps=True))
    for cmd in commands:
        try:
            subprocess.run(cmd, check=True)
        except (subprocess.CalledProcessError, OSError, subprocess.SubprocessError):
            pass  # the residual diff below is the verdict, not the exit code
    for path, data in state.items():
        try:
            path.write_bytes(data)
        except OSError:
            echo(f"Could not restore {path}.")
    residual = install_txn.diff(before, _installed_snapshot())
    if not residual:
        echo("Undone: the environment is exactly as it was before the install.")
        return True
    echo(
        "Could NOT fully undo the install — still different: "
        f"{residual.describe()}.\nRestore it by hand:\n  "
        + "\n  ".join(" ".join(c) for c in commands)
    )
    return False


def install_packages(packages: Sequence[str], *, echo=print) -> bool:
    """Install *packages* into the current environment. Returns True on success.

    A transaction, so a feature cannot leave the base install worse than it found
    it (see :mod:`yazses.system.install_txn` for the three failures this closes):

    1. YazSes's own requirements go to the installer as ``--constraint``, so the
       resolver refuses a feature that would move numpy, ctranslate2 & co. out of
       range — before anything is touched;
    2. the installed set is snapshotted, and the install is routed to the channel
       that records it (uv tool receipt, ``pipx inject``, or the venv);
    3. afterwards, if the install failed part-way, was interrupted, or left a base
       requirement unmet that was met before, everything it changed is undone, and
       the report says whether the undo was complete.
    """
    if not packages:
        return True
    blocked = install_blocked_reason(packages)
    if blocked is not None:
        echo(blocked)
        return False
    echo("Installing dependencies: " + " ".join(packages))
    other = daemon_interpreter_differs()
    if other is not None:
        echo(
            "\n⚠ The running daemon uses a DIFFERENT Python:\n"
            f"    daemon:  {other}\n"
            f"    this:    {sys.executable}\n"
            "  These packages are going into the second one, so the daemon will\n"
            "  still report the feature as unavailable after a restart. Install\n"
            "  them into the daemon's environment instead, e.g.\n"
            f"    {other} -m pip install " + " ".join(packages) + "\n"
        )

    receipt = _uv_tool_receipt()
    base = install_txn.base_requirements(_yazses_requires())
    before = _installed_snapshot()
    state = _state_files(receipt)
    broken_before = set(install_txn.unsatisfied(base, before))
    with tempfile.TemporaryDirectory(prefix="yazses-install-") as tmp:
        constraints: Path | None = None
        lines = install_txn.constraint_lines(base)
        if lines:
            constraints = Path(tmp) / "yazses-constraints.txt"
            constraints.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            ok = _install_into_channel(packages, receipt, constraints, echo=echo)
        except KeyboardInterrupt:
            echo("\nInterrupted — undoing whatever the install had already changed.")
            if before:
                _undo(before, state, echo=echo)
            raise
    if not before:
        return ok  # nothing to compare against: report the installer's own verdict
    after = _installed_snapshot()
    if ok:
        newly_broken = [
            p for p in install_txn.unsatisfied(base, after) if p not in broken_before
        ]
        if not newly_broken:
            _say_how_it_persists(packages, echo=echo)
            return True
        echo(
            "The install succeeded but broke YazSes's own requirements:\n  "
            + "\n  ".join(newly_broken)
            + "\nUndoing it, so dictation keeps working."
        )
        _undo(before, state, echo=echo)
        return False
    change = install_txn.diff(before, after)
    if change:
        echo(f"The install failed part-way, after changing: {change.describe()}. Undoing it.")
        _undo(before, state, echo=echo)
    return False


def _say_how_it_persists(packages: Sequence[str], *, echo) -> None:
    """The one channel whose install does not survive its own manager: a checkout."""
    if not _editable_checkout():
        return
    extras = install_txn.extras_providing(packages, _yazses_requires())
    # `--inexact` first: `uv sync --extra tts` alone is exact too, and would remove
    # the extras the developer synced before (Qt, say) to add this one.
    keep = "uv sync --inexact"
    if extras:
        keep += "   (or sync its extra with yours: " + " ".join(
            f"--extra {e}" for e in extras
        ) + ")"
    echo(
        "Note: this is a source checkout. A plain `uv sync` removes packages its "
        f"lockfile's extras do not list; keep these with:  {keep}"
    )


def _install_into_channel(
    packages: Sequence[str],
    receipt: Path | None,
    constraints: Path | None,
    *,
    echo,
) -> bool:
    """Run the channel's own installer. True on success; only KeyboardInterrupt escapes."""
    # A `uv tool install` reinstalls this interpreter itself from its own
    # receipt on every `uv tool upgrade` — the command the tray's "Install
    # update" and `yazses update` both run for this install method. A package
    # landing here any other way looks, to that reconciliation, like it should
    # not be there, and disappears on the next upgrade with no error anyone
    # sees. Recording it in the receipt instead is what makes it survive.
    # No constraint file here: `uv tool install` resolves yazses *together with*
    # the new requirements, so YazSes's own requirements already bind.
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
    else:
        venv = _pipx_venv()
        if venv is not None:
            cmd = manual = pipx_inject_command(venv, packages)
            if constraints is not None and not _preflight(packages, constraints, echo=echo):
                return False
            try:
                subprocess.run(cmd, check=True)
                echo("Recorded as injected in the pipx venv, so `pipx reinstall` keeps it.")
                return True
            except subprocess.CalledProcessError as exc:
                echo(f"Automatic install failed ({exc}). Install manually:\n  {' '.join(manual)}")
                _notify_install_failed(exc, manual)
                return False
            except OSError:
                pass  # pipx vanished between the probe and the call: use the venv directly

    cmd = install_command(packages, constraints=constraints)
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        # The printed command carries no temporary constraint file: it is gone by
        # the time anyone copies the line.
        manual = install_command(packages)
        echo(f"Automatic install failed ({exc}). Install manually:\n  {' '.join(manual)}")
        if constraints is not None:
            echo(_CONFLICT_NOTE)
        _notify_install_failed(exc, manual)
        return False


#: Printed under a failed constrained install. The manual command cannot carry the
#: temporary constraint file, so it is the one thing that *could* break the base
#: install — which is worth one sentence before someone pastes it.
_CONFLICT_NOTE = (
    "(That command skips the guard that keeps YazSes's own libraries in range. If "
    "the installer's error above is a dependency conflict, do not force it: this "
    "capability cannot share an environment with this version of YazSes.)"
)


def _preflight(packages: Sequence[str], constraints: Path, *, echo) -> bool:
    """Resolve *packages* under YazSes's constraints without installing anything.

    For the one channel that cannot take a constraint file on its real install
    (pipx; see :func:`pipx_inject_command`). A resolver conflict is refused here,
    before pipx touches the venv. An installer that cannot dry-run (pip older than
    22.2) answers True: the post-install check in :func:`install_packages` still
    undoes a result that broke the base.
    """
    cmd = install_command(install_txn.applicable(packages), constraints=constraints)
    cmd.insert(cmd.index("--constraint"), "--dry-run")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return True
    if proc.returncode == 0:
        return True
    output = (proc.stderr or proc.stdout or "").strip()
    if "no such option" in output.lower() or "unexpected argument" in output.lower():
        return True
    echo(
        "Not installed: a dry run of the install (held to YazSes's own requirements) "
        "failed, so nothing was changed. The resolver said:\n" + output[-1500:]
        + "\nIf that is a dependency conflict, do not force the install: this "
        "capability cannot share an environment with this version of YazSes."
    )
    return False


def _notify_install_failed(exc: BaseException, manual: Sequence[str]) -> None:
    from yazses.system.notify import notify_when_unattended

    notify_when_unattended(
        "YazSes could not install a feature's dependencies",
        f"The install failed ({exc}). Run this in a terminal:\n  {' '.join(manual)}",
    )


def install_feature(
    packages: Sequence[str],
    *,
    check_modules: Sequence[str] = (),
    echo=print,
) -> bool:
    """Install a feature's *packages*, then prove its *check_modules* now resolve.

    :func:`install_packages` reports what the installer said. A feature is only
    installed when its modules are importable, and an installer that exits 0
    without providing them (a wrong package for this platform, a split install
    whose other interpreter got the files) used to be reported as success, leaving
    the capability dormant behind "Apply it: yazses restart". This is the check the
    daemon's dormancy probe would make at the next start, made now, so the person
    who asked hears it.
    """
    if not install_packages(packages, echo=echo):
        return False
    if not check_modules:
        return True
    importlib.invalidate_caches()
    still = missing_modules(check_modules)
    if not still:
        return True
    echo(
        f"The installer finished, but {', '.join(still)} still cannot be imported by "
        f"this Python ({sys.executable}), so the capability stays dormant."
    )
    return False
