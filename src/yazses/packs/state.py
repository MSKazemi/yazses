"""Per-feature pack state and the ``state.json`` schema (pure; ADR-028 §5).

Every surface — CLI, tray, Settings, doctor — takes a pack-backed feature's state from
:func:`feature_status`, so they cannot disagree. The rule it exists to keep:

    A feature whose config says on but whose pack is missing, stale or damaged reads
    **waiting for add-on**, never ``on``.

That is the ``Feature.inert`` lesson applied to packs: a config key nothing can honour
must not be reported as working.

``state.json`` (``format: 1``)::

    {"format": 1,
     "builds": {"b-<12hex>": {"build_id": "sha256:…", "app_version": "2.44.0",
                              "packs": {"parakeet": {"sha256": "…", "installed_at": 0.0,
                                                     "features": ["stt-parakeet"],
                                                     "size": 312345}}}},
     "started_ok": ["sha256:…"],
     "last_results": {"parakeet": {"ok": false, "step": "download",
                                   "message": "…", "at": 0.0}}}

It is a record, not an authority: whether a pack *loads* is decided from the tree and the
embedded index alone. A corrupt or missing file reads as empty and is never an error.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yazses.packs.manifest import IndexEntry, PackIndex
from yazses.packs.policy import Capability, human_bytes

__all__ = [
    "DAMAGED",
    "NOT_INSTALLED",
    "OK",
    "STALE",
    "UNAVAILABLE",
    "PackStatus",
    "TreeFact",
    "claimed_dirs",
    "dump_state",
    "empty_state",
    "feature_status",
    "installed_elsewhere",
    "mark_started_ok",
    "parse_state",
    "record_install",
    "record_result",
    "remove_build",
    "remove_pack",
    "started_ok",
]

OK = "ok"
NOT_INSTALLED = "not-installed"
STALE = "needs-download"
DAMAGED = "damaged"
UNAVAILABLE = "unavailable"

_FORMAT = 1


# ---- state.json --------------------------------------------------------------

def empty_state() -> dict[str, Any]:
    return {"format": _FORMAT, "builds": {}, "started_ok": [], "last_results": {}}


def parse_state(text: str | None) -> dict[str, Any]:
    """Read ``state.json`` leniently. Anything unreadable becomes :func:`empty_state`."""
    try:
        data = json.loads(text or "")
    except (ValueError, RecursionError):
        return empty_state()
    if not isinstance(data, dict) or data.get("format") != _FORMAT:
        return empty_state()
    out = empty_state()
    builds = data.get("builds")
    if isinstance(builds, dict):
        for comp, rec in builds.items():
            if not (isinstance(comp, str) and isinstance(rec, dict)):
                continue
            raw_packs = rec.get("packs")
            packs: dict[Any, Any] = raw_packs if isinstance(raw_packs, dict) else {}
            out["builds"][comp] = {
                "build_id": str(rec.get("build_id", "")),
                "app_version": str(rec.get("app_version", "")),
                "packs": {
                    str(n): dict(p) for n, p in packs.items() if isinstance(p, dict)
                },
            }
    ok = data.get("started_ok")
    if isinstance(ok, list):
        out["started_ok"] = [s for s in ok if isinstance(s, str)]
    results = data.get("last_results")
    if isinstance(results, dict):
        out["last_results"] = {
            str(n): dict(r) for n, r in results.items() if isinstance(r, dict)
        }
    return out


def dump_state(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def claimed_dirs(doc: Mapping[str, Any]) -> dict[str, str]:
    """Build directory -> the build id ``state.json`` says owns it (for the collision
    guard in :func:`yazses.packs.layout.build_dir_name`)."""
    return {c: r["build_id"] for c, r in doc.get("builds", {}).items() if r.get("build_id")}


def record_install(
    doc: Mapping[str, Any],
    *,
    component: str,
    build_id: str,
    app_version: str,
    entry: IndexEntry,
    at: float,
) -> dict[str, Any]:
    new = copy.deepcopy(dict(doc))
    build = new.setdefault("builds", {}).setdefault(
        component, {"build_id": build_id, "app_version": app_version, "packs": {}}
    )
    build["build_id"] = build_id
    build["app_version"] = app_version
    build.setdefault("packs", {})[entry.name] = {
        "sha256": entry.sha256,
        "installed_at": at,
        "features": list(entry.features),
        "size": entry.size,
    }
    return new


def record_result(
    doc: Mapping[str, Any], name: str, *, ok: bool, step: str, message: str, at: float
) -> dict[str, Any]:
    new = copy.deepcopy(dict(doc))
    new.setdefault("last_results", {})[name] = {
        "ok": ok, "step": step, "message": message, "at": at,
    }
    return new


def remove_pack(doc: Mapping[str, Any], component: str, name: str) -> dict[str, Any]:
    new = copy.deepcopy(dict(doc))
    build = new.get("builds", {}).get(component)
    if build is not None:
        build.get("packs", {}).pop(name, None)
        if not build.get("packs"):
            new["builds"].pop(component, None)
    return new


def remove_build(doc: Mapping[str, Any], component: str) -> dict[str, Any]:
    new = copy.deepcopy(dict(doc))
    new.get("builds", {}).pop(component, None)
    return new


def mark_started_ok(doc: Mapping[str, Any], build_id: str) -> dict[str, Any]:
    """Record that ``build_id`` completed one good start (ADR-028 §6, *Rollback*).
    Only the newest few are kept; the list exists to answer one question."""
    new = copy.deepcopy(dict(doc))
    ids = [b for b in new.get("started_ok", []) if b != build_id]
    new["started_ok"] = [*ids, build_id][-4:]
    return new


def started_ok(doc: Mapping[str, Any], build_id: str) -> bool:
    return build_id in doc.get("started_ok", [])


def installed_elsewhere(doc: Mapping[str, Any], name: str, build_id: str) -> str | None:
    """The app version a pack called ``name`` was last installed for, under a build other
    than ``build_id`` — i.e. why it now needs downloading again. ``None`` if never."""
    best: tuple[float, str] | None = None
    for rec in doc.get("builds", {}).values():
        if rec.get("build_id") == build_id:
            continue
        pack = rec.get("packs", {}).get(name)
        if not isinstance(pack, dict):
            continue
        at = pack.get("installed_at")
        when = float(at) if isinstance(at, (int, float)) else 0.0
        if best is None or when > best[0]:
            best = (when, str(rec.get("app_version") or "an earlier version"))
    return best[1] if best else None


# ---- per-feature status -------------------------------------------------------

@dataclass(frozen=True)
class TreeFact:
    """What is on disk for one pack under *this* build: ``ok``, ``damaged`` or
    ``absent``, and for ``damaged`` the reason."""

    state: str
    reason: str = ""


@dataclass(frozen=True)
class PackStatus:
    feature: str
    pack: str | None
    state: str
    config_on: bool
    #: True only when the config says on **and** the pack is installed for this build.
    reads_on: bool
    #: The short word(s) a list shows: "on", "off", "waiting for add-on", …
    label: str
    #: The sentence a surface shows, naming the next step.
    message: str
    download_bytes: int = 0
    unpacked_bytes: int = 0


def _pretty(name: str) -> str:
    return name.replace("-", " ").title()


def feature_status(
    slug: str,
    *,
    config_on: bool,
    capability: Capability,
    index: PackIndex | None,
    index_error: str | None,
    trees: Mapping[str, TreeFact],
    doc: Mapping[str, Any],
) -> PackStatus:
    """The one state a pack-backed feature is in, for every surface."""
    def status(state: str, pack: str | None, label: str, message: str,
               entry: IndexEntry | None = None) -> PackStatus:
        return PackStatus(
            feature=slug, pack=pack, state=state, config_on=config_on,
            reads_on=config_on and state == OK, label=label, message=message,
            download_bytes=entry.size if entry else 0,
            unpacked_bytes=entry.unpacked_bytes if entry else 0,
        )

    waiting = "waiting for add-on" if config_on else "off"
    if not capability.ok:
        return status(UNAVAILABLE, None, waiting, capability.reason + ".")
    if index is None:
        return status(UNAVAILABLE, None, waiting, (
            f"This copy of YazSes cannot read its add-on list ({index_error or 'missing'}). "
            "Reinstall YazSes from the releases page."
        ))
    entry = index.for_feature(slug)
    if entry is None:
        return status(UNAVAILABLE, None, waiting, (
            f"No add-on is published for {slug} in this build of YazSes."
        ))
    pretty = _pretty(entry.name)
    price = (
        f"{human_bytes(entry.size)} download, {human_bytes(entry.unpacked_bytes)} on disk"
    )
    tree = trees.get(entry.name, TreeFact("absent"))
    if tree.state == "ok":
        return status(OK, entry.name, "on" if config_on else "off",
                      f"The {pretty} add-on is installed.", entry)
    if tree.state == "damaged":
        label = "damaged — reinstall"
        return status(DAMAGED, entry.name, label, (
            f"The {pretty} add-on is damaged ({tree.reason or 'a file is missing'} — "
            "security software may have removed it). It was set aside. Reinstall it: "
            f"yazses packs install {entry.name}"
        ), entry)
    before = installed_elsewhere(doc, entry.name, index.base_build_id)
    if before is not None:
        return status(STALE, entry.name, waiting, (
            f"YazSes was updated. The {pretty} add-on was built for {before} and is not "
            f"loaded. Download it again ({human_bytes(entry.size)}): "
            f"yazses packs install {entry.name}"
        ), entry)
    return status(NOT_INSTALLED, entry.name, waiting, (
        f"Needs the {pretty} add-on — {price}."
    ), entry)
