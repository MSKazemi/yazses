"""A feature install as a transaction: which channel, what may not move, and how to undo.

`yazses features enable <name>` (and the settings window, and the point-of-need
"Install now" a dormant feature offers) installs optional libraries into the
running environment. Three things went wrong there, and the decisions that fix them
live here, pure, so every case tests without a network, a package manager or an
optional dependency:

* **The channel decides where a package must be recorded.** A package that lands in
  an environment without being written into that channel's own record is removed by
  the channel's next rebuild: `uv tool upgrade` drops what its receipt does not list
  (``deps._persist_uv_tool_extras``), and ``pipx reinstall`` drops what was not
  ``pipx inject``-ed — reproduced offline with pipx 1.4.3: a package installed with
  the venv's own pip was gone after ``pipx reinstall``, an injected one survived.
  :func:`classify` names the channel; ``system/deps.py`` routes to its installer.

* **A feature must not be able to move the base install.** A plain ``pip install`` of
  a feature resolves the feature alone, so a feature that wants an older numpy
  silently downgrades the one dictation needs — reproduced offline: injecting a
  package that wanted ``dep-a<2`` downgraded ``dep-a`` 2.0 → 1.0 with exit 0. With
  YazSes's own requirements passed as ``--constraint`` the resolver refuses *before
  anything is touched* (:func:`constraint_lines`).

* **A failure half-way must not leave the environment half-changed.** The installed
  set is snapshotted before the install and compared after (:func:`diff`); on a
  failure, an interrupt, or a post-install check that finds the base broken, the
  difference is undone (:func:`restore_specs`) and the report says exactly what
  was restored — or, when restoring fails too, the commands that would.

Nothing here runs anything. ``system/deps.py`` owns the subprocesses, and is the
module registered for them in ADR-019's inventory.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# --- channels ----------------------------------------------------------------

SNAP = "snap"
FROZEN = "frozen"
UV_TOOL = "uv-tool"
PIPX = "pipx"
EDITABLE = "editable"
VENV = "venv"
SYSTEM = "system"


@dataclass(frozen=True)
class Channel:
    """How one install channel takes a feature's libraries, and whether they last."""

    key: str
    installer: str          # what runs, in words
    survives: str           # what keeps the packages across the channel's own update
    can_install: bool       # False: the payload is fixed or the system owns it


CHANNELS: Mapping[str, Channel] = {
    SNAP: Channel(SNAP, "nothing — the snap is read-only", "", False),
    FROZEN: Channel(FROZEN, "nothing — the .app/.exe/MSIX payload is fixed", "", False),
    UV_TOOL: Channel(
        UV_TOOL, "uv tool install --with … (the receipt)",
        "recorded in uv-receipt.toml, so `uv tool upgrade` keeps it", True,
    ),
    PIPX: Channel(
        PIPX, "pipx inject",
        "recorded as injected in pipx_metadata.json, so `pipx reinstall`/`upgrade` keep it",
        True,
    ),
    EDITABLE: Channel(
        EDITABLE, "uv pip install / pip install into the checkout's venv",
        "nothing: the next `uv sync` removes it unless the extra is synced", True,
    ),
    VENV: Channel(VENV, "uv pip install / pip install into the venv", "the venv itself", True),
    SYSTEM: Channel(SYSTEM, "nothing — the system Python belongs to the OS", "", False),
}


#: Every value ``updater.detect_install_method`` can return, mapped to the channel a
#: feature install takes on it. ``pip`` is three channels (a venv, a source checkout,
#: or the system interpreter) that only the running environment can tell apart, which
#: is why :func:`classify` exists at all. A new install method fails
#: ``tests/test_install_channels.py`` until it is mapped here.
METHOD_CHANNELS: Mapping[str, tuple[str, ...]] = {
    "snap": (SNAP,),
    "uv": (UV_TOOL,),
    "pipx": (PIPX,),
    "pip": (VENV, EDITABLE, SYSTEM),
    "windows-installer": (FROZEN,),
    "choco": (FROZEN,),
    "winget": (FROZEN,),
    "scoop": (FROZEN,),
    "macos-app": (FROZEN,),
    "msix": (FROZEN,),
}


def classify(
    *,
    snap: bool,
    frozen: bool,
    uv_receipt: bool,
    pipx_venv: bool,
    editable: bool,
    in_venv: bool,
) -> str:
    """The install channel, from facts about the running interpreter. Pure.

    Ordered most-specific first: a snap and a frozen bundle can never take a
    package whatever else is true; a uv tool and a pipx venv are venvs too, but
    ones whose manager rebuilds them from a record; an editable checkout is a venv
    whose *project* manager does. Only a venv that is none of those is plain.
    """
    if snap:
        return SNAP
    if frozen:
        return FROZEN
    if uv_receipt:
        return UV_TOOL
    if pipx_venv:
        return PIPX
    if editable:
        return EDITABLE
    if in_venv:
        return VENV
    return SYSTEM


# --- requirement handling ------------------------------------------------------


def canonical(name: str) -> str:
    """PEP 503 normalised distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(spec: str):
    """A ``packaging`` Requirement, or ``None`` when packaging is absent or *spec* is bad.

    ``packaging`` reaches every install through faster-whisper → huggingface-hub, but
    not through a declared dependency of ours, so a missing copy degrades the guard
    (no constraints, no base check) instead of failing the install.
    """
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:
        return None
    try:
        return Requirement(spec)
    except InvalidRequirement:
        return None


def base_requirements(requires: Iterable[str]) -> list[str]:
    """YazSes's own unconditional requirements on *this* platform, as PEP 508 strings.

    *requires* is ``importlib.metadata.requires("yazses")``. A requirement that only
    applies under an extra (``extra == "tts"``) is dropped: that is exactly what a
    feature install may add. One whose platform marker is false here is dropped too —
    it is not installed and nothing can break it.
    """
    out: list[str] = []
    for raw in requires:
        req = _requirement(raw)
        if req is None:
            continue
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        out.append(raw)
    return out


def constraint_lines(base: Iterable[str]) -> list[str]:
    """``--constraint`` file lines that hold every base requirement in its range.

    Constraints may not carry extras (pip rejects them), and a requirement with no
    version range constrains nothing, so both are reduced or skipped. Markers are
    already evaluated by :func:`base_requirements`.
    """
    lines: list[str] = []
    for raw in base:
        req = _requirement(raw)
        if req is None or req.url or not str(req.specifier):
            continue
        lines.append(f"{req.name}{req.specifier}")
    return lines


def unsatisfied(base: Iterable[str], installed: Mapping[str, str]) -> list[str]:
    """Base requirements the installed set no longer meets, one readable line each.

    *installed* maps canonical name → version (:func:`snapshot`). Pre-releases count
    as satisfying, so a dev build of a dependency is not reported as breakage.
    """
    problems: list[str] = []
    for raw in base:
        req = _requirement(raw)
        if req is None:
            continue
        have = installed.get(canonical(req.name))
        if have is None:
            problems.append(f"{req.name} is missing (YazSes needs {req.name}{req.specifier})")
        elif str(req.specifier) and not req.specifier.contains(have, prereleases=True):
            problems.append(f"{req.name} {have} does not satisfy {req.name}{req.specifier}")
    return problems


def applicable(packages: Iterable[str], environment: Mapping[str, str] | None = None) -> list[str]:
    """*packages* with every environment marker evaluated here and removed.

    For installers that cannot be trusted with markers. pipx 1.4.3 does not evaluate
    them: it prints "Ignoring environment markers" and installs **every** spec —
    reproduced offline, a ``sys_platform == 'darwin'`` package was injected on Linux.
    Handed the ``read-back`` pair (``onnxruntime>=1.27`` everywhere but Intel macOS,
    ``onnxruntime>=1.23.2,<1.24`` there) it would ask for both, which no version
    satisfies. Evaluated here, exactly one survives. A spec that cannot be parsed is
    passed through unchanged rather than dropped.
    """
    out: list[str] = []
    for spec in packages:
        req = _requirement(spec)
        if req is None:
            out.append(spec)
            continue
        if req.marker is not None and not req.marker.evaluate(
            dict(environment) if environment is not None else None
        ):
            continue
        req.marker = None
        out.append(str(req))
    return out


def extras_providing(packages: Iterable[str], requires: Iterable[str]) -> list[str]:
    """The extras of YazSes that declare any of *packages* — for `uv sync --extra`.

    A source checkout's environment is owned by ``uv sync``, which removes whatever
    the lockfile's chosen extras do not list; the way to keep a feature there is to
    sync its extra. Read from the installed metadata (*requires*), so it needs no
    ``pyproject.toml`` and no hand-kept map. ``all`` is never suggested.
    """
    wanted = {canonical(re.split(r"[\[<>=!~; ]", p, maxsplit=1)[0]) for p in packages}
    found: dict[str, None] = {}
    for raw in requires:
        req = _requirement(raw)
        if req is None or req.marker is None or canonical(req.name) not in wanted:
            continue
        for match in re.finditer(r"extra\s*==\s*['\"]([^'\"]+)['\"]", str(req.marker)):
            if match.group(1) != "all":
                found.setdefault(match.group(1), None)
    return list(found)


# --- snapshots and undo ----------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """What an install did to the installed set."""

    added: tuple[str, ...] = ()                         # canonical names
    removed: tuple[tuple[str, str], ...] = ()           # (name, old version)
    changed: tuple[tuple[str, str, str], ...] = ()      # (name, old, new)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = [f"+{n}" for n in self.added]
        parts += [f"-{n} {v}" for n, v in self.removed]
        parts += [f"{n} {old}→{new}" for n, old, new in self.changed]
        return ", ".join(parts) if parts else "nothing"


def snapshot(distributions: Iterable) -> dict[str, str]:
    """canonical name → version, from ``importlib.metadata.distributions()``.

    A distribution with no name (a broken ``.dist-info``) is skipped rather than
    failing the snapshot: it cannot be restored by name anyway. When a name appears
    twice (two site directories), the first wins, as it does for imports.
    """
    out: dict[str, str] = {}
    for dist in distributions:
        try:
            name = dist.metadata["Name"]
            version = dist.version
        except Exception:  # noqa: BLE001 - a malformed record is skipped, not fatal
            continue
        if not name or not version:
            continue
        out.setdefault(canonical(name), version)
    return out


def diff(before: Mapping[str, str], after: Mapping[str, str]) -> Change:
    """The :class:`Change` between two snapshots."""
    added = tuple(sorted(n for n in after if n not in before))
    removed = tuple(sorted((n, v) for n, v in before.items() if n not in after))
    changed = tuple(
        sorted((n, v, after[n]) for n, v in before.items() if n in after and after[n] != v)
    )
    return Change(added=added, removed=removed, changed=changed)


def restore_specs(change: Change) -> tuple[list[str], list[str]]:
    """``(uninstall, reinstall)`` that undo *change*.

    Added packages are uninstalled; removed or changed ones are reinstalled at their
    previous version (``name==version``), which the installer finds in its cache —
    the same files it removed a moment ago. ``yazses`` itself is never touched: an
    editable checkout cannot be reinstalled by version.
    """
    uninstall = [n for n in change.added if n != "yazses"]
    reinstall = [f"{n}=={v}" for n, v in change.removed if n != "yazses"]
    reinstall += [f"{n}=={old}" for n, old, _new in change.changed if n != "yazses"]
    return uninstall, reinstall
