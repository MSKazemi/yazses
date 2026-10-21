"""Mount installed packs at process start (ADR-028 §2).

Called by the PyInstaller runtime hook (``packaging/windows/rthook_yazses_packs.py``)
before ``main`` runs, in every process of a frozen install, frozen ``multiprocessing``
children included. The pure :func:`plan_mount` decides; :func:`apply` carries it out
through the ``PackRuntime`` backend; :func:`mount_at_startup` wires the two together and
**never raises** — a pack must never be able to stop YazSes from starting.

What mounting does, and does not:

* ``sys.path.append(<pack>/site)`` then ``<pack>/stdlib`` — **appended, never
  prepended**, so the frozen archive and the base's files always win. ``site.addsitedir``
  is not used, because it would execute ``.pth`` lines.
* each ``native_dirs`` entry goes through ``PackRuntime.add_native_dir`` and the handle is
  kept in :data:`_HANDLES` for the life of the process (closing it removes the directory).
  ``PATH`` is not touched.
* nothing from a pack is imported. A pack's modules load lazily, when its feature runs.
* a pack whose ``pack.json`` lists ``bind_to_base`` (ADR-028 M1) gets a
  :class:`~yazses.packs.bind.FirstUseBinder` on ``sys.meta_path``. It loads the
  **base's** copy of each named DLL by absolute path the first time one of that pack's
  top-level modules is imported, before the pack's extension loads, and refuses the pack
  (``ImportError`` with a named reason, also added to :attr:`MountReport.failed`) if the
  base lacks the DLL, its version is below ``bind_min_versions``, or another file of that
  name is loaded. Start-up itself loads nothing; :mod:`yazses.packs.bind` is imported
  only when such a pack is mounted.

Skipped entirely when: not frozen; ``YAZSES_NO_PACKS=1``; the OS has no pack loader;
this install may not use packs (profile or install method); **the process is
elevated**; or the embedded index does not belong to this app. A single pack is skipped
when its ``COMPLETE`` marker is missing, and refused (reported, to be quarantined by the
next ``yazses packs verify``) when any field disagrees with this base and its index.
Every skip carries a named reason in :data:`LAST`, so ``yazses packs`` and doctor can say
exactly why a feature reads *waiting for add-on*.
"""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.packs.abi import BaseIdentity, match
from yazses.packs.context import NO_PACKS_ENV, InstalledTree, no_packs_requested
from yazses.packs.manifest import PackIndex, PackManifest
from yazses.packs.policy import Capability, disposition

if TYPE_CHECKING:
    from yazses.platform.base import PackRuntime

__all__ = [
    "LAST",
    "MountItem",
    "MountPlan",
    "MountReport",
    "apply",
    "mount_at_startup",
    "plan_mount",
]


@dataclass(frozen=True)
class MountItem:
    name: str
    paths: tuple[Path, ...]
    native_dirs: tuple[Path, ...]
    #: ``(dll, minimum version or None)`` from ``bind_to_base`` (ADR-028 M1).
    binds: tuple[tuple[str, str | None], ...] = ()
    #: The pack's import directories (``site/`` and ``path_entries``, not ``stdlib/``):
    #: their top-level names trigger the binding.
    module_dirs: tuple[Path, ...] = ()


@dataclass(frozen=True)
class MountPlan:
    items: tuple[MountItem, ...] = ()
    #: ``(pack, reason)`` for packs left alone: no COMPLETE marker, or another build.
    skipped: tuple[tuple[str, str], ...] = ()
    #: ``(pack, reason)`` for packs that failed a check and should be set aside.
    quarantine: tuple[tuple[str, str], ...] = ()
    #: Non-empty when nothing at all is mounted, and why.
    reason: str = ""


@dataclass
class MountReport:
    plan: MountPlan
    mounted: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""


#: What the last :func:`mount_at_startup` in this process did (``None``: never ran).
LAST: MountReport | None = None
#: ``os.add_dll_directory`` handles. Module-global so they live as long as the process.
_HANDLES: list[object] = []


def plan_mount(
    *,
    base: BaseIdentity | None,
    base_problems: Sequence[str],
    index: PackIndex | None,
    index_error: str | None,
    trees: Sequence[InstalledTree],
    env: Mapping[str, str],
    capability: Capability,
) -> MountPlan:
    """Decide what to mount. Pure: reads only its arguments."""
    if no_packs_requested(env):
        return MountPlan(reason=f"{NO_PACKS_ENV} is set, so no add-on was loaded")
    if not capability.ok:
        return MountPlan(reason=capability.reason)
    if index is None or base is None:
        return MountPlan(reason=f"no add-on was loaded: {index_error or 'no add-on index'}")
    if base_problems:
        return MountPlan(reason=(
            "no add-on was loaded, because the add-on index does not belong to this "
            "app: " + "; ".join(base_problems)
        ))
    items: list[MountItem] = []
    skipped: list[tuple[str, str]] = []
    quarantine: list[tuple[str, str]] = []
    for tree in sorted(trees, key=lambda t: t.name):
        if tree.complete_sha256 is None:
            skipped.append((tree.name, "the install did not finish (no COMPLETE marker)"))
            continue
        if tree.manifest is None:
            quarantine.append((tree.name, tree.manifest_error or "pack.json is unreadable"))
            continue
        if tree.manifest.name != tree.name:
            quarantine.append((tree.name, f"pack.json names {tree.manifest.name!r}"))
            continue
        verdict = match(
            tree.manifest, base, index.entry(tree.name), archive_sha256=tree.complete_sha256
        )
        action = disposition(verdict.status, complete=True, damaged=False)
        if action == "stale":
            skipped.append((tree.name, "; ".join(verdict.reasons)))
        elif action == "quarantine":
            quarantine.append((tree.name, "; ".join(verdict.reasons)))
        elif tree.manifest.bind_to_base and _bind_mode(tree.manifest) != "in-process":
            skipped.append((tree.name, "the add-on must run in a separate process, which "
                                       "this version of YazSes cannot do yet"))
        else:
            paths = [tree.path / "site"]
            paths += [tree.path / Path(*p.split("/")) for p in tree.manifest.path_entries]
            module_dirs = tuple(paths)
            if tree.has_stdlib:
                paths.append(tree.path / "stdlib")
            natives = tuple(tree.path / Path(*d.split("/")) for d in tree.manifest.native_dirs)
            mins = {d.casefold(): v for d, v in tree.manifest.bind_min_versions}
            binds = tuple((d, mins.get(d.casefold())) for d in tree.manifest.bind_to_base)
            items.append(MountItem(tree.name, tuple(paths), natives, binds,
                                   module_dirs if binds else ()))
    return MountPlan(tuple(items), tuple(skipped), tuple(quarantine))


def _bind_mode(manifest: PackManifest) -> str:
    from yazses.packs.bind import bind_mode

    return bind_mode(manifest)


def _install_binder(
    item: MountItem,
    runtime: PackRuntime,
    report: MountReport,
    *,
    meta_path: list[Any],
    keep: list[object],
) -> None:
    """Put a :class:`~yazses.packs.bind.FirstUseBinder` for ``item`` first on
    ``meta_path``. Lists the pack's import directories (one ``scandir`` each); loads
    nothing."""
    from yazses.packs.bind import BindRequest, FirstUseBinder, top_level_names

    listing: list[tuple[str, bool]] = []
    for d in item.module_dirs:
        try:
            with os.scandir(d) as it:
                listing += [(e.name, e.is_dir()) for e in it]
        except OSError:
            continue
    triggers = top_level_names(listing)
    if not triggers:
        # A binder with nothing to watch would let the pack import unbound: fail closed.
        raise OSError("no importable module was found in its site folder")
    binder = FirstUseBinder(
        item.name,
        [BindRequest(dll, minimum) for dll, minimum in item.binds],
        triggers,
        runtime,
        meta_path=meta_path,
        keep=keep,
        on_refused=lambda pack, why: report.failed.append((pack, why)),
    )
    meta_path.insert(0, binder)


def apply(
    plan: MountPlan,
    runtime: PackRuntime,
    *,
    sys_path: list[str] | None = None,
    handles: list[object] | None = None,
    meta_path: list[Any] | None = None,
) -> MountReport:
    """Carry out ``plan``. A pack whose native directory cannot be added is not put on
    ``sys.path`` at all (half a pack is worse than none). A pack that lists
    ``bind_to_base`` gets its first-use binder *before* it reaches ``sys.path``, and is
    not mounted if the binder cannot be installed. Never raises."""
    path_list = sys.path if sys_path is None else sys_path
    keep = _HANDLES if handles is None else handles
    finders = sys.meta_path if meta_path is None else meta_path
    report = MountReport(plan)
    for item in plan.items:
        try:
            for native in item.native_dirs:
                keep.append(runtime.add_native_dir(native))
        except Exception as exc:  # noqa: BLE001 - one pack's fault must not stop startup
            report.failed.append((item.name, f"its native library folder could not be "
                                             f"added ({exc})"))
            continue
        if item.binds:
            try:
                _install_binder(item, runtime, report, meta_path=finders, keep=keep)
            except Exception as exc:  # noqa: BLE001 - unbound is refused, not mounted
                report.failed.append((item.name, f"its shared-library binding could not "
                                                 f"be prepared ({exc})"))
                continue
        for p in item.paths:
            text = str(p)
            if text not in path_list:
                path_list.append(text)
        report.mounted.append(item.name)
    if report.mounted:
        importlib.invalidate_caches()
    return report


def mount_at_startup(
    *,
    env: Mapping[str, str] | None = None,
    runtime: PackRuntime | None = None,
    data_dir: Path | None = None,
    frozen: bool | None = None,
    sys_path: list[str] | None = None,
) -> MountReport | None:
    """The runtime hook's one call. Returns what happened (also kept in :data:`LAST`),
    or ``None`` when there was nothing to consider. **Never raises.**

    The cheap exits come first — not frozen, the recovery switch, an OS with no loader,
    no ``packs`` directory — so a user who never installed a pack pays for one
    ``stat``, not for profile detection and the index.
    """
    global LAST
    try:
        environ: Mapping[str, str] = os.environ if env is None else env
        if not (bool(getattr(sys, "frozen", False)) if frozen is None else frozen):
            return None
        if no_packs_requested(environ):
            LAST = MountReport(MountPlan(reason=f"{NO_PACKS_ENV} is set, so no add-on "
                                                "was loaded"))
            return LAST
        if runtime is None:
            from yazses.platform.factory import get_pack_runtime

            runtime = get_pack_runtime()
        if not runtime.supported():
            return None
        if data_dir is None:
            from yazses.platform.factory import get_pack_paths

            data_dir = get_pack_paths().data_dir
        from yazses.packs.layout import PackLayout

        if not PackLayout.under(data_dir).root.is_dir():
            return None

        from yazses.packs.context import load_context, read_tree

        ctx = load_context(env=environ, runtime=runtime, data_dir=data_dir, frozen=True)
        build_dir = ctx.build_dir
        trees = []
        if build_dir is not None and build_dir.is_dir():
            trees = [read_tree(p) for p in sorted(build_dir.iterdir()) if p.is_dir()]
        plan = plan_mount(
            base=ctx.base,
            base_problems=ctx.base_problems,
            index=ctx.index,
            index_error=ctx.index_error,
            trees=trees,
            env=environ,
            capability=ctx.capability,
        )
        LAST = apply(plan, runtime, sys_path=sys_path)
        return LAST
    except BaseException as exc:  # noqa: BLE001 - the hook must never stop startup
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        LAST = MountReport(MountPlan(reason="no add-on was loaded"),
                           error=f"{exc.__class__.__name__}: {exc}")
        return LAST
