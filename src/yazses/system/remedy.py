"""The one install hint a user-facing message gives when an optional library is missing.

Eight messages across the tray, the overlay, the settings window, `enroll-voice`, the
daemon's Cocktail Filter warning and meeting notes each hand-wrote their own remedy,
and every one of them told the user to ``uv sync`` an extra: a command that only
does anything inside a source checkout. An end user who ran it got "No `pyproject.toml`
found", or — worse — synced some other project. This module derives the remedy
instead of letting each message write one:

* **A capability is named and the registry agrees.** When *feature* is a wired
  capability that is switched on and whose ``_FEATURE_DEPS`` packages are part of
  *extra*, the answer is what :mod:`yazses.system.dormant` would say for it — the
  same probes, the same refusal for an environment that can never install (a snap, a
  frozen ``.app``/``.exe``, the system Python), and on an installable one the
  point-of-need command ``yazses features install <slug>``, which installs exactly
  what `features install` would and writes no config.
* **Otherwise** — no capability owns the library (meeting notes, a BLE armband), the
  named one is off, or the registry and the extra disagree — the requirements are
  read from the installed distribution's own metadata for *extra*, and the command
  is the one that installs into *this* environment and lasts there: the receipt-
  merged ``uv tool install`` for a uv tool, ``pipx inject`` for pipx, ``uv sync
  --inexact --extra`` for a source checkout, the interpreter's own installer for a
  plain venv. A blocked environment gets its reason instead.

A switched-off capability is never the answer: a hint that installs PySide6 by
turning the tray or the overlay on (the overlay steals keyboard focus on Wayland)
would change more than the user asked. The feature slug is passed by the caller
because a library match alone is ambiguous in the harmful direction —
``llama-cpp-python`` belongs to ``llm-cleanup``, which rewrites every dictation —
and it is checked against the registry here, and at every call site by
``tests/test_install_hints_are_for_end_users.py``.

It never installs anything (AGENTS.md rule 1, ADR-019).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

#: The wording `dormant.py` uses before a command, kept identical on purpose.
_LEAD = "Install them with:  "

#: A backslash is safe because the interpreter path leads the command, and PowerShell
#: will not run a quoted first word (`"C:\...\python.exe" -m pip` is a parse error
#: without `&`). Bare, a Windows path without spaces runs in PowerShell and cmd.exe
#: alike; a POSIX path with a backslash in it is not a case worth breaking that for.
_SAFE_ARG = re.compile(r"^[\w@%+=:,./\\-]+$")


def _quote(arg: str) -> str:
    """Double quotes, which POSIX shells, PowerShell and cmd.exe all honour as arguments.

    A path with a space is still quoted, so in PowerShell that command needs `&` in
    front; cmd.exe and POSIX shells run it as printed.
    """
    return arg if _SAFE_ARG.match(arg) else f'"{arg}"'


def render_command(argv: Sequence[str]) -> str:
    """*argv* as one command line a user can paste, each argument quoted only if needed."""
    return " ".join(_quote(a) for a in argv)


_render = render_command  # the module's own call sites predate the public name


def _canonical(name: str) -> str:
    base = re.split(r"[\[<>=!~; ]", name, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", base).lower()


def extra_requirements(extra: str, requires: Iterable[str] | None = None) -> tuple[str, ...]:
    """The requirements YazSes declares for *extra*, markers evaluated on this machine.

    Read from the installed metadata (*requires*, default the running ``yazses``),
    which is what every installer resolves an extra from, so it needs no
    ``pyproject.toml`` and no hand-kept copy. A requirement whose platform marker
    does not hold here is dropped; the others lose their marker, since the hint is
    for this machine. Empty when the metadata is unreadable.
    """
    if requires is None:
        try:
            from importlib.metadata import requires as _requires

            requires = list(_requires("yazses") or [])
        except Exception:  # noqa: BLE001 - no metadata: no requirements, never an error
            return ()
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:  # pragma: no cover - packaging is a base dependency
        return ()
    out: list[str] = []
    for raw in requires:
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            continue
        if req.marker is None:
            continue
        try:
            for_extra = req.marker.evaluate({"extra": extra})
            for_base = req.marker.evaluate({"extra": ""})
        except Exception:  # noqa: BLE001 - an unevaluable marker is not this extra's
            continue
        if not for_extra or for_base:
            continue
        req.marker = None
        out.append(str(req))
    return tuple(dict.fromkeys(out))


def _installed(name: str) -> bool:
    try:
        from importlib.metadata import PackageNotFoundError, version

        version(_canonical(name))
        return True
    except PackageNotFoundError:
        return False
    except Exception:  # noqa: BLE001 - unknown means "maybe missing": still hint
        return False


def _registry_row(slug: str, cfg, features: Sequence | None):
    if features is None:
        from yazses.system.features import feature_status

        features = feature_status(cfg)
    return next((f for f in features if getattr(f, "slug", "") == slug), None)


def _owned_by(row, packages: Sequence[str]) -> bool:
    """True when enabling *row* installs only libraries that *extra* declares."""
    mine = {_canonical(p) for p in getattr(row, "pip_packages", ()) or ()}
    return bool(mine) and mine <= {_canonical(p) for p in packages}


def _feature_hint(row, cfg, *, missing, blocked, graphical) -> str | None:
    """What `dormant.py` says for *row*, as the point-of-need command, or None."""
    from yazses.system.dormant import dormant_features

    kwargs = {}
    if missing is not None:
        kwargs["missing"] = missing
    if blocked is not None:
        kwargs["blocked"] = blocked
    if graphical is not None:
        kwargs["graphical"] = graphical
    found = dormant_features(cfg, features=[row], **kwargs)
    if not found:
        return None
    item = found[0]
    if not item.installable:
        return item.remedy
    return f"{_LEAD}yazses features install {item.slug}"


def _channel_command(extra: str, packages: Sequence[str], channel: str) -> list[str] | None:
    """The argv that installs *packages* into this environment and lasts there."""
    from yazses.system import deps, install_txn

    if channel == install_txn.UV_TOOL:
        receipt = Path(sys.prefix) / "uv-receipt.toml"
        parsed = deps._read_receipt(receipt) if receipt.is_file() else None
        if parsed is not None:
            target, _extras, withs = parsed
            return deps._merged_install_argv(target, withs, packages)
        return None
    if channel == install_txn.PIPX:
        return deps.pipx_inject_command(Path(sys.prefix).name, packages)
    if channel == install_txn.EDITABLE:
        # The one channel where syncing the extra *is* the right command. `--inexact`
        # so the extras the developer already synced are kept (see deps.py).
        return ["uv", "sync", "--inexact", "--extra", extra]
    return None


def install_hint(
    extra: str,
    *,
    feature: str | None = None,
    cfg=None,
    features: Sequence | None = None,
    requires: Iterable[str] | None = None,
    missing: Callable[[Iterable[str]], Sequence[str]] | None = None,
    blocked: Callable[[Sequence[str]], str | None] | None = None,
    graphical: Callable[[], bool] | None = None,
    installed: Callable[[str], bool] | None = None,
    channel: str | None = None,
) -> str:
    """The sentence that tells an end user how to get *extra*'s libraries, or ``""``.

    *extra* is the YazSes extra that ships the missing library (``desktop``,
    ``voiceprint``, ``notes`` …). *feature* is the capability the message is about,
    when there is one; it is used only if the registry says enabling it installs
    libraries *extra* declares, and only while it is switched on. ``""`` when every
    requirement of *extra* is already installed — then installing is not the fix,
    and a message that said it was would send the user in a circle.

    Everything after *cfg* is injectable for tests; production callers pass at most
    *extra*, *feature* and *cfg*.
    """
    packages = extra_requirements(extra, requires)
    is_installed = installed or _installed
    if packages and all(is_installed(p) for p in packages):
        return ""
    if feature is not None:
        try:
            if cfg is None and features is None:
                from yazses.config import load_config

                cfg = load_config()
            row = _registry_row(feature, cfg, features)
            if row is not None and (not packages or _owned_by(row, packages)):
                hint = _feature_hint(
                    row, cfg, missing=missing, blocked=blocked, graphical=graphical
                )
                if hint:
                    return hint
                if not packages:
                    packages = tuple(row.pip_packages)
        except Exception:  # noqa: BLE001 - a hint must never break the message it is in
            pass
    if not packages:
        return f"Install the YazSes `{extra}` extra into the environment YazSes runs from."
    try:
        from yazses.system import deps

        reason = (blocked or deps.install_blocked_reason)(packages)
        if reason:
            return reason
        where = channel if channel is not None else deps.install_channel()
        argv = _channel_command(extra, packages, where) or deps.install_command(packages)
    except Exception:  # noqa: BLE001 - fall back to the packages, never to a traceback
        return "It needs: " + " ".join(packages)
    return _LEAD + _render(argv)
