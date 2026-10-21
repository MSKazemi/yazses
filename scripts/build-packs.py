#!/usr/bin/env python3
"""Build ADR-028 feature add-on packs for a frozen Windows base.

A pack is one ZIP (``.yazpack``) per qualifying pyproject extra, holding that extra's
wheels *minus* what the frozen base already carries, unpacked the way
``pip install --target`` lays them out. Every pack is pinned to one exact base build:
``base_build_id`` is the SHA-256 of a canonical manifest of ``dist/YazSes/``, taken
right after PyInstaller. The pack index (``YazSes-<v>-windows-<arch>-packs.json``)
lists every pack's SHA-256 and is copied into ``dist/YazSes/_internal/`` before Inno
packages the bundle, so the installed app knows offline which packs belong to it.

Decisions live in ``design/adr/adr-028-feature-addon-packs.md`` and
``design/specs/feature-addon-packs.md`` (its *Implementation status* note records the
choices this script makes where the spec left the format open).

Subcommands
-----------
``build``          the release path: base manifest -> packs -> provisional index ->
                   frozen probe of each pack -> final index of the packs that probed ->
                   embed -> base-invariance check. A pack that fails any check or the
                   probe is withheld; the base installer still ships.
``check-release``  a published index against the release's assets and SHA256SUMS.txt.
``validate``       ``packaging/packs/packs.toml`` against pyproject and _FEATURE_DEPS.
``spike-spec``     write a copy of the PyInstaller spec with the Phase 0 spike hook.
``spike-probe``    mount each built pack into the spike-frozen app and report the four
                   ADR-028 open risks as PASS/FAIL lines in the job summary.

Standard library plus the ``uv`` executable only, so it runs on the Windows runner
with nothing new installed. Everything above the ``I/O`` line is pure and is tested
directly by ``tests/test_build_packs.py``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
PACKS_TOML = ROOT / "packaging" / "packs" / "packs.toml"
PYPROJECT = ROOT / "pyproject.toml"
SPIKE_HOOK = ROOT / "packaging" / "packs" / "spike" / "rthook_pack_spike.py"

#: ``pack.json`` / ``RECORD.json`` / base-manifest format.
PACK_FORMAT = 1
#: Index format (spec, Contracts). An unknown value makes the runtime refuse every pack.
INDEX_FORMAT = 1
PACK_SUFFIX = ".yazpack"
#: Where the index is embedded, relative to the bundle root (``dist/YazSes``).
#: PyInstaller >= 6 puts everything but the executables in ``_internal`` = sys._MEIPASS.
EMBEDDED_INDEX = "_internal/yazses-packs-index.json"
#: GitHub's per-asset limit is "under 2 GiB"; ADR-028 §4a.
PACK_MAX_BYTES = int(1.9 * 1024**3)
#: Above this a pack needs ``approved_large`` + ``approved_by`` in packs.toml (§7 e).
LARGE_PACK_BYTES = 500 * 1024**2
#: Longest relative path inside a pack (§6 path length), so the install stays < MAX_PATH.
PATH_BUDGET = 140
#: A member whose DEFLATE ratio would exceed this is STORED instead, so the runtime's
#: decompression-bomb ratio cap can be any value >= this without refusing a real pack.
MAX_MEMBER_RATIO = 100
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
DECISIONS = ("pack", "bundled", "no-windows-wheel", "unwired", "deferred")
PROBE_ARGS = ("--cli", "packs", "probe", "{name}", "--staged", "{staged}")
PROBE_TIMEOUT_S = 120

# 16 characters, the runtime's cap (``yazses.packs.layout.MAX_PACK_NAME``): a longer name
# would make the runtime reject the whole index, not just that pack.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
_ARCH_RE = re.compile(r"^[a-z0-9_]{1,16}$")
_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+-]{0,40}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_BUILD_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DIST_SUFFIXES = (".dist-info", ".data", ".egg-info")
_NOT_MODULE_DIRS = {"__pycache__", "bin", "Scripts"}
_LICENCE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


class PackError(Exception):
    """A pack failed a build rule. The message is the reason it is withheld."""


# ======================================================================================
# Pure: naming
# ======================================================================================


def canonical_name(name: str) -> str:
    """PEP 503 normalisation, so ``Sherpa_ONNX`` and ``sherpa-onnx`` compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def host_platform() -> str:
    """The ``sysconfig`` platform tag of the interpreter running the build.

    A seam, not a shortcut: the pack build only runs on the Windows release runner,
    and the tests pin it to ``win-amd64`` so they do not depend on the host they run
    on (the FreeBSD leg has no asset OS token at all).
    """
    return sysconfig.get_platform()


def os_token(platform_tag: str) -> str:
    """The ``<os>`` word in an asset name, from a ``sysconfig.get_platform()`` tag.

    The spec's asset rule says ``<platform os>``; the release names already in use
    say ``windows`` and ``macos``, so ``win-amd64`` maps to ``windows``.
    """
    if platform_tag.startswith("win"):
        return "windows"
    if platform_tag.startswith("macosx"):
        return "macos"
    if platform_tag.startswith("linux"):
        return "linux"
    raise ValueError(f"no asset os token for platform {platform_tag!r}")


def _check_parts(version: str, os_tok: str, arch: str) -> None:
    if not _VERSION_RE.match(version):
        raise ValueError(f"bad version {version!r}")
    if os_tok not in {"windows", "macos", "linux"}:
        raise ValueError(f"bad os token {os_tok!r}")
    if not _ARCH_RE.match(arch):
        raise ValueError(f"bad arch {arch!r}")


def pack_asset_name(version: str, os_tok: str, arch: str, name: str) -> str:
    _check_parts(version, os_tok, arch)
    if not _NAME_RE.match(name):
        raise ValueError(f"bad pack name {name!r}")
    return f"YazSes-{version}-{os_tok}-{arch}-pack-{name}{PACK_SUFFIX}"


def index_asset_name(version: str, os_tok: str, arch: str) -> str:
    _check_parts(version, os_tok, arch)
    return f"YazSes-{version}-{os_tok}-{arch}-packs.json"


def provenance_asset_name(version: str, os_tok: str, arch: str) -> str:
    _check_parts(version, os_tok, arch)
    return f"YazSes-{version}-{os_tok}-{arch}-packs.intoto.jsonl"


# ======================================================================================
# Pure: hashing and canonical JSON
# ======================================================================================


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Byte-stable JSON: sorted keys, no whitespace. Used for anything that is hashed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def pretty_json(obj: Any) -> bytes:
    """Human-readable but still deterministic. The index and pack.json use this."""
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def base_manifest(entries: Iterable[tuple[str, int, str]]) -> bytes:
    """Canonical ``base-manifest.json`` bytes for ``(relpath, size, sha256)`` entries."""
    files = []
    seen: set[str] = set()
    for path, size, digest in sorted(entries):
        if path in seen:
            raise ValueError(f"duplicate path in base manifest: {path}")
        seen.add(path)
        files.append({"path": path, "size": int(size), "sha256": digest})
    return canonical_json({"format": PACK_FORMAT, "files": files})


def build_id_of(manifest: bytes) -> str:
    return "sha256:" + sha256_bytes(manifest)


# ======================================================================================
# Pure: requirements export
# ======================================================================================


def parse_requirements_export(text: str) -> dict[str, str]:
    """``uv export`` output -> {canonical name: requirement block with its hashes}.

    Continuation lines are joined, ``# via`` comments and option lines dropped.
    """
    blocks: dict[str, str] = {}
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        joined = " ".join(part.rstrip("\\").strip() for part in current).strip()
        current.clear()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", joined)
        if not m:
            return
        blocks[canonical_name(m.group(1))] = joined

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            flush()
            continue
        if raw[:1].isspace() and current:
            current.append(stripped)
            continue
        flush()
        if stripped.startswith(("-e ", "--", "-r ", "-c ", ".", "/")):
            continue
        current.append(stripped)
    flush()
    return blocks


def marginal_requirements(extra: Mapping[str, str], base_names: set[str]) -> dict[str, str]:
    """The extra's closure minus everything the base already freezes."""
    return {n: b for n, b in sorted(extra.items()) if n not in base_names}


def render_requirements(blocks: Mapping[str, str]) -> str:
    out = []
    for _, block in sorted(blocks.items()):
        # `--hash=` options split back onto continuation lines for readability.
        out.append(re.sub(r"\s+(--hash=)", r" \\\n    \1", block))
    return "\n".join(out) + "\n"


# ======================================================================================
# Pure: tree rules (modules, DLLs, .pth, paths)
# ======================================================================================


def top_level_modules(relpaths: Iterable[str]) -> set[str]:
    """Importable top-level names in a ``--target`` tree (or a RECORD's file list)."""
    names: set[str] = set()
    for rel in relpaths:
        parts = PurePosixPath(rel.replace("\\", "/")).parts
        if not parts or parts[0] in ("..", "."):
            continue
        first = parts[0]
        if len(parts) == 1:
            if first.endswith(".py"):
                names.add(first[:-3])
            elif first.endswith((".pyd", ".so")):
                names.add(first.split(".", 1)[0])
            continue
        if first.endswith(_DIST_SUFFIXES) or first in _NOT_MODULE_DIRS:
            continue
        if rel.endswith((".py", ".pyd", ".so", ".pyc")):
            names.add(first)
    return names


def module_collisions(pack_modules: set[str], base_modules: set[str]) -> list[str]:
    """Names the pack would ship that the base already provides (case-insensitively).

    The base always wins on sys.path, so a collision is a module the pack could never
    load; refusing it makes shadowing impossible rather than unlikely (§1).
    """
    base = {m.lower() for m in base_modules}
    return sorted(m for m in pack_modules if m.lower() in base)


@dataclass
class DllReport:
    drop: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    shared_identical: list[str] = field(default_factory=list)


def dll_collisions(
    pack_dlls: Mapping[str, str],
    base_dlls: Mapping[str, str],
    other_packs: Mapping[str, Mapping[str, str]] | None = None,
) -> DllReport:
    """DLL basename rule (§1). Maps are ``{relpath: sha256}``.

    Windows answers a by-name DLL request from the loaded-module list whatever folder
    it came from, so two different files with one basename silently bind to whichever
    loaded first. Against the base: identical bytes -> drop the pack's copy; different
    -> conflict. Against another pack: different -> conflict; identical -> both keep it
    (either pack may be installed alone, and whichever loads serves both). Two copies
    of one basename inside the same pack with different bytes -> conflict.
    """
    rep = DllReport()

    def by_base(m: Mapping[str, str]) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for rel, digest in m.items():
            out.setdefault(PurePosixPath(rel).name.lower(), {})[rel] = digest
        return out

    mine = by_base(pack_dlls)
    base = by_base(base_dlls)
    for basename, copies in sorted(mine.items()):
        if len(set(copies.values())) > 1:
            rep.conflicts.append(
                f"{basename}: {len(copies)} copies with different bytes inside the pack "
                f"({', '.join(sorted(copies))})"
            )
        if basename in base:
            base_digests = set(base[basename].values())
            for rel, digest in sorted(copies.items()):
                if base_digests == {digest}:
                    rep.drop.append(rel)
                else:
                    rep.conflicts.append(
                        f"{basename}: {rel} differs from the base's "
                        f"{', '.join(sorted(base[basename]))}"
                    )
        for other, odlls in sorted((other_packs or {}).items()):
            for orel, odigest in sorted(odlls.items()):
                if PurePosixPath(orel).name.lower() != basename:
                    continue
                for rel, digest in sorted(copies.items()):
                    if digest == odigest:
                        rep.shared_identical.append(f"{rel} == {other}:{orel}")
                    else:
                        rep.conflicts.append(
                            f"{basename}: {rel} differs from pack {other!r}'s {orel}"
                        )
    return rep


def native_dirs(relpaths: Iterable[str], prefix: str = "site") -> list[str]:
    """Pack-root-relative directories holding a ``.dll`` (fed to os.add_dll_directory)."""
    return sorted({
        str(PurePosixPath(prefix) / PurePosixPath(rel).parent)
        for rel in relpaths
        if rel.lower().endswith(".dll")
    })


def classify_pth(text: str) -> tuple[list[str], list[str]]:
    """``.pth`` lines -> (path lines, code lines). Comments and blanks dropped."""
    paths: list[str] = []
    code: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("import ", "import\t")):
            code.append(line)
        else:
            paths.append(line)
    return paths, code


def pth_path_entries(text: str, prefix: str = "site") -> list[str]:
    """A ``.pth`` becomes ``path_entries`` in pack.json; executable lines fail the build."""
    paths, code = classify_pth(text)
    if code:
        raise PackError(f".pth executes code, which a pack may not do: {code[0]!r}")
    out = []
    for p in paths:
        if member_path_errors(f"{prefix}/{p}", budget=10**6):
            raise PackError(f".pth path escapes the pack: {p!r}")
        out.append(str(PurePosixPath(prefix) / PurePosixPath(p.replace("\\", "/"))))
    return out


def member_path_errors(path: str, budget: int = PATH_BUDGET) -> list[str]:
    """Why ``path`` may not be a pack member. Empty means fine."""
    errs = []
    if not path:
        return ["empty name"]
    if "\\" in path:
        errs.append("backslash in name")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path) or path.startswith("//"):
        errs.append("absolute path")
    parts = path.split("/")
    if any(p in ("..", ".", "") for p in parts):
        errs.append("'..', '.' or empty component")
    if any(ch in path for ch in '<>:"|?*\x00'):
        errs.append("character Windows cannot store")
    if len(path) > budget:
        errs.append(f"{len(path)} characters, over the {budget} budget")
    return errs


def licence_member(dist_info: str, rel_in_dist_info: str) -> bool:
    """Is this dist-info file a licence text that goes to LICENSES/?"""
    parts = PurePosixPath(rel_in_dist_info).parts
    if parts and parts[0] == "licenses":
        return True
    return PurePosixPath(rel_in_dist_info).name.upper().startswith(_LICENCE_PREFIXES)


# ======================================================================================
# Pure: pack.json, RECORD.json, the archive
# ======================================================================================


def record_json(payload: Iterable[tuple[str, int, str]]) -> bytes:
    """``RECORD.json``: every payload member (everything but RECORD.json and pack.json)."""
    files = [{"path": p, "size": int(s), "sha256": d} for p, s, d in sorted(payload)]
    return pretty_json({"format": PACK_FORMAT, "files": files})


def pack_json(fields: Mapping[str, Any], payload_bytes: int, payload_files: int,
              record_size: int) -> bytes:
    """``pack.json`` whose ``files``/``unpacked_bytes`` count *every* archive member.

    The numbers include pack.json itself, whose size depends on them, so iterate to the
    fixed point (it moves only when a digit count changes; two rounds in practice).
    """
    files = payload_files + 2
    guess = 0
    for _ in range(10):
        doc = dict(fields, files=files, unpacked_bytes=payload_bytes + record_size + guess)
        data = pretty_json(doc)
        if len(data) == guess:
            return data
        guess = len(data)
    raise RuntimeError("pack.json size did not converge")


def pack_fields(*, name: str, extra: str, features: list[str], app_version: str,
                base_build_id: str, python: Mapping[str, str], platform_tag: str, arch: str,
                distributions: list[dict[str, str]], entry_modules: list[str],
                native: list[str], path_entries: list[str]) -> dict[str, Any]:
    """Everything in pack.json except the two counts (ADR-028 §1 + ``path_entries``)."""
    return {
        "format": PACK_FORMAT,
        "name": name,
        "extra": extra,
        "features": sorted(features),
        "app_version": app_version,
        "base_build_id": base_build_id,
        "python": dict(python),
        "platform": platform_tag,
        "arch": arch,
        "distributions": sorted(distributions, key=lambda d: canonical_name(d["name"])),
        "entry_modules": list(entry_modules),
        "native_dirs": sorted(native),
        "path_entries": list(path_entries),
    }


def _compress_choice(data: bytes) -> int:
    if not data:
        return zipfile.ZIP_STORED
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    size = len(c.compress(data)) + len(c.flush())
    return zipfile.ZIP_STORED if len(data) / max(size, 1) > MAX_MEMBER_RATIO else zipfile.ZIP_DEFLATED


def write_deterministic_zip(dest: Path, members: Mapping[str, bytes | Path]) -> None:
    """Sorted entries, fixed timestamp and mode, no directory entries, no extra fields.

    Two runs over the same members produce the same bytes (tests prove it).
    """
    with zipfile.ZipFile(dest, "w", allowZip64=True) as zf:
        for name in sorted(members):
            errs = member_path_errors(name)
            if errs:
                raise PackError(f"{name}: {'; '.join(errs)}")
            src = members[name]
            data = src.read_bytes() if isinstance(src, Path) else src
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.compress_type = _compress_choice(data)
            zf.writestr(info, data, compress_type=info.compress_type, compresslevel=9)


# ======================================================================================
# Pure: the index
# ======================================================================================

_INDEX_KEYS = {"format", "app_version", "base_build_id", "python", "platform", "arch", "packs"}
_ENTRY_KEYS = {"name", "asset", "sha256", "size", "unpacked_bytes", "files", "features"}


def index_entry(*, name: str, asset: str, sha256: str, size: int, unpacked_bytes: int,
                files: int, features: list[str]) -> dict[str, Any]:
    return {
        "name": name, "asset": asset, "sha256": sha256, "size": int(size),
        "unpacked_bytes": int(unpacked_bytes), "files": int(files),
        "features": sorted(features),
    }


def build_index(*, app_version: str, base_build_id: str, python: Mapping[str, str],
                platform_tag: str, arch: str, entries: Iterable[Mapping[str, Any]]
                ) -> dict[str, Any]:
    doc = {
        "format": INDEX_FORMAT,
        "app_version": app_version,
        "base_build_id": base_build_id,
        "python": dict(python),
        "platform": platform_tag,
        "arch": arch,
        "packs": sorted((dict(e) for e in entries), key=lambda e: e["name"]),
    }
    errors = validate_index(doc)
    if errors:
        raise ValueError("invalid index: " + "; ".join(errors))
    return doc


def validate_index(doc: Any) -> list[str]:
    """The spec's index contract. Unknown keys are allowed; missing ones are not."""
    if not isinstance(doc, dict):
        return ["index is not an object"]
    if doc.get("format") != INDEX_FORMAT:
        return [f"unknown index format {doc.get('format')!r}"]
    errs = [f"missing key {k!r}" for k in sorted(_INDEX_KEYS - doc.keys())]
    if errs:
        return errs
    if not isinstance(doc["app_version"], str) or not _VERSION_RE.match(doc["app_version"]):
        errs.append("app_version is not a version string")
    if not isinstance(doc["base_build_id"], str) or not _BUILD_ID_RE.match(doc["base_build_id"]):
        errs.append("base_build_id is not sha256:<64 hex>")
    py = doc["python"]
    if not isinstance(py, dict) or not all(
        isinstance(py.get(k), str) and py.get(k) for k in ("cache_tag", "version", "abi")
    ):
        errs.append("python needs string cache_tag, version and abi")
    try:
        os_tok = os_token(str(doc["platform"]))
    except ValueError as exc:
        errs.append(str(exc))
        os_tok = ""
    if not isinstance(doc["arch"], str) or not _ARCH_RE.match(doc["arch"]):
        errs.append("arch is not a short lowercase token")
    if not isinstance(doc["packs"], list):
        return errs + ["packs is not a list"]
    names: set[str] = set()
    parts_ok = not errs
    for i, e in enumerate(doc["packs"]):
        where = f"packs[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where} is not an object")
            continue
        missing = sorted(_ENTRY_KEYS - e.keys())
        if missing:
            errs.append(f"{where} missing {missing}")
            continue
        name = e["name"]
        if not isinstance(name, str) or not _NAME_RE.match(name):
            errs.append(f"{where} bad name {name!r}")
            continue
        if name in names:
            errs.append(f"{where} duplicate name {name!r}")
        names.add(name)
        if parts_ok:
            want = pack_asset_name(doc["app_version"], os_tok, doc["arch"], name)
            if e["asset"] != want:
                errs.append(f"{where} asset {e['asset']!r} != re-derived {want!r}")
        if not isinstance(e["sha256"], str) or not _SHA_RE.match(e["sha256"]):
            errs.append(f"{where} sha256 is not 64 lowercase hex")
        for k in ("size", "unpacked_bytes", "files"):
            if not isinstance(e[k], int) or isinstance(e[k], bool) or e[k] < 0:
                errs.append(f"{where} {k} is not a non-negative int")
        if isinstance(e["size"], int) and e["size"] > PACK_MAX_BYTES:
            errs.append(f"{where} size over PACK_MAX_BYTES")
        if not isinstance(e["features"], list) or not all(
            isinstance(f, str) and f for f in e["features"]
        ):
            errs.append(f"{where} features is not a list of slugs")
    return errs


def index_bytes(doc: Mapping[str, Any]) -> bytes:
    return pretty_json(doc)


# ======================================================================================
# Pure: the release check
# ======================================================================================


def parse_sha256sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line.strip())
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def check_release(index_doc: Any, index_name: str, sums: Mapping[str, str],
                  assets: Iterable[str], index_sha256: str | None = None) -> list[str]:
    """Every pack in a *published* index is attached and listed with the same hash."""
    problems = [f"{index_name}: {e}" for e in validate_index(index_doc)]
    if problems:
        return problems
    attached = set(assets)
    os_tok = os_token(index_doc["platform"])
    want_index = index_asset_name(index_doc["app_version"], os_tok, index_doc["arch"])
    if index_name != want_index:
        problems.append(f"index is attached as {index_name!r}, expected {want_index!r}")
    if index_name not in sums:
        problems.append(f"{index_name} is not listed in SHA256SUMS.txt")
    elif index_sha256 is not None and sums[index_name] != index_sha256:
        problems.append(f"{index_name}: SHA256SUMS.txt does not match the downloaded index")
    if not index_doc["packs"]:
        problems.append(f"{index_name} lists no packs; an empty index should not be published")
    for e in index_doc["packs"]:
        asset = e["asset"]
        if asset not in attached:
            problems.append(f"{asset} is in the index but not attached to the release")
        if asset not in sums:
            problems.append(f"{asset} is not listed in SHA256SUMS.txt")
        elif sums[asset] != e["sha256"]:
            problems.append(f"{asset}: SHA256SUMS.txt and the index disagree")
    return problems


# ======================================================================================
# Pure: the packs.toml catalogue
# ======================================================================================


@dataclass(frozen=True)
class PackSpec:
    name: str
    extra: str
    features: tuple[str, ...]
    entry_modules: tuple[str, ...]
    approved_large: bool = False


def _norm_req(req: str) -> str:
    return re.sub(r"\s+", "", req).lower()


def validate_catalog(doc: Any, extras: Mapping[str, list[str]],
                     feature_deps: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]],
                     unwired: Iterable[str]) -> list[str]:
    """packs.toml against pyproject extras and features._FEATURE_DEPS (§7)."""
    if not isinstance(doc, dict) or doc.get("format") != 1:
        return ["packs.toml: missing or unknown `format`"]
    table = doc.get("extras")
    if not isinstance(table, dict) or not table:
        return ["packs.toml: no [extras.*] decisions at all"]
    unwired = set(unwired)
    errs: list[str] = []
    missing = sorted(set(extras) - set(table))
    stale = sorted(set(table) - set(extras))
    errs += [f"extra {m!r} has no decision in packs.toml" for m in missing]
    errs += [f"packs.toml decides {s!r}, which is not a pyproject extra" for s in stale]
    for name, entry in sorted(table.items()):
        if not isinstance(entry, dict):
            errs.append(f"{name}: not a table")
            continue
        decision = entry.get("decision")
        if decision not in DECISIONS:
            errs.append(f"{name}: decision {decision!r} not one of {DECISIONS}")
            continue
        if decision != "pack":
            if not str(entry.get("reason", "")).strip():
                errs.append(f"{name}: a {decision!r} decision needs a reason")
            continue
        if not _NAME_RE.match(name):
            errs.append(f"{name}: not a valid pack name")
        feats = entry.get("features")
        if not isinstance(feats, list) or not feats:
            errs.append(f"{name}: a pack needs `features`")
            feats = []
        mods = entry.get("entry_modules")
        if not isinstance(mods, list) or not mods or not all(
            isinstance(m, str) and _MODULE_RE.match(m) for m in mods
        ):
            errs.append(f"{name}: a pack needs `entry_modules` (dotted module names)")
        if entry.get("approved_large") and not str(entry.get("approved_by", "")).strip():
            errs.append(f"{name}: approved_large needs approved_by")
        extra_reqs = {_norm_req(r) for r in extras.get(name, [])}
        for slug in feats:
            if slug not in feature_deps:
                errs.append(f"{name}: feature {slug!r} is not in _FEATURE_DEPS")
                continue
            if slug in unwired:
                errs.append(f"{name}: feature {slug!r} is unwired; it cannot have a pack")
            need = {_norm_req(r) for r in feature_deps[slug][1]}
            if not need <= extra_reqs:
                errs.append(
                    f"{name}: feature {slug!r} installs {sorted(need - extra_reqs)}, "
                    f"which the {name!r} extra does not declare"
                )
    # Completeness: every wired dependency-carrying slug is served by some extra, and if
    # any serving extra is a pack, the slug is listed in that pack.
    for slug, (_imports, reqs) in sorted(feature_deps.items()):
        if slug in unwired:
            continue
        need = {_norm_req(r) for r in reqs}
        serving = [
            x for x, rs in extras.items()
            if x != "all" and need <= {_norm_req(r) for r in rs}
        ]
        if not serving:
            errs.append(f"feature {slug!r}: no extra declares {sorted(need)}")
            continue
        for x in serving:
            entry = table.get(x)
            if isinstance(entry, dict) and entry.get("decision") == "pack":
                if slug not in (entry.get("features") or []):
                    errs.append(f"feature {slug!r} is served by pack {x!r} but not listed in it")
    return errs


def packs_from_catalog(doc: Mapping[str, Any]) -> list[PackSpec]:
    out = []
    for name, entry in sorted(doc["extras"].items()):
        if entry.get("decision") == "pack":
            out.append(PackSpec(
                name=name, extra=name, features=tuple(entry["features"]),
                entry_modules=tuple(entry["entry_modules"]),
                approved_large=bool(entry.get("approved_large", False)),
            ))
    return out


def size_errors(size: int, approved_large: bool) -> list[str]:
    if size > PACK_MAX_BYTES:
        return [f"archive is {size} bytes, over the {PACK_MAX_BYTES}-byte ceiling"]
    if size > LARGE_PACK_BYTES and not approved_large:
        return [f"archive is {size} bytes, over 500 MiB, and packs.toml has no approved_large"]
    return []


# ======================================================================================
# Pure: the Phase 0 spike
# ======================================================================================


def inject_runtime_hook(spec_text: str, hook_path: str) -> str:
    """Put one runtime hook first in a PyInstaller spec's ``runtime_hooks=[...]``."""
    count = len(re.findall(r"runtime_hooks\s*=\s*\[", spec_text))
    if count != 1:
        raise ValueError(f"expected exactly one runtime_hooks=[ in the spec, found {count}")
    return re.sub(
        r"runtime_hooks\s*=\s*\[",
        lambda m: f"{m.group(0)}{hook_path!r}, ",
        spec_text,
        count=1,
    )


def scan_imports(source: str) -> set[str]:
    """Absolute module names a source file imports (any depth, any branch)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def spike_candidates(imported: Iterable[str], stdlib: Iterable[str], pack_modules: set[str],
                     base_modules: set[str]) -> tuple[list[str], list[str]]:
    """(stdlib top-level names, dotted base submodules) a pack's code refers to."""
    std = set(stdlib)
    pack_l = {m.lower() for m in pack_modules}
    base_l = {m.lower() for m in base_modules}
    stdlib_hits: set[str] = set()
    base_subs: set[str] = set()
    for name in imported:
        top = name.split(".", 1)[0]
        if top.lower() in pack_l:
            continue
        if top in std:
            stdlib_hits.add(top)
        elif top.lower() in base_l and "." in name:
            base_subs.add(name)
    return sorted(stdlib_hits), sorted(base_subs)


PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


def spike_verdicts(entry: Mapping[str, Any], result: Mapping[str, Any] | None
                   ) -> list[tuple[str, str, str]]:
    """One (probe, verdict, detail) row per ADR-028 open risk, for one pack.

    ``entry`` is the pack's build-report entry, ``result`` what the frozen hook wrote.
    """
    rows: list[tuple[str, str, str]] = []
    conflicts = list(entry.get("dll_conflicts", []))
    dropped = list(entry.get("dll_dropped", []))
    if result is None:
        rows.append(("frozen probe ran", FAIL, "the hook wrote no result"))
        rows.append(("(d) DLL basename collisions", FAIL if conflicts else PASS,
                     "; ".join(conflicts) or f"none ({len(dropped)} identical dropped)"))
        return rows
    if result.get("crash"):
        rows.append(("frozen probe ran", FAIL, str(result["crash"])[:300]))
        return rows
    rows.append(("probe ran inside the frozen app", PASS if result.get("frozen") else FAIL,
                 f"sys.frozen={result.get('frozen')}, _MEIPASS={result.get('meipass')}"))
    imports = result.get("entry", {})
    failed = {m: r for m, r in imports.items() if not r.get("ok")}
    rows.append((
        "mount: sys.path append makes pack modules importable",
        FAIL if failed or not imports else PASS,
        "; ".join(f"{m}: {r.get('error', '')[:160]}" for m, r in failed.items())
        or ", ".join(f"{m} from {r.get('file')}" for m, r in imports.items()),
    ))
    failures = [*failed.values(), *result.get("sweep_failures", [])]
    kinds: dict[str, list[str]] = {}
    for f in failures:
        kinds.setdefault(str(f.get("kind", "other")), []).append(
            str(f.get("missing") or f.get("module") or f.get("error", ""))[:120]
        )
    std_missing = list(result.get("stdlib_missing", []))
    if kinds.get("stdlib"):
        rows.append(("(a) stdlib modules present in the frozen app", FAIL,
                     "import failed on: " + ", ".join(sorted(set(kinds["stdlib"])))))
    elif std_missing:
        rows.append(("(a) stdlib modules present in the frozen app", WARN,
                     "referenced but absent (not hit by the import sweep): "
                     + ", ".join(std_missing)))
    else:
        rows.append(("(a) stdlib modules present in the frozen app", PASS,
                     f"{len(result.get('stdlib_checked', []))} referenced stdlib modules import"))
    md = result.get("metadata", {})
    own_missing = [d for d, v in md.get("pack", {}).items() if not v]
    rows.append(("(b) importlib.metadata sees the pack's dist-info",
                 FAIL if own_missing or not md.get("pack") else PASS,
                 ("missing: " + ", ".join(own_missing)) if own_missing
                 else ", ".join(f"{d} {v}" for d, v in md.get("pack", {}).items())))
    base_missing = [d for d, v in md.get("base", {}).items() if not v]
    rows.append(("(b) importlib.metadata sees base distributions the pack requires",
                 FAIL if base_missing else PASS,
                 ("no dist-info in the frozen base for: " + ", ".join(base_missing))
                 if base_missing else f"{len(md.get('base', {}))} checked"))
    sub_missing = list(result.get("base_submodules_missing", []))
    if kinds.get("base-submodule"):
        rows.append(("(c) base submodules PyInstaller did not prune", FAIL,
                     "import failed on: " + ", ".join(sorted(set(kinds["base-submodule"])))))
    elif sub_missing:
        rows.append(("(c) base submodules PyInstaller did not prune", WARN,
                     "referenced but absent: " + ", ".join(sub_missing)))
    else:
        rows.append(("(c) base submodules PyInstaller did not prune", PASS,
                     f"{len(result.get('base_submodules_checked', []))} referenced submodules import"))
    loaded = result.get("loaded_collisions", {})
    detail = "; ".join(conflicts) or f"none ({len(dropped)} identical copies dropped)"
    if loaded:
        detail += " | loaded: " + "; ".join(f"{b} <- {', '.join(p)}" for b, p in sorted(loaded.items()))
    rows.append(("(d) DLL basename collisions with the base (e.g. onnxruntime.dll)",
                 FAIL if conflicts else PASS, detail))
    other = kinds.get("other", []) + kinds.get("base", [])
    rows.append(("deep import sweep", WARN if other else INFO,
                 f"{result.get('sweep_imported', 0)} submodules imported; "
                 f"{len(result.get('sweep_failures', []))} failed"
                 + (": " + ", ".join(sorted(set(other))[:12]) if other else "")))
    rows.append(("pack size on this platform", INFO,
                 f"archive {entry.get('size', 0):,} B, unpacked {entry.get('unpacked_bytes', 0):,} B, "
                 f"{entry.get('files', 0)} files"))
    return rows


def render_summary(title: str, packs: Mapping[str, list[tuple[str, str, str]]]) -> str:
    lines = [f"## {title}", ""]
    for name, rows in sorted(packs.items()):
        lines += [f"### `{name}`", "", "| Probe | Result | Detail |", "|---|---|---|"]
        for probe, verdict, detail in rows:
            safe = detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {probe} | **{verdict}** | {safe} |")
        lines.append("")
        lines += [f"{verdict}: {name}: {probe}" for probe, verdict, _ in rows
                  if verdict in (PASS, FAIL)]
        lines.append("")
    return "\n".join(lines) + "\n"


# ======================================================================================
# I/O below this line
# ======================================================================================


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_tree(root: Path, exclude: Iterable[str] = ()) -> list[tuple[str, int, str]]:
    skip = set(exclude)
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in skip:
            continue
        out.append((rel, path.stat().st_size, sha256_file(path)))
    return out


def python_facts() -> dict[str, str]:
    return {
        "cache_tag": str(sys.implementation.cache_tag),
        "version": platform.python_version(),
        "abi": f"cp{sys.version_info.major}{sys.version_info.minor}",
    }


def read_project() -> tuple[str, dict[str, list[str]]]:
    with PYPROJECT.open("rb") as fh:
        doc = tomllib.load(fh)
    return str(doc["project"]["version"]), dict(doc["project"]["optional-dependencies"])


def load_catalog(path: Path = PACKS_TOML) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False, **kw)


def uv_export(extras: Iterable[str]) -> dict[str, str]:
    cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header",
           "--format", "requirements-txt"]
    for e in extras:
        cmd += ["--extra", e]
    out = _run(cmd, cwd=ROOT)
    if out.returncode != 0:
        raise PackError(f"uv export failed: {out.stderr.strip()[-600:]}")
    return parse_requirements_export(out.stdout)


def installed_distributions() -> dict[str, Any]:
    import importlib.metadata as md

    return {canonical_name(d.metadata["Name"]): d for d in md.distributions()
            if d.metadata["Name"]}


def safe_extract(archive: Path, dest: Path) -> None:
    """Extraction with the same name rules the runtime applies (§6)."""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            errs = member_path_errors(info.filename)
            if info.is_dir() or errs or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackError(f"refusing member {info.filename!r}: {errs or 'not a file'}")
            target = dest / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def gh_annotation(level: str, title: str, message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title={title}::{message.replace(chr(10), ' ')}")


def append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


@dataclass
class Context:
    dist: Path
    work: Path
    version: str
    arch: str
    platform_tag: str
    python: dict[str, str]
    base_build_id: str
    base_names: set[str]
    base_modules: set[str]
    base_dlls: dict[str, str]
    base_installed: dict[str, Any]
    report_only: bool = False


def base_context(dist: Path, work: Path, version: str, arch: str) -> tuple[Context, bytes]:
    if not (dist / "_internal").is_dir():
        raise SystemExit(f"{dist}/_internal is missing: not a PyInstaller >= 6 one-folder bundle")
    manifest = base_manifest(scan_tree(dist, exclude={EMBEDDED_INDEX}))
    work.mkdir(parents=True, exist_ok=True)
    (work / "base-manifest.json").write_bytes(manifest)
    installed = installed_distributions()
    exported = set(uv_export(["desktop"]))
    base_names = exported & set(installed)
    base_modules: set[str] = set(sys.stdlib_module_names)
    for name in base_names:
        files = installed[name].files or []
        base_modules |= top_level_modules(str(f) for f in files)
    internal = dist / "_internal"
    base_modules |= top_level_modules(
        p.relative_to(internal).as_posix() for p in internal.rglob("*") if p.is_file()
    )
    base_dlls = {
        p.relative_to(dist).as_posix(): sha256_file(p)
        for p in dist.rglob("*") if p.is_file() and p.suffix.lower() == ".dll"
    }
    ctx = Context(
        dist=dist, work=work, version=version, arch=arch,
        platform_tag=host_platform(), python=python_facts(),
        base_build_id=build_id_of(manifest), base_names=base_names,
        base_modules=base_modules, base_dlls=base_dlls, base_installed=installed,
    )
    return ctx, manifest


def _dist_infos(site: Path) -> list[Path]:
    return sorted(p for p in site.iterdir() if p.is_dir() and p.name.endswith(".dist-info"))


def _metadata(dist_info: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    text = (dist_info / "METADATA").read_text(encoding="utf-8", errors="replace")
    for line in text.split("\n\n", 1)[0].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def _licence_gate() -> Any:
    """``scripts/pack_licences.py`` (ADR-028 Q7), imported lazily so that
    ``check-release`` keeps running on a bare python3 with the standard library alone.
    Loaded by path, so ``scripts/`` never lands on ``sys.path``."""
    mod = sys.modules.get("pack_licences")
    if mod is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pack_licences", Path(__file__).resolve().parent / "pack_licences.py")
        assert spec is not None and spec.loader is not None
        mod = sys.modules["pack_licences"] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def build_one(spec: PackSpec, ctx: Context, built: Mapping[str, Mapping[str, str]]
              ) -> dict[str, Any]:
    """Build one pack into ``work/<name>``. Raises PackError with the withholding reason."""
    wdir = ctx.work / spec.name
    shutil.rmtree(wdir, ignore_errors=True)
    root = wdir / "root"
    site = root / "site"
    site.mkdir(parents=True)
    report: dict[str, Any] = {"name": spec.name, "extra": spec.extra,
                              "features": list(spec.features)}

    marginal = marginal_requirements(uv_export(["desktop", spec.extra]), ctx.base_names)
    if not marginal:
        raise PackError("the extra adds nothing beyond the base (decide `bundled` instead)")
    req = wdir / "requirements.txt"
    req.write_text(render_requirements(marginal), encoding="utf-8")
    report["requirements"] = sorted(marginal)
    out = _run(["uv", "pip", "install", "--target", str(site), "--python", sys.executable,
                "--no-deps", "--require-hashes", "--only-binary", ":all:",
                "--compile-bytecode", "-r", str(req)], cwd=ROOT)
    if out.returncode != 0:
        raise PackError(f"uv pip install failed: {out.stderr.strip()[-800:]}")
    for scripts in ("bin", "Scripts"):
        shutil.rmtree(site / scripts, ignore_errors=True)

    path_entries: list[str] = []
    for pth in sorted(site.glob("*.pth")):
        path_entries += pth_path_entries(pth.read_text(encoding="utf-8", errors="replace"))
        pth.unlink()

    dists = []
    requires: set[str] = set()
    licences: dict[str, Path] = {}
    report["licences"] = {}
    for di in _dist_infos(site):
        meta = _metadata(di)
        name = meta.get("Name", [di.name.split("-")[0]])[0]
        dists.append({"name": name, "version": meta.get("Version", ["?"])[0]})
        report["licences"][name] = (meta.get("License-Expression") or meta.get("License")
                                    or ["(not declared)"])[0][:120]
        for r in meta.get("Requires-Dist", []):
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", r)
            # Extra-gated lines count too: the pack was installed with the extras the
            # pyproject requirement names (onnx-asr[cpu,hub]), so they are live.
            if m:
                requires.add(canonical_name(m.group(1)))
        for f in sorted(di.rglob("*")):
            rel = f.relative_to(di).as_posix()
            if f.is_file() and licence_member(di.name, rel):
                licences[f"LICENSES/{canonical_name(name)}/{rel}"] = f
    overlap = sorted(canonical_name(d["name"]) for d in dists
                     if canonical_name(d["name"]) in ctx.base_names)
    if overlap:
        raise PackError(f"distributions already in the base: {overlap}")
    report["base_requires"] = sorted(requires & ctx.base_names)
    lic = _licence_gate().check_pack(spec.name, _dist_infos(site))
    report["licence_gate"] = lic.report()
    if lic.problems and not ctx.report_only:
        raise PackError("licence gate: " + "; ".join(lic.problems))

    rels = [p.relative_to(site).as_posix() for p in sorted(site.rglob("*")) if p.is_file()]
    pack_modules = top_level_modules(rels)
    clash = module_collisions(pack_modules, ctx.base_modules)
    if clash:
        raise PackError(f"top-level modules the base already provides: {clash}")
    report["top_level_modules"] = sorted(pack_modules)

    pack_dlls = {r: sha256_file(site / r) for r in rels if r.lower().endswith(".dll")}
    dll = dll_collisions({f"site/{r}": d for r, d in pack_dlls.items()}, ctx.base_dlls, built)
    report["dll_conflicts"] = dll.conflicts
    report["dll_dropped"] = dll.drop
    report["dll_shared_identical"] = dll.shared_identical
    report["dlls"] = {f"site/{r}": d for r, d in pack_dlls.items()}
    if dll.conflicts and not ctx.report_only:
        raise PackError("DLL basename collision: " + "; ".join(dll.conflicts))
    for rel in dll.drop:
        (root / rel).unlink()

    rels = [p.relative_to(site).as_posix() for p in sorted(site.rglob("*")) if p.is_file()]
    natives = native_dirs(rels)

    imported: set[str] = set()
    for r in rels:
        if r.endswith(".py") and "/tests/" not in f"/{r}" and "/test/" not in f"/{r}":
            imported |= scan_imports((site / r).read_text(encoding="utf-8", errors="replace"))
    std, subs = spike_candidates(imported, sys.stdlib_module_names, pack_modules,
                                 ctx.base_modules)
    import importlib.util

    report["stdlib_candidates"] = [s for s in std if importlib.util.find_spec(s) is not None]
    report["base_submodule_candidates"] = subs

    members: dict[str, bytes | Path] = {f"site/{r}": site / r for r in rels}
    members.update(licences)
    if lic.source_md:
        members[_licence_gate().SOURCE_MD] = lic.source_md.encode("utf-8")
    errors = [f"{n}: {'; '.join(e)}" for n in members if (e := member_path_errors(n))]
    if errors:
        raise PackError("path rule: " + "; ".join(errors[:5]))
    payload = [(n, p.stat().st_size if isinstance(p, Path) else len(p),
                sha256_file(p) if isinstance(p, Path) else sha256_bytes(p))
               for n, p in members.items()]
    record = record_json(payload)
    fields = pack_fields(
        name=spec.name, extra=spec.extra, features=list(spec.features),
        app_version=ctx.version, base_build_id=ctx.base_build_id, python=ctx.python,
        platform_tag=ctx.platform_tag, arch=ctx.arch, distributions=dists,
        entry_modules=list(spec.entry_modules), native=natives, path_entries=path_entries,
    )
    fields["licences"] = lic.pack_json()
    pj = pack_json(fields, sum(s for _, s, _ in payload), len(payload), len(record))
    members["RECORD.json"] = record
    members["pack.json"] = pj
    asset = pack_asset_name(ctx.version, os_token(ctx.platform_tag), ctx.arch, spec.name)
    archive = wdir / asset
    write_deterministic_zip(archive, members)
    size = archive.stat().st_size
    problems = size_errors(size, spec.approved_large)
    if problems:
        raise PackError("; ".join(problems))
    doc = json.loads(pj)
    report.update(
        asset=asset, archive=str(archive), sha256=sha256_file(archive), size=size,
        unpacked_bytes=doc["unpacked_bytes"], files=doc["files"], pack_json=doc,
    )
    return report


def run_probe(exe: Path, report: Mapping[str, Any], work: Path) -> tuple[bool, str]:
    staged = work / "probe" / report["name"]
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    safe_extract(Path(report["archive"]), staged)
    home = work / "probe-home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("YAZSES_NO_PACKS", None)
    for var in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_CONFIG_HOME",
                "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        env[var] = str(home)
    args = [a.format(name=report["name"], staged=str(staged)) for a in PROBE_ARGS]
    try:
        out = _run([str(exe), *args], env=env, timeout=PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"probe timed out after {PROBE_TIMEOUT_S}s"
    except OSError as exc:
        return False, f"probe could not start: {exc}"
    tail = (out.stdout + out.stderr).strip()[-600:]
    return out.returncode == 0, f"exit {out.returncode}: {tail}"


def cmd_build(args: argparse.Namespace) -> int:
    """Pack production must never cost the release its base installer.

    A pack-level failure withholds that pack (inside ``_build``). Anything else that
    goes wrong withholds *every* pack: the embedded index and ``--out`` are removed, the
    base is re-checked against the manifest taken before any pack work, and the build
    continues without packs. Only a base that changed fails the command.
    """
    try:
        return _build(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- reported, then the base ships without packs
        dist = Path(args.dist)
        (dist / EMBEDDED_INDEX).unlink(missing_ok=True)
        shutil.rmtree(Path(args.out), ignore_errors=True)
        before = Path(args.work) / "base-manifest.json"
        if before.is_file() and before.read_bytes() != base_manifest(
            scan_tree(dist, exclude={EMBEDDED_INDEX})
        ):
            print("ERROR: dist/ changed during pack production", file=sys.stderr)
            return 1
        why = f"{type(exc).__name__}: {exc}"
        print(f"WARNING: no add-on packs built: {why}", file=sys.stderr)
        gh_annotation("warning", "add-on packs not built", why)
        append_summary(f"## Add-on packs (ADR-028)\n\nNo pack was built: `{why[:300]}`\n\n")
        return 1 if args.strict else 0


def _build(args: argparse.Namespace) -> int:
    version = args.version or read_project()[0]
    dist, work, out_dir = Path(args.dist), Path(args.work), Path(args.out)
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    embedded = dist / EMBEDDED_INDEX
    embedded.unlink(missing_ok=True)

    ctx, manifest = base_context(dist, work, version, args.arch)
    ctx.report_only = args.skip_probe
    print(f"base_build_id {ctx.base_build_id} ({ctx.python['version']}, {ctx.platform_tag})")
    catalog = load_catalog(Path(args.catalog))
    _, extras = read_project()
    report: dict[str, Any] = {"base_build_id": ctx.base_build_id, "app_version": version,
                              "python": ctx.python, "platform": ctx.platform_tag,
                              "arch": ctx.arch, "base_dlls": ctx.base_dlls,
                              "base_modules": sorted(ctx.base_modules - set(sys.stdlib_module_names)),
                              "packs": {}, "withheld": {}}
    built: dict[str, dict[str, Any]] = {}
    for spec in packs_from_catalog(catalog):
        if spec.extra not in extras:
            report["withheld"][spec.name] = "not a pyproject extra"
            continue
        try:
            entry = build_one(spec, ctx, {n: e["dlls"] for n, e in built.items()})
        except Exception as exc:  # noqa: BLE001 -- any failure withholds this pack only
            if not isinstance(exc, PackError):
                exc = PackError(f"{type(exc).__name__}: {exc}")
            report["withheld"][spec.name] = str(exc)
            gh_annotation("warning", f"add-on pack {spec.name} withheld", str(exc))
            print(f"WITHHELD {spec.name}: {exc}")
            continue
        built[spec.name] = entry
        print(f"built {entry['asset']} {entry['size']:,} B sha256 {entry['sha256']}")

    def write_index(names: Iterable[str]) -> dict[str, Any] | None:
        entries = [index_entry(name=n, asset=built[n]["asset"], sha256=built[n]["sha256"],
                               size=built[n]["size"],
                               unpacked_bytes=built[n]["unpacked_bytes"],
                               files=built[n]["files"], features=built[n]["features"])
                   for n in names]
        if not entries:
            embedded.unlink(missing_ok=True)
            return None
        doc = build_index(app_version=version, base_build_id=ctx.base_build_id,
                          python=ctx.python, platform_tag=ctx.platform_tag, arch=ctx.arch,
                          entries=entries)
        embedded.write_bytes(index_bytes(doc))
        return doc

    if args.skip_probe:
        report["packs"] = built
        (work / "build-report.json").write_bytes(pretty_json(report))
        print("--skip-probe: nothing embedded, nothing written to --out (spike/diagnostic mode)")
        return 0

    # Provisional index first, so a probe that consults the embedded index sees it.
    write_index(built)
    passed = []
    for name in sorted(built):
        ok, detail = run_probe(Path(args.probe_exe), built[name], work)
        built[name]["probe"] = detail
        if ok:
            passed.append(name)
            print(f"probe ok {name}")
        else:
            report["withheld"][name] = f"frozen probe failed: {detail}"
            gh_annotation("warning", f"add-on pack {name} withheld",
                          f"frozen probe failed: {detail}")
            print(f"WITHHELD {name}: frozen probe failed: {detail}")
    final = write_index(passed)

    # The guard that pack production left the base installer's contents unchanged.
    after = base_manifest(scan_tree(dist, exclude={EMBEDDED_INDEX}))
    if after != manifest:
        embedded.unlink(missing_ok=True)
        print("ERROR: dist/ changed during pack production; base-manifest is not invariant",
              file=sys.stderr)
        return 1

    report["packs"] = {n: built[n] for n in passed}
    (work / "build-report.json").write_bytes(pretty_json(report))
    if final is not None:
        out_dir.mkdir(parents=True)
        for n in passed:
            shutil.copy2(built[n]["archive"], out_dir / built[n]["asset"])
        idx_name = index_asset_name(version, os_token(ctx.platform_tag), ctx.arch)
        (out_dir / idx_name).write_bytes(embedded.read_bytes())
        print(f"published {len(passed)} pack(s) + {idx_name}; embedded {EMBEDDED_INDEX}")
    else:
        print("no pack passed every check; nothing embedded, nothing published")

    lines = ["## Add-on packs (ADR-028)", "", f"`base_build_id` `{ctx.base_build_id}`", "",
             "| Pack | Result | Size | Detail |", "|---|---|---|---|"]
    for n in passed:
        lines.append(f"| {n} | **published** | {built[n]['size']:,} B | sha256 `{built[n]['sha256']}` |")
    for n, why in sorted(report["withheld"].items()):
        lines.append(f"| {n} | **withheld** | | {why[:300].replace('|', '/')} |")
    append_summary("\n".join(lines) + "\n\n")
    if args.strict and report["withheld"]:
        return 1
    return 0


def cmd_check_release(args: argparse.Namespace) -> int:
    sums = parse_sha256sums(Path(args.sums).read_text(encoding="utf-8"))
    assets = [ln.strip() for ln in Path(args.assets).read_text(encoding="utf-8").splitlines()
              if ln.strip()]
    problems = []
    for path in map(Path, args.index):
        data = path.read_bytes()
        try:
            doc = json.loads(data)
        except ValueError as exc:
            problems.append(f"{path.name}: not JSON ({exc})")
            continue
        problems += check_release(doc, path.name, sums, assets, sha256_bytes(data))
        print(f"{path.name}: {len(doc.get('packs', []))} pack(s) checked")
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if not args.index:
        print("ERROR: no index given", file=sys.stderr)
        return 1
    return 1 if problems else 0


def cmd_validate(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from yazses.system import features

    _, extras = read_project()
    errs = validate_catalog(load_catalog(Path(args.catalog)), extras,
                            features._FEATURE_DEPS, features._UNWIRED)
    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    print("packs.toml ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


def cmd_spike_spec(args: argparse.Namespace) -> int:
    src = Path(args.spec)
    text = src.read_text(encoding="utf-8")
    Path(args.out).write_text(inject_runtime_hook(text, str(Path(args.hook).resolve())),
                              encoding="utf-8")
    print(f"wrote {args.out} with runtime hook {args.hook}")
    return 0


def cmd_spike_probe(args: argparse.Namespace) -> int:
    work = Path(args.work)
    report = json.loads((work / "build-report.json").read_text(encoding="utf-8"))
    exe = Path(args.exe)
    base_modules = report["base_modules"]
    base_dll_names: dict[str, list[str]] = {}
    for rel in report["base_dlls"]:
        base_dll_names.setdefault(PurePosixPath(rel).name.lower(), []).append(rel)
    verdicts: dict[str, list[tuple[str, str, str]]] = {}
    harness_ok = True
    for name, entry in sorted(report["packs"].items()):
        staged = work / "spike" / name
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        safe_extract(Path(entry["archive"]), staged)
        pj = entry["pack_json"]
        result_path = work / "spike" / f"{name}.result.json"
        result_path.unlink(missing_ok=True)
        collided = sorted({PurePosixPath(r).name.lower() for r in entry["dlls"]}
                          & set(base_dll_names))
        request = {
            "site": str(staged / "site"),
            "extra_paths": [str(staged / p) for p in pj.get("path_entries", [])],
            "native_dirs": [str(staged / d) for d in pj["native_dirs"]],
            "entry_modules": pj["entry_modules"],
            "pack_packages": entry["top_level_modules"],
            "distributions": [d["name"] for d in pj["distributions"]],
            "base_requires": entry["base_requires"],
            "stdlib_candidates": entry["stdlib_candidates"],
            "base_submodule_candidates": entry["base_submodule_candidates"],
            "base_modules": base_modules,
            "collided_dlls": collided,
            "result": str(result_path),
        }
        req_path = work / "spike" / f"{name}.request.json"
        req_path.write_bytes(pretty_json(request))
        env = dict(os.environ, YAZSES_PACK_SPIKE_REQUEST=str(req_path))
        try:
            out = _run([str(exe), "--version"], env=env, timeout=args.timeout)
            print(f"{name}: hook exit {out.returncode}\n{out.stdout[-2000:]}{out.stderr[-2000:]}")
        except subprocess.TimeoutExpired:
            print(f"{name}: timed out after {args.timeout}s")
        result = (json.loads(result_path.read_text(encoding="utf-8"))
                  if result_path.is_file() else None)
        if result is None:
            harness_ok = False
        verdicts[name] = spike_verdicts(entry, result)
    for name, why in sorted(report["withheld"].items()):
        verdicts[name] = [("pack built", FAIL, why)]
    summary = render_summary(
        f"ADR-028 Phase 0 spike: Python {report['python']['version']}, {report['platform']}",
        verdicts,
    )
    print(summary)
    append_summary(summary)
    (work / "spike-summary.md").write_text(summary, encoding="utf-8")
    return 0 if harness_ok and report["packs"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build, probe, index and embed the packs")
    b.add_argument("--dist", default="dist/YazSes")
    b.add_argument("--out", default="dist/packs")
    b.add_argument("--work", default="build/packs")
    b.add_argument("--arch", required=True)
    b.add_argument("--version", help="defaults to pyproject's [project] version")
    b.add_argument("--catalog", default=str(PACKS_TOML))
    mode = b.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe-exe", help="the frozen yazses-cli.exe that probes each pack")
    mode.add_argument("--skip-probe", action="store_true",
                      help="diagnostics only: keep packs in --work, embed and publish nothing")
    b.add_argument("--strict", action="store_true", help="exit 1 if any pack is withheld")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check-release", help="a published index against the release")
    c.add_argument("--sums", required=True)
    c.add_argument("--assets", required=True, help="file with one asset name per line")
    c.add_argument("index", nargs="*")
    c.set_defaults(func=cmd_check_release)

    v = sub.add_parser("validate", help="packs.toml against pyproject and _FEATURE_DEPS")
    v.add_argument("--catalog", default=str(PACKS_TOML))
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("spike-spec", help="copy the spec with the Phase 0 runtime hook")
    s.add_argument("--spec", default="packaging/windows/yazses.spec")
    s.add_argument("--hook", default=str(SPIKE_HOOK))
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_spike_spec)

    p = sub.add_parser("spike-probe", help="Phase 0: probe every built pack in the frozen app")
    p.add_argument("--work", default="build/packs")
    p.add_argument("--exe", default="dist/YazSes/yazses-cli.exe")
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_spike_probe)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
