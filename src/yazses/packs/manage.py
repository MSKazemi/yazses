"""What the ``yazses packs`` commands and ``features enable`` do, minus the printing.

Orchestration over a :class:`~yazses.packs.context.PackContext`: list, verify (and set
damaged trees aside), remove, clean, and run one install with the real fetch and probe.
Each returns data or an ``InstallResult``-shaped answer; the CLI formats it. User
initiated only — this module reaches ``packs.install`` and so ``packs.fetch``.
"""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yazses.packs.bind import Binding
from yazses.packs.context import PackContext, scan_trees, write_state
from yazses.packs.install import (
    InstallResult,
    install_pack,
    quarantine_tree,
    subprocess_probe,
    tree_hash,
    tree_stat,
)
from yazses.packs.manifest import IndexEntry, ManifestError, parse_record
from yazses.packs.state import (
    PackStatus,
    TreeFact,
    feature_status,
    remove_build,
    remove_pack,
)

__all__ = [
    "PackRow",
    "check_bindings",
    "clean",
    "feature_pack_status",
    "install",
    "remove",
    "rows",
    "verify",
]

Progress = Callable[[str, "float | None"], None]


@dataclass(frozen=True)
class PackRow:
    name: str
    features: tuple[str, ...]
    state: str
    size: int
    unpacked: int
    detail: str = ""


def rows(ctx: PackContext) -> list[PackRow]:
    """One row per pack this build's index lists, with its on-disk state."""
    if ctx.index is None:
        return []
    trees = scan_trees(ctx)
    out = []
    for entry in ctx.index.packs:
        fact = trees.get(entry.name, TreeFact("absent"))
        out.append(PackRow(entry.name, entry.features, fact.state, entry.size,
                           entry.unpacked_bytes, fact.reason))
    return out


def feature_pack_status(ctx: PackContext, slug: str, *, config_on: bool) -> PackStatus:
    return feature_status(
        slug,
        config_on=config_on,
        capability=ctx.capability,
        index=ctx.index,
        index_error=ctx.index_error,
        trees=scan_trees(ctx) if ctx.capability.ok else {},
        doc=ctx.doc,
    )


def install(
    ctx: PackContext,
    entry: IndexEntry,
    *,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> InstallResult:
    """Run the real transaction for ``entry`` (real fetch, child-process probe)."""
    from yazses.packs.fetch import manual_steps

    if not ctx.capability.ok:
        return InstallResult(False, "Add-on not installed", ctx.capability.reason + ".")
    if ctx.index is None or ctx.base is None:
        return InstallResult(False, "Add-on not installed", (
            f"This copy of YazSes cannot read its add-on list ({ctx.index_error}). "
            "Reinstall YazSes from the releases page."
        ))
    if ctx.base_problems:
        return InstallResult(False, "Add-on not installed", (
            "This copy of YazSes carries an add-on list for a different build ("
            + "; ".join(ctx.base_problems) + "). Reinstall YazSes from the releases page."
        ))
    return install_pack(
        ctx.index,
        entry,
        ctx.base,
        ctx.layout,
        doc=ctx.doc,
        probe=subprocess_probe(ctx.runtime),
        progress=progress,
        cancel=cancel,
        write_doc=lambda d: write_state(ctx.layout, d),
        manual_steps=manual_steps(ctx.index, entry),
    )


def verify(ctx: PackContext, name: str | None = None, *, set_aside: bool = True
           ) -> list[tuple[str, str]]:
    """Full check (every file's size and SHA-256 against ``RECORD.json``) of the packs
    installed for this build. Returns ``(pack, problem)``; empty means all good. A damaged
    tree is moved to quarantine when ``set_aside`` (ADR-028 §2)."""
    out: list[tuple[str, str]] = []
    build = ctx.build_dir
    if ctx.index is None or build is None or not build.is_dir():
        return out
    facts = scan_trees(ctx)
    for entry in ctx.index.packs:
        if name is not None and entry.name != name:
            continue
        path = build / entry.name
        fact = facts.get(entry.name, TreeFact("absent"))
        if fact.state == "absent":
            continue
        problem = fact.reason if fact.state == "damaged" else _record_problem(path)
        if problem:
            out.append((entry.name, problem))
            if set_aside:
                quarantine_tree(ctx.layout, path, problem)
    return out


def check_bindings(ctx: PackContext, name: str | None = None) -> list[Binding]:
    """What each installed pack of this build that lists ``bind_to_base`` binds to
    (ADR-028 M1): the base's file and its version, or why it is refused. Loads the
    base's own DLLs by path, exactly as the pack's first use would; imports nothing from
    any pack and sets nothing aside (a refusal is the base's fault, not the pack's)."""
    from yazses.packs.bind import bind_pack, requests_for
    from yazses.packs.context import read_tree

    out: list[Binding] = []
    build = ctx.build_dir
    if ctx.index is None or build is None or not build.is_dir():
        return out
    for entry in ctx.index.packs:
        if name is not None and entry.name != name:
            continue
        path = build / entry.name
        if not path.is_dir():
            continue
        tree = read_tree(path)
        if tree.complete_sha256 is None or tree.manifest is None:
            continue
        if tree.manifest.bind_to_base:
            out.extend(bind_pack(entry.name, requests_for(tree.manifest), ctx.runtime,
                                 keep=_BOUND))
    return out


#: Handles of libraries :func:`check_bindings` loaded; kept for the life of the process.
_BOUND: list[object] = []


def _record_problem(path: Path) -> str:
    try:
        record = parse_record((path / "RECORD.json").read_text(encoding="utf-8"))
    except (OSError, ManifestError) as exc:
        return f"RECORD.json is unreadable ({exc})"
    from yazses.packs.archive import check_tree

    problems = check_tree(record, tree_stat(path), hash_fn=tree_hash(path))
    return "; ".join(problems[:3])


def remove(ctx: PackContext, name: str | None) -> list[str]:
    """Delete one pack (``name``) for this build, or every pack of every build
    (``None``). Returns what was removed. Explicit only — nothing calls this silently."""
    removed: list[str] = []
    if name is None:
        if ctx.layout.root.is_dir():
            for child in sorted(ctx.layout.root.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                    removed.append(child.name)
            try:
                ctx.layout.state_file.unlink()
            except OSError:
                pass
        return removed
    comp = ctx.component
    if comp is None:
        return removed
    path = ctx.layout.pack_dir(comp, name)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        removed.append(name)
    try:
        write_state(ctx.layout, remove_pack(ctx.doc, comp, name))
    except OSError:
        pass
    return removed


def clean(ctx: PackContext) -> list[str]:
    """Delete quarantine, staging and downloads, and the trees of builds other than this
    one — except the newest other build until this one has started cleanly, which a
    failed update's rollback needs (``policy.gc_plan``)."""
    from yazses.packs.install import builds_on_disk
    from yazses.packs.policy import gc_plan
    from yazses.packs.state import started_ok

    removed: list[str] = []
    for d in (ctx.layout.quarantine, ctx.layout.staging, ctx.layout.downloads):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    comp = ctx.component
    if comp is not None and ctx.index is not None:
        doc = ctx.doc
        plan = gc_plan(builds_on_disk(ctx.layout, doc), comp,
                       started_ok=started_ok(doc, ctx.index.base_build_id))
        for other in plan.delete:
            shutil.rmtree(ctx.layout.build_dir(other), ignore_errors=True)
            doc = remove_build(doc, other)
            removed.append(other)
        try:
            write_state(ctx.layout, doc)
        except OSError:
            pass
    return removed
