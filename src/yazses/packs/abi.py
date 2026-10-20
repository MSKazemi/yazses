"""Does this pack belong to this exact base build? (pure; ADR-028 §1)

A pack is loadable **only** into the base whose ``base_build_id`` it names. Version
equality is not enough: the base freezes numpy and onnxruntime, ``uv python install 3.12``
takes whichever patch is current, and a tag has been rebuilt before (v2.32.0). So:

* **stale** — the pack names another build id. It is never loaded, never quarantined, and
  is kept for rollback (§6). After every app update every pack reads stale.
* **refused** — the build id matches but something else does not (Python, platform, arch,
  version, name, sizes, hash). Defence in depth: a matching id with a different Python
  is a broken build or a tampered tree, not a pack to load.
* **ok** — every field agrees.

Each mismatching field yields its own reason, written so a refusal can say *why*
("built for Python 3.12.8, this app runs 3.12.9") instead of showing a hash.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.packs.manifest import IndexEntry, PackIndex, PackManifest

__all__ = ["OK", "REFUSED", "STALE", "BaseIdentity", "Match", "base_identity", "match"]

OK = "ok"
STALE = "stale"
REFUSED = "refused"


@dataclass(frozen=True)
class BaseIdentity:
    """The running base: its build id from the embedded index, the rest from ``sys``."""

    build_id: str
    cache_tag: str
    python_version: str
    platform: str
    arch: str
    app_version: str


@dataclass(frozen=True)
class Match:
    status: str
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == OK


def base_identity(
    index: PackIndex,
    *,
    cache_tag: str,
    python_version: str,
    platform: str,
    arch: str,
    app_version: str,
) -> tuple[BaseIdentity, tuple[str, ...]]:
    """The running base, and every way the embedded index disagrees with the process.

    The index is written by CI for the bundle it is copied into, so a disagreement means
    the index does not belong to this app (copied between builds, or a build fault).
    The caller must then refuse every pack: the reasons say why.
    """
    base = BaseIdentity(
        build_id=index.base_build_id,
        cache_tag=cache_tag,
        python_version=python_version,
        platform=platform,
        arch=arch,
        app_version=app_version,
    )
    problems: list[str] = []
    if index.python.cache_tag != cache_tag:
        problems.append(
            f"the add-on index is for {index.python.cache_tag}, this app runs {cache_tag}"
        )
    if index.python.version != python_version:
        problems.append(
            f"the add-on index is for Python {index.python.version}, this app runs "
            f"{python_version}"
        )
    if index.platform != platform:
        problems.append(f"the add-on index is for {index.platform}, this app is {platform}")
    if index.arch != arch:
        problems.append(f"the add-on index is for {index.arch}, this app is {arch}")
    if index.app_version != app_version:
        problems.append(
            f"the add-on index is for YazSes {index.app_version}, this is {app_version}"
        )
    return base, tuple(problems)


def match(
    pack: PackManifest,
    base: BaseIdentity,
    entry: IndexEntry | None,
    *,
    archive_sha256: str | None = None,
) -> Match:
    """``ok``, ``stale`` or ``refused``, with one reason per mismatching field."""
    reasons: list[str] = []
    if pack.python.cache_tag != base.cache_tag:
        reasons.append(f"built for {pack.python.cache_tag}, this app runs {base.cache_tag}")
    if pack.python.version != base.python_version:
        reasons.append(
            f"built for Python {pack.python.version}, this app runs {base.python_version}"
        )
    if pack.platform != base.platform:
        reasons.append(f"built for {pack.platform}, this app is {base.platform}")
    if pack.arch != base.arch:
        reasons.append(f"built for {pack.arch}, this app is {base.arch}")
    if pack.app_version != base.app_version:
        reasons.append(f"built for YazSes {pack.app_version}, this is {base.app_version}")

    if pack.base_build_id != base.build_id:
        head = (
            f"built for another build of YazSes ({pack.app_version}, "
            f"{pack.base_build_id[7:19]}), not this one ({base.app_version}, "
            f"{base.build_id[7:19]})"
        )
        return Match(STALE, (head, *reasons))

    if entry is None:
        reasons.append(f"{pack.name!r} is not listed in this build's add-on index")
    else:
        if entry.name != pack.name:
            reasons.append(f"the index entry is {entry.name!r}, the pack says {pack.name!r}")
        if set(entry.features) != set(pack.features):
            reasons.append("the pack serves different features than the index says")
        if entry.files != pack.files:
            reasons.append(f"the pack has {pack.files} files, the index says {entry.files}")
        if entry.unpacked_bytes != pack.unpacked_bytes:
            reasons.append(
                f"the pack unpacks to {pack.unpacked_bytes} bytes, the index says "
                f"{entry.unpacked_bytes}"
            )
        if archive_sha256 is not None and archive_sha256.lower() != entry.sha256:
            reasons.append(
                "the archive's SHA-256 does not match the one built into this copy of YazSes"
            )
    return Match(REFUSED, tuple(reasons)) if reasons else Match(OK)
