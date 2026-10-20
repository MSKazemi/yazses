"""The pack install transaction (ADR-028 §6). Never raises to the UI.

    lock -> disk space -> download + verify -> extract to staging (members checked
    first, tree checked against RECORD.json after) -> match against this base ->
    import probe in a child process -> one same-volume os.replace into place ->
    COMPLETE -> state.json -> delete the archive

If any step fails, the staging tree and the download are deleted, the previous tree (if
any) is put back, config is never touched (the caller writes it only after
``ok``), and :class:`InstallResult` names the step and the next thing to do. Every
dependency is injected (``fetch``, ``extract``, ``probe``, ``replace``, ``clock``,
``free_bytes``), so the transaction is tested with fakes and no network.

Who calls it: the process where the user clicked — the CLI, the tray or Settings. Never
the daemon, the update watcher or the runtime hook (a closure test enforces it).
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.packs.abi import BaseIdentity, match
from yazses.packs.archive import check_tree, validate_members
from yazses.packs.layout import COMPLETE, PackLayout, build_dir_name
from yazses.packs.manifest import (
    IndexEntry,
    ManifestError,
    PackIndex,
    PackManifest,
    parse_manifest,
    parse_record,
)
from yazses.packs.policy import disk_problem, gc_plan, size_problem
from yazses.packs.state import (
    claimed_dirs,
    record_install,
    record_result,
    remove_build,
    started_ok,
)

if TYPE_CHECKING:
    from yazses.platform.base import PackRuntime

__all__ = [
    "LOCK_STALE_S",
    "PROBE_TIMEOUT_S",
    "ExtractError",
    "InstallResult",
    "extract_archive",
    "install_pack",
    "quarantine_tree",
    "subprocess_probe",
    "builds_on_disk",
    "tree_hash",
    "tree_stat",
]

#: A lock older than this belongs to an attempt that died (ADR-028 §6: "stale after 2 h").
LOCK_STALE_S = 2 * 3600.0
#: The import probe's wall-clock budget (ADR-028 §6).
PROBE_TIMEOUT_S = 120.0
_CHUNK = 1 << 16
_MAX_META = 1 << 20

Progress = Callable[[str, "float | None"], None]
Fetch = Callable[..., Path]
Extract = Callable[[Path, Path], PackManifest]
Probe = Callable[[str, Path], "tuple[bool, str]"]


class ExtractError(Exception):
    """The archive was refused before or during extraction. ``str()`` is a sentence."""


@dataclass
class InstallResult:
    """What an install came to. ``ok`` means the pack is in place and the caller may now
    write config; anything else means nothing changed, and ``steps`` say what to do."""

    ok: bool
    title: str
    message: str
    steps: list[str] = field(default_factory=list)
    log_file: Path | None = None
    step: str = ""


# ---- the default extractor -----------------------------------------------------

def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise ExtractError(f"the archive has no {name}") from None
    if info.file_size > _MAX_META:
        raise ExtractError(f"the archive's {name} is implausibly large")
    with zf.open(info) as fh:
        data = fh.read(_MAX_META + 1)
    if len(data) > _MAX_META:
        raise ExtractError(f"the archive's {name} is implausibly large")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_stat(root: Path) -> Callable[[str], int | None]:
    def stat(rel: str) -> int | None:
        try:
            p = root / Path(*rel.split("/"))
            return p.stat().st_size if p.is_file() else None
        except OSError:
            return None
    return stat


def tree_hash(root: Path) -> Callable[[str], str | None]:
    def digest(rel: str) -> str | None:
        try:
            return _sha256(root / Path(*rel.split("/")))
        except OSError:
            return None
    return digest


def extract_archive(archive: Path, staging: Path) -> PackManifest:
    """Validate every member, extract into ``staging`` (which must not exist), and check
    the result against ``RECORD.json`` with hashes. Raises :class:`ExtractError`."""
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            try:
                manifest = parse_manifest(_read_member(zf, "pack.json"))
            except ManifestError as exc:
                raise ExtractError(str(exc)) from None
            members = [
                (i.filename, i.file_size, i.compress_size, i.is_dir(), i.external_attr)
                for i in infos
            ]
            report = validate_members(members, manifest)
            if not report.ok:
                raise ExtractError("; ".join(report.problems[:3]))
            try:
                record = parse_record(_read_member(zf, "RECORD.json"))
            except ManifestError as exc:
                raise ExtractError(str(exc)) from None
            payload = {
                i.filename for i in infos
                if not i.is_dir() and i.filename not in {"pack.json", "RECORD.json"}
            }
            if {f.path for f in record.files} != payload:
                raise ExtractError("RECORD.json does not list exactly the files in the archive")
            staging.mkdir(parents=True, exist_ok=False)
            for info in infos:
                dest = staging / Path(*info.filename.rstrip("/").split("/"))
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with zf.open(info) as src, dest.open("xb") as out:
                    while True:
                        chunk = src.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:
                            raise ExtractError(f"{info.filename} is larger than declared")
                        out.write(chunk)
                if written != info.file_size:
                    raise ExtractError(f"{info.filename} is shorter than declared")
    except ExtractError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        raise ExtractError(f"the archive could not be unpacked ({exc})") from exc
    problems = check_tree(record, tree_stat(staging), hash_fn=tree_hash(staging))
    if problems:
        raise ExtractError("the unpacked add-on does not match its RECORD.json: "
                           + "; ".join(problems[:3]))
    return manifest


# ---- the default probe -------------------------------------------------------------

def subprocess_probe(
    runtime: PackRuntime,
    *,
    timeout: float = PROBE_TIMEOUT_S,
    run: Callable[..., Any] = subprocess.run,
) -> Probe:
    """A probe that runs ``yazses packs probe`` in a child of this app, with packs
    switched off in the child (``YAZSES_NO_PACKS=1``) so only the staged tree is on its
    path — otherwise a reinstall would test the old copy."""
    from yazses.packs.probe import describe_exit

    def probe(name: str, staged: Path) -> tuple[bool, str]:
        argv = runtime.probe_command(name, staged)
        if not argv:
            return False, "this app cannot start its own add-on test"
        env = dict(os.environ, YAZSES_NO_PACKS="1", PYTHONIOENCODING="utf-8")
        try:
            proc = run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return False, f"the add-on test did not finish within {timeout:.0f} s"
        except OSError as exc:
            return False, f"the add-on test could not be started ({exc})"
        if proc.returncode == 0:
            return True, ""
        kind, message = describe_exit(proc.returncode, proc.stdout or "")
        return False, f"{message} [{kind}]"

    return probe


# ---- helpers -------------------------------------------------------------------------

def _rmtree(path: Path | None) -> None:
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _free_bytes(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def _acquire_lock(path: Path, now: Callable[[], float]) -> bool:
    """``O_CREAT | O_EXCL`` single flight, ADR-027's ``acquire_update_lock`` pattern with
    a per-pack name. A lock older than :data:`LOCK_STALE_S` is taken over."""
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = now() - path.stat().st_mtime
            except OSError:
                continue
            if age < LOCK_STALE_S:
                return False
            _unlink(path)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {now():.0f}\n")
        return True
    return False


def _clean_downloads(layout: PackLayout, entry: IndexEntry) -> None:
    for suffix in ("", ".part"):
        _unlink(layout.downloads / (entry.asset + suffix))


def _pretty(name: str) -> str:
    return name.replace("-", " ").title()


# ---- the transaction -----------------------------------------------------------------

def install_pack(
    index: PackIndex,
    entry: IndexEntry,
    base: BaseIdentity,
    layout: PackLayout,
    *,
    doc: dict[str, Any],
    probe: Probe,
    fetch: Fetch | None = None,
    extract: Extract = extract_archive,
    replace: Callable[[Path, Path], None] = os.replace,
    clock: Callable[[], float] = time.time,
    free_bytes: Callable[[Path], int | None] = _free_bytes,
    token: Callable[[], str] = lambda: secrets.token_hex(4),
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
    write_doc: Callable[[dict[str, Any]], None] | None = None,
    manual_steps: list[str] | None = None,
) -> InstallResult:
    """Install ``entry`` for this ``base``. Never raises; see the module docstring.

    A failure is also recorded in ``state.json``'s ``last_results`` (best-effort), so a
    surface can show why the last attempt did not finish.
    """
    result = _attempt(
        index, entry, base, layout, doc=doc, probe=probe, fetch=fetch, extract=extract,
        replace=replace, clock=clock, free_bytes=free_bytes, token=token,
        progress=progress, cancel=cancel, write_doc=write_doc, manual_steps=manual_steps,
    )
    if not result.ok and write_doc is not None:
        try:
            write_doc(record_result(doc, entry.name, ok=False, step=result.step,
                                    message=result.message, at=clock()))
        except Exception:  # noqa: BLE001 - state.json is a record, not an authority
            pass
    return result


def _attempt(
    index: PackIndex,
    entry: IndexEntry,
    base: BaseIdentity,
    layout: PackLayout,
    *,
    doc: dict[str, Any],
    probe: Probe,
    fetch: Fetch | None = None,
    extract: Extract = extract_archive,
    replace: Callable[[Path, Path], None] = os.replace,
    clock: Callable[[], float] = time.time,
    free_bytes: Callable[[Path], int | None] = _free_bytes,
    token: Callable[[], str] = lambda: secrets.token_hex(4),
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
    write_doc: Callable[[dict[str, Any]], None] | None = None,
    manual_steps: list[str] | None = None,
) -> InstallResult:
    pretty = _pretty(entry.name)
    steps = list(manual_steps or [])
    step = "check"
    lock = layout.lock(entry.name)
    locked = False
    staging: Path | None = None
    aside: Path | None = None
    target: Path | None = None
    placed = False

    def say(message: str, fraction: float | None = None) -> None:
        if progress is not None:
            progress(message, fraction)

    def fail(message: str, *, title: str = "Add-on not installed") -> InstallResult:
        return InstallResult(False, title, message, steps, step=step)

    def cancelled() -> bool:
        return cancel is not None and cancel()

    def save(new_doc: dict[str, Any]) -> None:
        if write_doc is not None:
            try:
                write_doc(new_doc)
            except Exception:  # noqa: BLE001 - state.json is a record, not an authority
                pass

    result: InstallResult
    try:
        problem = size_problem(entry)
        if problem:
            return fail(problem[0].upper() + problem[1:] + ".")
        component = build_dir_name(base.build_id, claimed_dirs(doc))
        target = layout.pack_dir(component, entry.name)

        step = "lock"
        layout.root.mkdir(parents=True, exist_ok=True)
        if not _acquire_lock(lock, clock):
            return fail(f"Another install of the {pretty} add-on is already running. "
                        "Wait for it to finish, then try again.")
        locked = True

        step = "disk"
        problem = disk_problem(entry, free_bytes(layout.root))
        if problem:
            return fail(problem[0].upper() + problem[1:] + ". Nothing was changed.")

        step = "download"
        if cancelled():
            raise KeyboardInterrupt
        from yazses.packs.fetch import PackCancelled, PackFetchError, fetch_pack

        fetcher = fetch if fetch is not None else fetch_pack
        try:
            archive = fetcher(index, entry, layout.downloads, progress=progress, cancel=cancel)
        except PackCancelled:
            raise KeyboardInterrupt from None
        except PackFetchError as exc:
            return fail(str(exc))

        step = "extract"
        say("Checking…")
        if cancelled():
            raise KeyboardInterrupt
        staging = layout.staging_dir(entry.name, token())
        _rmtree(staging)
        try:
            manifest = extract(archive, staging)
        except ExtractError as exc:
            return fail(f"The {pretty} add-on was refused: {exc}. It was deleted and "
                        "nothing was installed.")

        step = "match"
        say("Installing…")
        verdict = match(manifest, base, entry, archive_sha256=entry.sha256)
        if manifest.name != entry.name or not verdict.ok:
            why = "; ".join(verdict.reasons) or f"it is the {manifest.name!r} pack"
            return fail(f"The {pretty} add-on does not belong to this copy of YazSes "
                        f"({why}). Nothing was installed.")

        step = "probe"
        say("Testing the add-on…")
        if cancelled():
            raise KeyboardInterrupt
        ok, detail = probe(entry.name, staging)
        if not ok:
            return fail(f"The {pretty} add-on downloaded and verified, but could not be "
                        f"loaded by this copy of YazSes: {detail}. Nothing was installed. "
                        "Please report this: https://github.com/MSKazemi/yazses/issues")

        step = "place"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            aside = layout.staging_dir(entry.name, token() + ".old")
            replace(target, aside)
        replace(staging, target)
        staging = None
        placed = True
        tmp = target / (COMPLETE + ".tmp")
        tmp.write_text(f"sha256 {entry.sha256}\n", encoding="utf-8")
        replace(tmp, target / COMPLETE)

        step = "record"
        now = clock()
        new_doc = record_install(doc, component=component, build_id=base.build_id,
                                 app_version=base.app_version, entry=entry, at=now)
        new_doc = record_result(new_doc, entry.name, ok=True, step="done",
                                message="installed", at=now)
        _gc(layout, new_doc, component, base.build_id)
        save(_gc_doc(new_doc, layout, component, base.build_id))
        _rmtree(aside)
        aside = None
        for old in _quarantined(layout, entry.name):
            _rmtree(old)
        say("Done.")
        result = InstallResult(True, f"{pretty} add-on installed", (
            f"The {pretty} add-on is installed ({entry.unpacked_bytes / 1e6:.1f} MB in "
            f"{target})."
        ), step="done")
    except KeyboardInterrupt:
        result = fail("Cancelled. Nothing was downloaded or changed.",
                      title="Add-on install cancelled")
        result.step = "cancelled"
    except Exception as exc:  # noqa: BLE001 - never a traceback in the UI
        result = fail(f"The {pretty} add-on was not installed: unexpected error at the "
                      f"{step} step ({exc.__class__.__name__}: {exc}). Nothing was changed.")
    finally:
        _rmtree(staging)
        _clean_downloads(layout, entry)
        if not placed and aside is not None and target is not None:
            try:
                replace(aside, target)  # put the previous tree back
            except OSError:
                pass
        if locked:
            _unlink(lock)
    return result


def builds_on_disk(layout: PackLayout, doc: dict[str, Any]) -> dict[str, float]:
    """Build directory -> when its newest pack was installed, from ``state.json``."""
    out: dict[str, float] = {}
    for comp, rec in doc.get("builds", {}).items():
        times = [p.get("installed_at", 0.0) for p in rec.get("packs", {}).values()
                 if isinstance(p, dict)]
        out[comp] = max((float(t) for t in times if isinstance(t, (int, float))), default=0.0)
    return out


def _gc(layout: PackLayout, doc: dict[str, Any], component: str, build_id: str) -> None:
    plan = gc_plan(builds_on_disk(layout, doc), component, started_ok=started_ok(doc, build_id))
    for comp in plan.delete:
        _rmtree(layout.build_dir(comp))


def _gc_doc(doc: dict[str, Any], layout: PackLayout, component: str, build_id: str
            ) -> dict[str, Any]:
    plan = gc_plan(builds_on_disk(layout, doc), component, started_ok=started_ok(doc, build_id))
    for comp in plan.delete:
        doc = remove_build(doc, comp)
    return doc


_STAMP = re.compile(r"^\d{8}T\d{6}Z(-\d+)?$")


def _quarantined(layout: PackLayout, name: str) -> list[Path]:
    """This pack's quarantine folders (``<name>-<UTC stamp>``), and no other pack's."""
    prefix = f"{name}-"
    try:
        return [
            p for p in layout.quarantine.iterdir()
            if p.name.startswith(prefix) and _STAMP.match(p.name[len(prefix):])
        ]
    except OSError:
        return []


def quarantine_tree(
    layout: PackLayout,
    tree: Path,
    reason: str,
    *,
    clock: Callable[[], float] = time.time,
    replace: Callable[[Path, Path], None] = os.replace,
) -> Path | None:
    """Move a tree that failed a check to ``quarantine/<name>-<UTC>/`` beside a
    ``reason.txt`` (ADR-028 §2). Kept for diagnosis until the next successful install of
    that pack or ``yazses packs clean``. Returns the new location, or ``None`` if the
    move failed (the tree is then left where it is, and still does not mount if its
    check keeps failing)."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
    layout.quarantine.mkdir(parents=True, exist_ok=True)
    dest = layout.quarantine_dir(tree.name, stamp)
    n = 1
    while dest.exists():
        n += 1
        dest = layout.quarantine_dir(tree.name, f"{stamp}-{n}")
    try:
        replace(tree, dest)
        (dest / "reason.txt").write_text(reason + "\n", encoding="utf-8")
    except OSError:
        return None
    return dest
