"""Download the add-ons again on the first start after an update (ADR-028 Q3).

Packs are pinned to the exact base build, so after an update the add-ons the user had
are not loaded until this version's own copies are installed. The owner's answer to
ADR-028's third question splits that into two halves:

1. **Consent, in the old version.** The update question names the installed add-ons and
   their sizes, read from the index built into the *running* app
   (:func:`addons_for_update`, worded by ``installer_update.addons_note``). When the user
   answers yes and the hand-off has started, :func:`record_consent` writes a small
   ``packs/update-consent.json``: the old build id, the two versions and the pack names.
2. **The fetch, in the new version.** On its first start the tray calls
   :func:`run_refetch` off its UI thread. The consent file is **erased before anything
   else happens** -- it is used at most once, so a crash, a hang or a failure can never
   turn into a download on every start. Each consented pack that ``state.json`` records
   for the old build and that this version's **own** embedded index lists goes through
   the ordinary verified install (``packs.manage.install``: the same fetch, checksum,
   extract, ``RECORD.json`` check and import probe as a click on *Install now*) -- no
   second downloader and no new egress row. Each installed tree is then checked again
   in full (``packs.manage.verify``).

Only when **every** pack verified is this build marked ``started_ok`` and the previous
build's trees garbage-collected (``policy.gc_plan``). On a partial or failed run nothing
of the old build is touched: it stays for ADR-027's rollback, the features read
*waiting for add-on*, and the existing *Install now* in Settings and the tray is the
one-click retry. No consent (the CLI's ``yazses update`` does not ask, a declined
question, a failed update that relaunched the old build) means nothing is downloaded.

A start with nothing to download is this build's first good start
(:func:`mark_first_start`): it writes ``started_ok`` and retires the other builds, once
per build. That is the marker ADR-028 §6 says the tray writes; nothing wrote it before.

The decisions (:func:`parse_consent`, :func:`plan_refetch`, :func:`describe`) are pure;
the I/O around them takes injected ``install``, ``verify`` and ``retire`` callables, so
the state machine is tested with fakes and no network.

**This module cannot download by itself.** It imports nothing of ``packs.fetch``,
``packs.install`` or ``packs.manage``: ``install`` and ``verify`` have no default and are
handed in by the tray's entry point (``tray.app.run``), which the daemon never imports.
``tray.updates`` sits in the daemon's static import closure (through the platform
factory), so binding the downloader anywhere it can reach would put the download one
import away from the daemon (``tests/test_egress_inventory.py``).
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.packs.layout import PackLayout
from yazses.packs.manifest import IndexEntry, PackIndex
from yazses.packs.state import TreeFact

if TYPE_CHECKING:
    from yazses.packs.context import PackContext

__all__ = [
    "CONSENT_FILE",
    "CONSENT_MAX_AGE_S",
    "Consent",
    "Outcome",
    "Plan",
    "addons_for_update",
    "consent_path",
    "consent_pending",
    "describe",
    "dump_consent",
    "erase_consent",
    "installed_addons",
    "mark_first_start",
    "parse_consent",
    "plan_refetch",
    "read_consent",
    "record_consent",
    "retire_old_builds",
    "run_refetch",
    "write_consent",
]

log = logging.getLogger(__name__)

#: Beside ``state.json`` in the pack root, so the per-user uninstaller removes it too.
CONSENT_FILE = "update-consent.json"
#: A consent older than this is not acted on: it answered a question about *that* update.
CONSENT_MAX_AGE_S = 7 * 86400.0
#: Clock skew tolerated for a consent stamped in the future.
_FUTURE_SKEW_S = 86400.0
_FORMAT = 1
_MAX_BYTES = 64 * 1024

#: Outcome states.
DORMANT = "dormant"
DONE = "done"
PARTIAL = "partial"
FAILED = "failed"


def _pretty(name: str) -> str:
    return name.replace("-", " ").title()


# ---- the consent record (pure) ----------------------------------------------------

@dataclass(frozen=True)
class Consent:
    """The user said yes to an update whose question named these add-ons."""

    build_id: str
    from_version: str
    to_version: str
    packs: tuple[str, ...]
    at: float


def dump_consent(consent: Consent) -> str:
    return json.dumps({
        "format": _FORMAT,
        "build_id": consent.build_id,
        "from": consent.from_version,
        "to": consent.to_version,
        "packs": list(consent.packs),
        "at": consent.at,
    }, indent=2, sort_keys=True) + "\n"


def parse_consent(text: str | None) -> Consent | None:
    """Read a consent leniently: anything malformed is no consent (never an error)."""
    try:
        data = json.loads(text or "")
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("format") != _FORMAT:
        return None
    build_id, packs, at = data.get("build_id"), data.get("packs"), data.get("at")
    if not (isinstance(build_id, str) and build_id and isinstance(packs, list)):
        return None
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return None
    names = tuple(dict.fromkeys(p for p in packs if isinstance(p, str) and p))
    if not names:
        return None
    return Consent(build_id, str(data.get("from") or ""), str(data.get("to") or ""),
                   names, float(at))


def installed_addons(
    index: PackIndex | None, trees: Mapping[str, TreeFact]
) -> tuple[tuple[str, int], ...]:
    """``(pack name, download bytes)`` for every pack installed and intact for this
    build, in index order -- what the update question names (pure)."""
    if index is None:
        return ()
    return tuple(
        (e.name, e.size) for e in index.packs
        if trees.get(e.name, TreeFact("absent")).state == "ok"
    )


# ---- the decision (pure) ------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    """What the first start after an update does. ``fetch`` empty means nothing."""

    fetch: tuple[str, ...] = ()
    #: Consented, but this version publishes no add-on of that name (it may be bundled).
    not_offered: tuple[str, ...] = ()
    #: Consented and already installed for this build.
    present: tuple[str, ...] = ()
    reason: str = ""


def _recorded_for(doc: Mapping[str, Any], build_id: str) -> set[str]:
    out: set[str] = set()
    for rec in doc.get("builds", {}).values():
        if isinstance(rec, dict) and rec.get("build_id") == build_id:
            packs = rec.get("packs")
            if isinstance(packs, dict):
                out.update(str(n) for n in packs)
    return out


def plan_refetch(
    consent: Consent | None,
    *,
    now: float,
    capable: bool,
    index: PackIndex | None,
    trees: Mapping[str, TreeFact],
    doc: Mapping[str, Any],
) -> Plan:
    """Which packs to download again, or why none (pure).

    Nothing without consent; nothing for a stale consent; nothing when this process may
    not install packs; nothing when the build did not change (a failed update relaunched
    the old version, whose packs are still in place); and only packs ``state.json``
    records for the old build -- what the user actually had -- that this version's own
    index lists and that are not already installed.
    """
    if consent is None:
        return Plan(reason="no consent")
    if now - consent.at > CONSENT_MAX_AGE_S or consent.at - now > _FUTURE_SKEW_S:
        return Plan(reason="the consent is stale")
    if not capable or index is None:
        return Plan(reason="this process cannot install add-ons")
    if index.base_build_id == consent.build_id:
        return Plan(reason="the build did not change")
    had = _recorded_for(doc, consent.build_id)
    offered = {e.name for e in index.packs}
    fetch: list[str] = []
    not_offered: list[str] = []
    present: list[str] = []
    for name in consent.packs:
        if name not in had:
            continue
        if name not in offered:
            not_offered.append(name)
        elif trees.get(name, TreeFact("absent")).state == "ok":
            present.append(name)
        else:
            fetch.append(name)
    reason = "" if fetch else "nothing to download"
    return Plan(tuple(fetch), tuple(not_offered), tuple(present), reason)


@dataclass(frozen=True)
class Outcome:
    state: str
    version: str = ""
    installed: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    retired: tuple[str, ...] = ()
    reason: str = ""
    plan: Plan = field(default_factory=Plan)


def _names(names: Sequence[str]) -> str:
    pretty = [_pretty(n) for n in names]
    if len(pretty) <= 1:
        return "".join(pretty)
    return ", ".join(pretty[:-1]) + " and " + pretty[-1]


def describe(outcome: Outcome) -> tuple[str, str] | None:
    """``(title, body)`` to show once, or ``None`` when nothing happened (pure).

    Kept short: the tray shows it in a balloon, which Windows drops whole over 255
    characters. The failure reason itself is in ``state.json`` and the log.
    """
    version = f"YazSes {outcome.version}" if outcome.version else "this version"
    if outcome.state == DONE:
        one = len(outcome.installed) == 1
        return ("Add-ons ready", (
            f"{_names(outcome.installed)} {'is' if one else 'are'} downloaded again for "
            f"{version}. Restart YazSes to switch {'it' if one else 'them'} on."
        ))
    failed = _names([n for n, _ in outcome.failed])
    waits = "it waits" if len(outcome.failed) == 1 else "they wait"
    retry = "Open Settings and click Install now to try again."
    if outcome.state == PARTIAL:
        return ("Some add-ons not downloaded", (
            f"{_names(outcome.installed)} downloaded again for {version}; {failed} "
            f"could not be. {retry}"
        ))
    if outcome.state == FAILED:
        return ("Add-ons not downloaded", (
            f"{failed} could not be downloaded again for {version}, so {waits}. {retry}"
        ))
    return None


# ---- I/O ------------------------------------------------------------------------------

def consent_path(layout: PackLayout) -> Path:
    return layout.root / CONSENT_FILE


def consent_pending(layout: PackLayout) -> bool:
    """Cheap check the tray makes before loading anything else. Never raises."""
    try:
        return consent_path(layout).is_file()
    except OSError:
        return False


def read_consent(layout: PackLayout) -> Consent | None:
    try:
        with consent_path(layout).open("rb") as fh:
            data = fh.read(_MAX_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_BYTES:
        return None
    return parse_consent(data.decode("utf-8", errors="replace"))


def write_consent(layout: PackLayout, consent: Consent) -> None:
    """Atomic replace. Raises ``OSError``."""
    layout.root.mkdir(parents=True, exist_ok=True)
    path = consent_path(layout)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(dump_consent(consent), encoding="utf-8")
    os.replace(tmp, path)


def erase_consent(layout: PackLayout) -> bool:
    """Delete the consent. ``True`` when it is gone (or was never there)."""
    try:
        consent_path(layout).unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def addons_for_update(ctx: PackContext) -> tuple[tuple[str, int], ...]:
    """The installed add-ons the update question names, from this (old) build's own
    embedded index. Empty when this install cannot use packs. Never raises."""
    try:
        if not ctx.capability.ok or ctx.index is None:
            return ()
        from yazses.packs.context import scan_trees

        return installed_addons(ctx.index, scan_trees(ctx))
    except Exception:  # noqa: BLE001 - a missing sentence, never a failed update
        log.debug("could not list the installed add-ons", exc_info=True)
        return ()


def record_consent(
    ctx: PackContext,
    addons: Sequence[tuple[str, int]],
    *,
    from_version: str,
    to_version: str,
    now: Callable[[], float] = time.time,
) -> bool:
    """Write the consent once the update hand-off has started. Never raises.

    Nothing is written when the question named no add-on, or when this build has no
    index (no build id to tell the next start whether the build changed).
    """
    if not addons or ctx.index is None:
        return False
    try:
        write_consent(ctx.layout, Consent(
            build_id=ctx.index.base_build_id,
            from_version=str(from_version),
            to_version=str(to_version),
            packs=tuple(dict.fromkeys(name for name, _size in addons)),
            at=now(),
        ))
    except OSError:
        log.warning("could not record the add-on consent; the new version will ask",
                    exc_info=True)
        return False
    return True


def retire_old_builds(ctx: PackContext) -> list[str]:
    """Mark this build ``started_ok`` and delete every other build's trees
    (``policy.gc_plan`` with ``started_ok=True``). Call only after every new tree has
    verified: until then the previous build is ADR-027's rollback."""
    import shutil

    from yazses.packs.context import read_state, write_state
    from yazses.packs.policy import gc_plan
    from yazses.packs.state import mark_started_ok, remove_build

    if ctx.index is None:
        return []
    doc = mark_started_ok(read_state(ctx.layout), ctx.index.base_build_id)
    fresh = replace(ctx, doc=doc)
    comp = fresh.component
    if comp is None:
        return []
    removed: list[str] = []
    for other in gc_plan(_builds_on_disk(doc), comp, started_ok=True).delete:
        shutil.rmtree(ctx.layout.build_dir(other), ignore_errors=True)
        doc = remove_build(doc, other)
        removed.append(other)
    try:
        write_state(ctx.layout, doc)
    except OSError:
        log.debug("could not record the retired builds", exc_info=True)
    return removed


def mark_first_start(ctx: PackContext, *, retire: Retire | None = None) -> tuple[str, ...]:
    """A start with nothing to download: record ``started_ok`` for this build and delete
    the other builds' trees (ADR-028 §6, *Rollback*: "a started-ok marker the tray writes
    after it is up"). Without this nothing ever wrote the marker, and every previous
    build's packs stayed on disk for good.

    Does nothing when this process may not use packs, when ``state.json`` records no
    build at all (it is not created for a user who never installed an add-on), or when
    this build is already marked -- so it runs its ``retire`` at most once per build.
    """
    from yazses.packs.context import read_state
    from yazses.packs.state import started_ok

    if not (ctx.capability.ok and ctx.index is not None and ctx.base is not None
            and not ctx.base_problems):
        return ()
    doc = read_state(ctx.layout)
    if not doc.get("builds") or started_ok(doc, ctx.index.base_build_id):
        return ()
    return tuple((retire or retire_old_builds)(ctx))


def _builds_on_disk(doc: Mapping[str, Any]) -> dict[str, float]:
    """Build directory -> when its newest pack was installed (``install.builds_on_disk``,
    restated: importing ``packs.install`` here would put it in the daemon's closure)."""
    out: dict[str, float] = {}
    for comp, rec in doc.get("builds", {}).items():
        packs = rec.get("packs", {}) if isinstance(rec, dict) else {}
        times = [p.get("installed_at", 0.0) for p in packs.values() if isinstance(p, dict)]
        out[comp] = max((float(t) for t in times if isinstance(t, (int, float))), default=0.0)
    return out


#: ``packs.manage.install``: the verified transaction (fetch, checksum, extract, probe).
#: Returns an ``install.InstallResult`` (``.ok``, ``.message``) -- typed ``Any`` because
#: even a type-only import of ``packs.install`` counts in the closure test.
Install = Callable[["PackContext", IndexEntry], Any]
#: ``packs.manage.verify(ctx, name, set_aside=True)``: ``(pack, problem)`` pairs.
Verify = Callable[["PackContext", str], "list[tuple[str, str]]"]
Retire = Callable[["PackContext"], "list[str]"]


def run_refetch(
    ctx: PackContext,
    *,
    install: Install,
    verify: Verify,
    now: Callable[[], float] = time.time,
    retire: Retire | None = None,
) -> Outcome:
    """Act on a pending consent, once. Blocking (downloads): call it off the UI thread.

    Never raises. The consent is erased **before** anything is downloaded; if it cannot
    be erased nothing is downloaded either, so no start can repeat the work.

    The tray calls it on every start of a frozen build that has a ``state.json``. A start
    with nothing to download is this build's first good start (:func:`mark_first_start`).
    A start that downloaded retires the old build only when every pack verified; a
    partial or failed one leaves it, and the next start, having nothing left to
    download, retires it then.
    """
    from yazses.packs.context import read_state, scan_trees

    version = ctx.index.app_version if ctx.index is not None else ""
    try:
        consent = read_consent(ctx.layout)
        if consent is None:
            if consent_pending(ctx.layout):
                erase_consent(ctx.layout)  # unreadable: drop it, never retry it
            retired = mark_first_start(ctx, retire=retire)
            return Outcome(DORMANT, version, retired=retired, reason="no consent")
        if not erase_consent(ctx.layout):
            log.warning("could not erase the add-on consent; not downloading")
            return Outcome(DORMANT, version, reason="the consent could not be erased")
        capable = (ctx.capability.ok and ctx.base is not None and not ctx.base_problems)
        trees = scan_trees(ctx) if capable else {}
        plan = plan_refetch(consent, now=now(), capable=capable, index=ctx.index,
                            trees=trees, doc=read_state(ctx.layout))
        if not plan.fetch:
            log.info("add-on re-download after the update: %s", plan.reason)
            retired = mark_first_start(ctx, retire=retire)
            return Outcome(DORMANT, version, retired=retired, reason=plan.reason, plan=plan)
        assert ctx.index is not None
        installed: list[str] = []
        failed: list[tuple[str, str]] = []
        for name in plan.fetch:
            entry = next(e for e in ctx.index.packs if e.name == name)
            # A fresh state document each time: an install records itself by rewriting
            # state.json from the document it was given, so a stale one would drop the
            # pack installed just before it.
            fresh = replace(ctx, doc=read_state(ctx.layout))
            try:
                result = install(fresh, entry)
            except Exception as exc:  # noqa: BLE001 - the transaction never raises; belt
                failed.append((name, f"unexpected error ({exc})"))
                continue
            if not result.ok:
                log.warning("add-on %s was not downloaded again: %s", name, result.message)
                failed.append((name, result.message))
                continue
            problems = verify(replace(ctx, doc=read_state(ctx.layout)), name)
            if problems:
                why = "; ".join(p for _n, p in problems)
                log.warning("add-on %s failed its check after install: %s", name, why)
                failed.append((name, why))
                continue
            installed.append(name)
        if failed:
            state = PARTIAL if installed else FAILED
            return Outcome(state, version, tuple(installed), tuple(failed), plan=plan)
        retired = tuple((retire or retire_old_builds)(ctx))
        return Outcome(DONE, version, tuple(installed), retired=retired, plan=plan)
    except Exception as exc:  # noqa: BLE001 - a startup job never raises into the tray
        log.warning("add-on re-download after the update failed", exc_info=True)
        return Outcome(DORMANT, version, reason=str(exc))
