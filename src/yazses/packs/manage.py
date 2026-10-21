"""What the ``yazses packs`` commands and ``features enable`` do, minus the printing.

Orchestration over a :class:`~yazses.packs.context.PackContext`: list, verify (and set
damaged trees aside), remove, clean, and run one install with the real fetch and probe.
Each returns data or an ``InstallResult``-shaped answer; the CLI formats it. User
initiated only — this module reaches ``packs.install`` and so ``packs.fetch``.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yazses.packs.context import PackContext, scan_trees, write_state
from yazses.packs.install import (
    InstallResult,
    install_pack,
    quarantine_tree,
    subprocess_probe,
    tree_hash,
    tree_stat,
)
from yazses.packs.manifest import IndexEntry, ManifestError, PackIndex, parse_record
from yazses.packs.state import (
    PackStatus,
    TreeFact,
    feature_status,
    remove_build,
    remove_pack,
)

__all__ = [
    "DiskUse",
    "PackRow",
    "clean",
    "disk_use",
    "entry_for_file",
    "feature_pack_status",
    "file_fetcher",
    "install",
    "install_from_file",
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


# ---- offline install from a file (ADR-028 question 5, Phase 2) -----------------------

#: ``YazSes-<version>-<os>-<arch>-pack-<name>.yazpack`` read back, only to say *which*
#: YazSes a refused file belongs to. Never used to accept a file.
_ASSET_RE = re.compile(
    r"^YazSes-(?P<version>.+)-(?P<os>[a-z]+)-(?P<arch>[a-z0-9_]+)-pack-"
    r"(?P<name>[a-z0-9][a-z0-9-]*)\.yazpack$"
)
_COPY_CHUNK = 1 << 20
_MAX_PACK_JSON = 1 << 20


def entry_for_file(index: PackIndex, file_name: str, name: str | None = None
                   ) -> tuple[IndexEntry | None, str]:
    """The index entry a local ``.yazpack`` is, chosen by its **exact** file name.

    ``(entry, "")`` when ``file_name`` is one of this build's asset names (and the asset
    of ``name``, when a name is given); otherwise ``(None, sentence)``. Pure. The name
    only selects the entry: trust comes from the SHA-256 checked afterwards.
    """
    entry = next((p for p in index.packs if p.asset == file_name), None)
    accepted = ", ".join(p.asset for p in index.packs) or "none"
    if entry is None:
        m = _ASSET_RE.match(file_name)
        if m is not None and m.group("version") != index.app_version:
            return None, (
                f"{file_name} is an add-on for YazSes {m.group('version')}, and this is "
                f"YazSes {index.app_version}. Download the file for this version "
                f"(this copy accepts: {accepted})."
            )
        return None, (
            f"{file_name} is not an add-on file of this copy of YazSes "
            f"{index.app_version}. Use the file exactly as the release names it "
            f"(this copy accepts: {accepted})."
        )
    if name is not None and entry.name != name:
        return None, (
            f"{file_name} is the {entry.name} add-on, not {name}. Name the add-on the "
            "file holds, or leave the name out."
        )
    return entry, ""


def _foreign_build(archive: Path, index: PackIndex) -> str | None:
    """The ``base_build_id`` a refused archive's ``pack.json`` names when it is not this
    build's, so the refusal can say so. ``None`` when unreadable or ours. Reads one
    small member; never extracts."""
    import zipfile

    from yazses.packs.manifest import parse_manifest

    try:
        with zipfile.ZipFile(archive) as zf:
            info = zf.getinfo("pack.json")
            if info.file_size > _MAX_PACK_JSON:
                return None
            with zf.open(info) as fh:
                data = fh.read(_MAX_PACK_JSON + 1)
        manifest = parse_manifest(data)
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile):
        return None
    return None if manifest.base_build_id == index.base_build_id else manifest.base_build_id


def _short_build(build_id: str) -> str:
    return build_id.split(":", 1)[-1][:12]


def file_fetcher(source: Path) -> Callable[..., Path]:
    """A ``fetch`` for :func:`~yazses.packs.install.install_pack` that reads ``source``
    instead of the network.

    It copies ``source`` to ``downloads/<asset>.part``, hashes **the copy** (a file
    changed after a check cannot slip in), requires the size and SHA-256 of this build's
    embedded index entry, then renames the copy to ``<asset>``. It raises
    ``PackFetchError`` or ``PackCancelled`` like the network fetch, deletes the ``.part``
    on every failure, and leaves deleting ``<asset>`` to the transaction. It opens no
    socket and fetches no ``SHA256SUMS.txt``.
    """
    from yazses.packs.fetch import PackCancelled, PackFetchError

    def fetch(index: PackIndex, entry: IndexEntry, dest_dir: Path, *,
              progress: Progress | None = None,
              cancel: Callable[[], bool] | None = None) -> Path:
        pretty = entry.name.replace("-", " ").title()
        mismatch = (
            f"{source.name} did not match the checksum built into this copy of YazSes "
            f"for the {pretty} add-on"
        )

        def wrong_file(archive: Path, detail: str) -> PackFetchError:
            other = _foreign_build(archive, index)
            if other is not None:
                return PackFetchError("checksum", (
                    f"{source.name} was made for a different build of YazSes (build "
                    f"{_short_build(other)}; this copy is build "
                    f"{_short_build(index.base_build_id)}). Download the add-on from the "
                    f"v{index.app_version} release this copy was installed from. Nothing "
                    "was installed."
                ))
            return PackFetchError("checksum", f"{mismatch}{detail}. Nothing was installed.")

        try:
            have = source.stat().st_size
        except OSError as exc:
            raise PackFetchError("refused", (
                f"{source.name} could not be read ({exc}). Nothing was installed."
            )) from exc
        if have != entry.size:
            raise wrong_file(source, (
                f": it is {have:,} bytes, and this build's add-on is {entry.size:,}. It "
                "may be incomplete or from another build"
            ))
        dest_dir.mkdir(parents=True, exist_ok=True)
        part = dest_dir / (entry.asset + ".part")
        out = dest_dir / entry.asset
        digest = hashlib.sha256()
        copied = 0
        try:
            if progress is not None:
                progress(f"Copying {source.name}…", 0.0)
            with source.open("rb") as src, part.open("wb") as dst:
                while copied <= entry.size:
                    if cancel is not None and cancel():
                        raise PackCancelled()
                    chunk = src.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    copied += len(chunk)
                    digest.update(chunk)
                    dst.write(chunk)
            if copied != entry.size or digest.hexdigest() != entry.sha256:
                raise wrong_file(part, ". It may be damaged, changed, or from another "
                                       "build")
            os.replace(part, out)
        except OSError as exc:
            raise PackFetchError("refused", (
                f"{source.name} could not be copied ({exc}). Nothing was installed."
            )) from exc
        finally:
            try:
                part.unlink()
            except OSError:
                pass
        if progress is not None:
            progress("The checksum matches this copy of YazSes.", 1.0)
        return out

    return fetch


def install_from_file(
    ctx: PackContext,
    source: Path,
    *,
    name: str | None = None,
    probe: Callable[[str, Path], tuple[bool, str]] | None = None,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> InstallResult:
    """Install a ``.yazpack`` the user carried here (``yazses packs install --from``).

    Offline by construction: the only trust anchor is the SHA-256 in **this build's
    embedded index**. No ``SHA256SUMS.txt`` is fetched and nothing reaches the network.
    A file whose name is not one of this build's asset names, whose size or hash differs,
    or that was made for another build id is refused with a sentence saying which. After
    the hash, the ordinary transaction runs unchanged: member validation, staging,
    ``RECORD.json``, the ABI match, the child-process probe and the atomic place.
    """
    from yazses.packs.fetch import pack_urls

    refused = "Add-on not installed"
    if not ctx.capability.ok:
        return InstallResult(False, refused, ctx.capability.reason + ".", step="check")
    if ctx.index is None or ctx.base is None:
        return InstallResult(False, refused, (
            f"This copy of YazSes cannot read its add-on list ({ctx.index_error}). "
            "Reinstall YazSes from the releases page."
        ), step="check")
    if ctx.base_problems:
        return InstallResult(False, refused, (
            "This copy of YazSes carries an add-on list for a different build ("
            + "; ".join(ctx.base_problems) + "). Reinstall YazSes from the releases page."
        ), step="check")
    entry, problem = entry_for_file(ctx.index, source.name, name)
    if entry is None:
        return InstallResult(False, refused, problem + " Nothing was installed.",
                             step="check")
    _, url = pack_urls(ctx.index, entry)
    steps = [f"The add-on file for this copy is {entry.asset} on the "
             f"v{ctx.index.app_version} release: {url}"]
    if not source.is_file():
        return InstallResult(False, refused, f"{source} is not a file.", steps,
                             step="check")
    return install_pack(
        ctx.index,
        entry,
        ctx.base,
        ctx.layout,
        doc=ctx.doc,
        probe=probe if probe is not None else subprocess_probe(ctx.runtime),
        fetch=file_fetcher(source),
        progress=progress,
        cancel=cancel,
        write_doc=lambda d: write_state(ctx.layout, d),
        manual_steps=steps,
    )


# ---- disk use, for doctor's add-on row (ADR-028 question 4) --------------------------

@dataclass(frozen=True)
class DiskUse:
    """Bytes under the pack root, split by whether this copy of YazSes loads them.

    ``this_build`` is ``None`` when this process cannot tell which build it is (not the
    frozen app, or no readable index): then nothing can be called unused."""

    this_build: int | None
    other_builds: int
    leftovers: int

    @property
    def total(self) -> int:
        return (self.this_build or 0) + self.other_builds + self.leftovers

    @property
    def unused(self) -> int:
        """What this copy never loads. Zero when the build is unknown."""
        return 0 if self.this_build is None else self.other_builds + self.leftovers


def _tree_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def disk_use(ctx: PackContext) -> DiskUse:
    """Measure ``packs/``. Reads only and never raises. Build directories are ``b-*``;
    ``staging``, ``downloads`` and ``quarantine`` are leftovers."""
    comp = ctx.component
    this: int | None = 0 if comp is not None else None
    other = leftover = 0
    try:
        children = sorted(ctx.layout.root.iterdir())
    except OSError:
        children = []
    for child in children:
        try:
            if child.is_symlink() or not child.is_dir():
                continue
        except OSError:
            continue
        size = _tree_bytes(child)
        if child.name.startswith("b-"):
            if comp is not None and child.name == comp:
                this = (this or 0) + size
            else:
                other += size
        elif child.name in {"staging", "downloads", "quarantine"}:
            leftover += size
    return DiskUse(this, other, leftover)
