"""Which feature is served by which pack, and the per-extra decisions (pure).

Two sources, kept apart on purpose:

* **At runtime** the answer comes from the embedded index alone
  (:meth:`~yazses.packs.manifest.PackIndex.for_feature`): a frozen app has no
  ``pyproject.toml`` and must not guess.
* **At build and test time** the answer is *derived*: ``system/features.py::_FEATURE_DEPS``
  says which distributions a capability needs, ``pyproject.toml``'s extras say which
  extra declares them, and ``packaging/packs/packs.toml`` records a decision per extra
  (ADR-028 §7). :func:`catalogue_problems` holds the three to each other so that a new
  extra cannot silently be missing a decision.

``packs.toml`` schema the runtime side reads (the build side owns the file)::

    [extras.parakeet]
    decision = "pack"              # pack | bundled | no-windows-wheel | unwired | deferred
    entry_modules = ["onnx_asr"]   # required for "pack"
    approved_large = false         # true needs approved_by (ADR-028 §7 (e))
    approved_by = ""
    shared_with = []
    reason = ""                    # required for anything but "pack"
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DECISIONS",
    "Decision",
    "catalogue_problems",
    "distribution",
    "extra_for_packages",
    "parse_decisions",
]

DECISIONS = frozenset({"pack", "bundled", "no-windows-wheel", "unwired", "deferred"})


@dataclass(frozen=True)
class Decision:
    extra: str
    kind: str
    entry_modules: tuple[str, ...] = ()
    approved_large: bool = False
    approved_by: str = ""
    shared_with: tuple[str, ...] = ()
    reason: str = ""


def distribution(requirement: str) -> str:
    """``onnx-asr[cpu,hub]>=0.12`` -> ``onnx-asr`` (PEP 503-normalised)."""
    name = re.split(r"[<>=!~\[;\s]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_decisions(data: Mapping[str, Any]) -> dict[str, Decision]:
    """``packs.toml`` (already parsed by ``tomllib``) -> extra -> :class:`Decision`.
    Raises ``ValueError`` naming the first malformed row."""
    raw = data.get("extras")
    if not isinstance(raw, dict):
        raise ValueError("packs.toml has no [extras.<name>] tables")
    out: dict[str, Decision] = {}
    for extra, row in raw.items():
        if not isinstance(row, dict):
            raise ValueError(f"packs.toml: [extras.{extra}] is not a table")
        kind = row.get("decision")
        if kind not in DECISIONS:
            raise ValueError(f"packs.toml: [extras.{extra}] has decision {kind!r}")
        modules = row.get("entry_modules", [])
        if not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):
            raise ValueError(f"packs.toml: [extras.{extra}] entry_modules is not a list")
        if kind == "pack" and not modules:
            raise ValueError(f"packs.toml: [extras.{extra}] is a pack with no entry_modules")
        reason = str(row.get("reason", ""))
        if kind != "pack" and not reason.strip():
            raise ValueError(f"packs.toml: [extras.{extra}] is {kind!r} with no reason")
        large = bool(row.get("approved_large", False))
        by = str(row.get("approved_by", ""))
        if large and not by.strip():
            raise ValueError(f"packs.toml: [extras.{extra}] approved_large needs approved_by")
        shared = row.get("shared_with", [])
        out[extra] = Decision(
            extra=extra,
            kind=kind,
            entry_modules=tuple(modules),
            approved_large=large,
            approved_by=by,
            shared_with=tuple(shared) if isinstance(shared, list) else (),
            reason=reason,
        )
    return out


def extra_for_packages(
    packages: Sequence[str], extras: Mapping[str, Sequence[str]]
) -> str | None:
    """The smallest extra (never ``all``) that declares every distribution in
    ``packages``; ties broken by name. ``None`` when no extra does."""
    wanted = {distribution(p) for p in packages}
    candidates = []
    for name, reqs in extras.items():
        if name == "all":
            continue
        have = {distribution(r) for r in reqs}
        if wanted <= have:
            candidates.append((len(have), name))
    return min(candidates)[1] if candidates else None


def catalogue_problems(
    feature_deps: Mapping[str, tuple[Sequence[str], Sequence[str]]],
    unwired: Collection[str],
    extras: Mapping[str, Sequence[str]],
    decisions: Mapping[str, Decision],
) -> list[str]:
    """Every way ``_FEATURE_DEPS``, the extras and ``packs.toml`` disagree.

    An empty ``decisions`` (or ``feature_deps``) is itself a problem: a loop over
    nothing is green, and "the catalogue lost every row" must not read as "fine".
    """
    problems: list[str] = []
    if not decisions:
        problems.append("packs.toml declares no decisions, so nothing is being checked")
    if not feature_deps:
        problems.append("no feature declares dependencies, so nothing is being checked")
    wired_extras: set[str] = set()
    for slug, (_modules, packages) in sorted(feature_deps.items()):
        extra = extra_for_packages(packages, extras)
        if extra is None:
            problems.append(f"{slug}: no pyproject extra declares {list(packages)}")
            continue
        if slug in unwired:
            continue
        wired_extras.add(extra)
        if extra not in decisions:
            problems.append(f"{slug}: its extra {extra!r} has no packs.toml decision")
        elif decisions[extra].kind == "unwired":
            problems.append(f"{slug} is wired but packs.toml calls {extra!r} unwired")
    for extra, decision in sorted(decisions.items()):
        if extra not in extras:
            problems.append(f"packs.toml decides {extra!r}, which is not a pyproject extra")
        elif decision.kind == "pack" and extra not in wired_extras:
            problems.append(f"packs.toml packs {extra!r}, but no wired feature uses it")
    return problems
