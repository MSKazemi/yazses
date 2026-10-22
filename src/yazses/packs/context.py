"""Gather the facts the pure pack modules decide on (the I/O half; never raises).

Everything the loader, the CLI and doctor need to know about *this* process — is it
frozen, may it use packs, which build is it, what does the embedded index say, what is on
disk — is read here once and handed to the pure functions in ``abi``, ``state``,
``policy`` and ``mount``. Reads only: nothing here writes, downloads or imports a pack.

Must stay out of the import closure of ``packs.fetch`` and ``packs.install``: the runtime
hook reaches this module, and the hook may never be able to start a download
(ADR-028 §4, enforced by ``tests/test_egress_inventory.py``).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.packs.abi import BaseIdentity, base_identity, match
from yazses.packs.layout import COMPLETE, PackLayout, build_dir_name
from yazses.packs.manifest import (
    ManifestError,
    PackIndex,
    PackManifest,
    parse_index,
    parse_manifest,
)
from yazses.packs.policy import Capability, capability
from yazses.packs.state import TreeFact, claimed_dirs, empty_state, parse_state

if TYPE_CHECKING:
    from yazses.platform.base import PackRuntime

__all__ = [
    "NO_PACKS_ENV",
    "InstalledTree",
    "PackContext",
    "SysFacts",
    "load_context",
    "no_packs_requested",
    "read_complete",
    "read_state",
    "read_tree",
    "scan_trees",
    "sys_facts",
    "write_state",
]

#: The recovery switch: set to 1 and no pack is mounted (ADR-028 §2.1).
NO_PACKS_ENV = "YAZSES_NO_PACKS"
#: pack.json / COMPLETE / state.json are small; anything larger is not ours.
_MAX_META_BYTES = 1 << 20


def no_packs_requested(env: Mapping[str, str]) -> bool:
    return env.get(NO_PACKS_ENV, "").strip().lower() not in {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class SysFacts:
    cache_tag: str
    python_version: str
    platform: str
    arch: str
    app_version: str


def sys_facts() -> SysFacts:
    import platform as _platform
    import sysconfig

    from yazses.system.installer_update import normalize_arch

    try:
        from yazses import __version__ as app_version
    except Exception:  # noqa: BLE001 - metadata missing: no version can match
        app_version = "0"
    return SysFacts(
        cache_tag=str(sys.implementation.cache_tag or ""),
        python_version=_platform.python_version(),
        platform=sysconfig.get_platform(),
        arch=normalize_arch(_platform.machine()),
        app_version=str(app_version),
    )


def _read_small(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            data = fh.read(_MAX_META_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_META_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def read_state(layout: PackLayout) -> dict[str, Any]:
    return parse_state(_read_small(layout.state_file))


def write_state(layout: PackLayout, doc: Mapping[str, Any]) -> None:
    """Atomic replace. Raises ``OSError``; callers treat state as best-effort."""
    from yazses.packs.state import dump_state

    layout.root.mkdir(parents=True, exist_ok=True)
    tmp = layout.state_file.with_name(f"{layout.state_file.name}.{os.getpid()}.tmp")
    tmp.write_text(dump_state(doc), encoding="utf-8")
    os.replace(tmp, layout.state_file)


def read_complete(tree: Path) -> str | None:
    """The archive SHA-256 the ``COMPLETE`` marker recorded, or ``None`` when the marker
    is missing or unreadable (a tree without it never mounts)."""
    text = _read_small(tree / COMPLETE)
    if text is None:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "sha256":
            return parts[1].lower()
    return None


@dataclass(frozen=True)
class InstalledTree:
    """One pack directory under this build, as read from disk (no hashing)."""

    name: str
    path: Path
    complete_sha256: str | None
    manifest: PackManifest | None
    manifest_error: str | None = None
    has_stdlib: bool = False


def read_tree(path: Path) -> InstalledTree:
    manifest: PackManifest | None = None
    error: str | None = None
    text = _read_small(path / "pack.json")
    if text is None:
        error = "pack.json is missing or unreadable"
    else:
        try:
            manifest = parse_manifest(text)
        except ManifestError as exc:
            error = str(exc)
    return InstalledTree(
        name=path.name,
        path=path,
        complete_sha256=read_complete(path),
        manifest=manifest,
        manifest_error=error,
        has_stdlib=(path / "stdlib").is_dir(),
    )


@dataclass(frozen=True)
class PackContext:
    runtime: PackRuntime
    layout: PackLayout
    frozen: bool
    capability: Capability
    index: PackIndex | None = None
    index_error: str | None = None
    base: BaseIdentity | None = None
    base_problems: tuple[str, ...] = ()
    doc: dict[str, Any] = field(default_factory=empty_state)

    @property
    def component(self) -> str | None:
        """This build's directory name below ``packs/``, or ``None`` with no index."""
        if self.index is None:
            return None
        try:
            return build_dir_name(self.index.base_build_id, claimed_dirs(self.doc))
        except ValueError:
            return None

    @property
    def build_dir(self) -> Path | None:
        comp = self.component
        return self.layout.build_dir(comp) if comp else None


def _load_index(runtime: PackRuntime) -> tuple[PackIndex | None, str | None]:
    try:
        path = runtime.embedded_index_path()
    except Exception as exc:  # noqa: BLE001 - a backend fault is a reason, not a crash
        return None, f"could not locate the add-on index ({exc})"
    if path is None:
        return None, "this build carries no add-on index"
    text = _read_small(path)
    if text is None:
        return None, f"the add-on index is missing ({path.name})"
    try:
        return parse_index(text), None
    except ManifestError as exc:
        return None, str(exc)


def load_context(
    *,
    env: Mapping[str, str] | None = None,
    runtime: PackRuntime | None = None,
    data_dir: Path | None = None,
    frozen: bool | None = None,
    facts: SysFacts | None = None,
    install_method: str | None = None,
    profile_can_add_packs: bool | None = None,
    profile_label: str | None = None,
) -> PackContext:
    """Every fact about packs in this process. Each argument overrides one probe, so the
    whole thing is testable on any OS. Never raises: a fault becomes a reason."""
    environ: Mapping[str, str] = os.environ if env is None else env
    if runtime is None:
        from yazses.platform.factory import get_pack_runtime

        runtime = get_pack_runtime()
    if data_dir is None:
        from yazses.platform.factory import get_pack_paths

        data_dir = get_pack_paths().data_dir
    layout = PackLayout.under(data_dir)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen

    try:
        supported = bool(runtime.supported())
    except Exception:  # noqa: BLE001
        supported = False
    if profile_can_add_packs is None or profile_label is None:
        try:
            from yazses.cameraperm.matrix import current_profile

            profile = current_profile(dict(environ))
            can_add, label = profile.can_add_packs, profile.label
        except Exception:  # noqa: BLE001
            can_add, label = False, "this install"
        profile_can_add_packs = can_add if profile_can_add_packs is None else profile_can_add_packs
        profile_label = label if profile_label is None else profile_label
    if install_method is None:
        try:
            from yazses.system.updater import detect_install_method

            install_method = detect_install_method()
        except Exception:  # noqa: BLE001
            install_method = "unknown"
    try:
        elevated = bool(runtime.is_elevated()) if supported and is_frozen else False
    except Exception:  # noqa: BLE001 - fail closed
        elevated = True
    cap = capability(
        frozen=is_frozen,
        runtime_supported=supported,
        profile_can_add_packs=bool(profile_can_add_packs),
        profile_label=profile_label,
        install_method=install_method,
        elevated=elevated,
    )
    doc = read_state(layout)
    if not (is_frozen and supported):
        return PackContext(runtime, layout, is_frozen, cap, doc=doc)
    index, error = _load_index(runtime)
    base: BaseIdentity | None = None
    problems: tuple[str, ...] = ()
    if index is not None:
        f = facts or sys_facts()
        base, problems = base_identity(
            index, cache_tag=f.cache_tag, python_version=f.python_version,
            platform=f.platform, arch=f.arch, app_version=f.app_version,
        )
    return PackContext(runtime, layout, is_frozen, cap, index, error, base, problems, doc)


def scan_trees(ctx: PackContext) -> dict[str, TreeFact]:
    """``ok`` / ``damaged`` / ``absent`` for every pack the index lists, from what is on
    disk under this build — the O(1)-per-pack check, no hashing (ADR-028 §2)."""
    out: dict[str, TreeFact] = {}
    if ctx.index is None or ctx.base is None or ctx.build_dir is None:
        return out
    for entry in ctx.index.packs:
        path = ctx.build_dir / entry.name
        if not path.is_dir():
            out[entry.name] = TreeFact("absent")
            continue
        tree = read_tree(path)
        if tree.complete_sha256 is None:
            out[entry.name] = TreeFact("absent")
            continue
        if tree.manifest is None:
            out[entry.name] = TreeFact("damaged", tree.manifest_error or "pack.json")
            continue
        verdict = match(tree.manifest, ctx.base, entry, archive_sha256=tree.complete_sha256)
        if verdict.ok:
            out[entry.name] = TreeFact("ok")
        else:
            out[entry.name] = TreeFact("damaged", "; ".join(verdict.reasons))
    return out
