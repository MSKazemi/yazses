"""Parse and validate the pack index, ``pack.json`` and ``RECORD.json`` (pure).

Every parser here returns a typed, frozen dataclass or raises :class:`ManifestError`,
whose message is a sentence a user can be shown. Nothing else is raised: the callers are
a runtime hook that must never stop YazSes from starting and UI paths that must never
show a traceback (ADR-028 §2, spec *Error semantics*).

Rules shared by all three formats (spec *Contracts*):

* ``format`` must be :data:`FORMAT`. An unknown format refuses everything with "this
  add-on index needs a newer YazSes" — guessing at a newer layout is how an old app
  would come to load code it does not understand.
* Unknown keys are ignored, so a later build may add fields without breaking older apps.
* A missing required key, or a value of the wrong type, refuses. ``True`` is not an
  integer here, although Python says it is.
* An index entry's ``asset`` name is **re-derived and compared**, never trusted.

**Counting convention**, as ``scripts/build-packs.py`` writes it (spec, *Implementation
status*, item 1): ``files`` and ``unpacked_bytes`` count **every** archive member,
``pack.json`` and ``RECORD.json`` included (the build computes ``pack.json`` to a fixed
point). ``RECORD.json`` lists every member *except* those two, because ``pack.json`` cannot
state its own hash and ``RECORD.json`` cannot hash itself.

``path_entries`` (optional, default empty) are pack-root-relative directories taken from
``.pth`` lines that only add a path; the loader appends them after ``site/``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FORMAT",
    "IndexEntry",
    "ManifestError",
    "PackIndex",
    "PackManifest",
    "PythonTag",
    "Record",
    "RecordEntry",
    "expected_asset_name",
    "is_safe_relpath",
    "parse_index",
    "parse_manifest",
    "parse_record",
    "platform_os",
]

#: The only layout this build understands, for the index, ``pack.json`` and ``RECORD.json``.
FORMAT = 1

#: Pack names become a path component (``packs/b-<id>/<name>/``) and part of a release
#: asset name, so they are short, lower-case and boring. 16 characters keeps the path
#: budget in :mod:`yazses.packs.layout` honest (``layout.MAX_PACK_NAME``).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_BUILD_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+!-]{0,63}$")
_ARCH_RE = re.compile(r"^[a-z0-9_]{1,16}$")
_PLATFORM_RE = re.compile(r"^[a-z0-9_.-]{1,40}$")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DIST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: ``sysconfig.get_platform()`` prefix -> the OS word release assets use.
_PLATFORM_OS = {"win": "windows", "macosx": "macos", "linux": "linux"}

#: The upper bound on any count or size a manifest may state. Far above any real pack
#: (the archive ceiling is 1.9 GiB, policy.PACK_MAX_BYTES); it only stops absurd values.
_MAX_INT = 1 << 40


class ManifestError(ValueError):
    """A pack index, ``pack.json`` or ``RECORD.json`` was refused. ``str()`` is a user
    sentence."""


@dataclass(frozen=True)
class PythonTag:
    cache_tag: str
    version: str
    abi: str


@dataclass(frozen=True)
class IndexEntry:
    """One pack, as the index built into this installer lists it."""

    name: str
    asset: str
    sha256: str
    size: int
    unpacked_bytes: int
    files: int
    features: tuple[str, ...]


@dataclass(frozen=True)
class PackIndex:
    format: int
    app_version: str
    base_build_id: str
    python: PythonTag
    platform: str
    arch: str
    packs: tuple[IndexEntry, ...]

    def entry(self, name: str) -> IndexEntry | None:
        return next((p for p in self.packs if p.name == name), None)

    def for_feature(self, slug: str) -> IndexEntry | None:
        """The pack that serves capability ``slug`` in this build, or ``None``."""
        return next((p for p in self.packs if slug in p.features), None)


@dataclass(frozen=True)
class PackManifest:
    """``pack.json``: what one pack is, and the one base build it belongs to."""

    format: int
    name: str
    extra: str
    features: tuple[str, ...]
    app_version: str
    base_build_id: str
    python: PythonTag
    platform: str
    arch: str
    distributions: tuple[tuple[str, str], ...]
    entry_modules: tuple[str, ...]
    native_dirs: tuple[str, ...]
    unpacked_bytes: int
    files: int
    #: Extra ``sys.path`` directories from ``.pth`` path lines (build item 4).
    path_entries: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecordEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Record:
    files: tuple[RecordEntry, ...]

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


# ---- small validators --------------------------------------------------------

def _load(text: str | bytes, what: str) -> dict[str, Any]:
    try:
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ManifestError(f"the {what} is not valid JSON ({exc.__class__.__name__})") from None
    if not isinstance(data, dict):
        raise ManifestError(f"the {what} is not a JSON object")
    fmt = data.get("format")
    if type(fmt) is not int or fmt != FORMAT:  # `True == 1.0 == 1` in Python; not here
        if isinstance(fmt, int) and not isinstance(fmt, bool) and fmt > FORMAT:
            raise ManifestError(
                f"this add-on {what} uses format {fmt}, which needs a newer YazSes; "
                "update YazSes and try again"
            )
        raise ManifestError(f"the {what} has an unknown format ({fmt!r})")
    return data


def _req(data: dict[str, Any], key: str, what: str) -> Any:
    if key not in data:
        raise ManifestError(f"the {what} is missing {key!r}")
    return data[key]


def _str(data: dict[str, Any], key: str, what: str, pattern: re.Pattern[str]) -> str:
    value = _req(data, key, what)
    if not isinstance(value, str) or not pattern.match(value):
        raise ManifestError(f"the {what} has an invalid {key!r}: {value!r}")
    return value


def _int(data: dict[str, Any], key: str, what: str, *, minimum: int = 0) -> int:
    value = _req(data, key, what)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"the {what} has a non-integer {key!r}: {value!r}")
    if not minimum <= value <= _MAX_INT:
        raise ManifestError(f"the {what} has an out-of-range {key!r}: {value}")
    return value


def _str_list(
    data: dict[str, Any], key: str, what: str, pattern: re.Pattern[str], *, empty_ok: bool
) -> tuple[str, ...]:
    value = _req(data, key, what)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"the {what} has an invalid {key!r} (not a list of strings)")
    if not value and not empty_ok:
        raise ManifestError(f"the {what} has an empty {key!r}")
    bad = [v for v in value if not pattern.match(v)]
    if bad:
        raise ManifestError(f"the {what} has an invalid entry in {key!r}: {bad[0]!r}")
    if len(set(value)) != len(value):
        raise ManifestError(f"the {what} lists a duplicate in {key!r}")
    return tuple(value)


def _python(data: dict[str, Any], what: str) -> PythonTag:
    raw = _req(data, "python", what)
    if not isinstance(raw, dict):
        raise ManifestError(f"the {what} has an invalid 'python' block")
    tag_re = re.compile(r"^[a-z0-9_.-]{1,32}$")
    return PythonTag(
        cache_tag=_str(raw, "cache_tag", f"{what} python block", tag_re),
        version=_str(raw, "version", f"{what} python block", _VERSION_RE),
        abi=_str(raw, "abi", f"{what} python block", tag_re),
    )


def is_safe_relpath(path: str, *, max_len: int = 140) -> bool:
    """A forward-slash relative path with no drive, root, ``..``, empty or dot segment,
    backslash, colon or control character, within ``max_len`` characters (pure).

    Shared by ``native_dirs`` here and by archive-member validation in
    :mod:`yazses.packs.archive`, so the two cannot disagree about what "inside the pack"
    means.
    """
    if not isinstance(path, str) or not path or len(path) > max_len:
        return False
    if path.startswith(("/", "\\")) or "\\" in path or ":" in path:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return False
    parts = path.split("/")
    return all(seg not in {"", ".", ".."} for seg in parts)


# ---- public parsers ----------------------------------------------------------

def platform_os(platform: str) -> str:
    """``win-amd64`` -> ``windows``. Raises :class:`ManifestError` for an unknown prefix."""
    prefix = platform.split("-", 1)[0].split("_", 1)[0]
    try:
        return _PLATFORM_OS[prefix]
    except KeyError:
        raise ManifestError(f"unknown platform {platform!r} in the add-on index") from None


def expected_asset_name(app_version: str, platform: str, arch: str, name: str) -> str:
    """``YazSes-<v>-<os>-<arch>-pack-<name>.yazpack`` — the one name an asset may have."""
    return f"YazSes-{app_version}-{platform_os(platform)}-{arch}-pack-{name}.yazpack"


def parse_index(text: str | bytes) -> PackIndex:
    """The embedded ``yazses-packs-index.json`` (or the release's ``…-packs.json``)."""
    what = "index"
    data = _load(text, what)
    app_version = _str(data, "app_version", what, _VERSION_RE)
    platform = _str(data, "platform", what, _PLATFORM_RE)
    arch = _str(data, "arch", what, _ARCH_RE)
    platform_os(platform)  # refuse an unknown platform up front
    raw_packs = _req(data, "packs", what)
    if not isinstance(raw_packs, list):
        raise ManifestError("the index's 'packs' is not a list")
    entries: list[IndexEntry] = []
    seen_features: dict[str, str] = {}
    for raw in raw_packs:
        if not isinstance(raw, dict):
            raise ManifestError("the index lists a pack that is not a JSON object")
        ewhat = "index entry"
        name = _str(raw, "name", ewhat, _NAME_RE)
        ewhat = f"index entry for {name!r}"
        asset = _req(raw, "asset", ewhat)
        wanted = expected_asset_name(app_version, platform, arch, name)
        if asset != wanted:
            raise ManifestError(
                f"the {ewhat} names the asset {asset!r}; this build expects {wanted!r}"
            )
        entry = IndexEntry(
            name=name,
            asset=wanted,
            sha256=_str(raw, "sha256", ewhat, _SHA_RE),
            size=_int(raw, "size", ewhat, minimum=1),
            unpacked_bytes=_int(raw, "unpacked_bytes", ewhat),
            files=_int(raw, "files", ewhat),
            features=_str_list(raw, "features", ewhat, _SLUG_RE, empty_ok=False),
        )
        if any(e.name == name for e in entries):
            raise ManifestError(f"the index lists the pack {name!r} twice")
        for slug in entry.features:
            if slug in seen_features:
                raise ManifestError(
                    f"the index offers {slug!r} from two packs ({seen_features[slug]!r} "
                    f"and {name!r})"
                )
            seen_features[slug] = name
        entries.append(entry)
    return PackIndex(
        format=FORMAT,
        app_version=app_version,
        base_build_id=_str(data, "base_build_id", what, _BUILD_ID_RE),
        python=_python(data, what),
        platform=platform,
        arch=arch,
        packs=tuple(entries),
    )


def parse_manifest(text: str | bytes) -> PackManifest:
    """``pack.json`` from an archive or an installed tree."""
    what = "pack.json"
    data = _load(text, what)
    raw_dists = _req(data, "distributions", what)
    if not isinstance(raw_dists, list):
        raise ManifestError("pack.json's 'distributions' is not a list")
    dists: list[tuple[str, str]] = []
    for raw in raw_dists:
        if not isinstance(raw, dict):
            raise ManifestError("pack.json lists a distribution that is not an object")
        dists.append((
            _str(raw, "name", "pack.json distribution", _DIST_RE),
            _str(raw, "version", "pack.json distribution", _VERSION_RE),
        ))
    native = _req(data, "native_dirs", what)
    if not isinstance(native, list) or not all(isinstance(n, str) for n in native):
        raise ManifestError("pack.json's 'native_dirs' is not a list of strings")
    for entry in native:
        if not is_safe_relpath(entry) or entry.split("/", 1)[0] not in {"site", "stdlib"}:
            raise ManifestError(
                f"pack.json names a native directory outside the pack: {entry!r}"
            )
    extra_paths = data.get("path_entries", [])
    if not isinstance(extra_paths, list) or not all(isinstance(p, str) for p in extra_paths):
        raise ManifestError("pack.json's 'path_entries' is not a list of strings")
    for entry in extra_paths:
        if not is_safe_relpath(entry) or entry.split("/", 1)[0] not in {"site", "stdlib"}:
            raise ManifestError(f"pack.json names a path entry outside the pack: {entry!r}")
    platform = _str(data, "platform", what, _PLATFORM_RE)
    platform_os(platform)
    return PackManifest(
        format=FORMAT,
        name=_str(data, "name", what, _NAME_RE),
        extra=_str(data, "extra", what, _SLUG_RE),
        features=_str_list(data, "features", what, _SLUG_RE, empty_ok=False),
        app_version=_str(data, "app_version", what, _VERSION_RE),
        base_build_id=_str(data, "base_build_id", what, _BUILD_ID_RE),
        python=_python(data, what),
        platform=platform,
        arch=_str(data, "arch", what, _ARCH_RE),
        distributions=tuple(dists),
        entry_modules=_str_list(data, "entry_modules", what, _MODULE_RE, empty_ok=False),
        native_dirs=tuple(native),
        unpacked_bytes=_int(data, "unpacked_bytes", what),
        files=_int(data, "files", what),
        path_entries=tuple(extra_paths),
    )


def parse_record(text: str | bytes) -> Record:
    """``RECORD.json``: ``{"format": 1, "files": [{"path", "size", "sha256"}, ...]}``."""
    what = "RECORD.json"
    data = _load(text, what)
    raw = _req(data, "files", what)
    if not isinstance(raw, list):
        raise ManifestError("RECORD.json's 'files' is not a list")
    out: list[RecordEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError("RECORD.json lists a file that is not an object")
        path = _req(item, "path", what)
        if not isinstance(path, str) or not is_safe_relpath(path):
            raise ManifestError(f"RECORD.json lists an unsafe path: {path!r}")
        if path in {"pack.json", "RECORD.json"}:
            raise ManifestError(f"RECORD.json lists {path}, which is not payload")
        folded = path.casefold()
        if folded in seen:
            raise ManifestError(f"RECORD.json lists {path!r} twice")
        seen.add(folded)
        out.append(RecordEntry(
            path=path,
            size=_int(item, "size", what),
            sha256=_str(item, "sha256", what, _SHA_RE),
        ))
    return Record(files=tuple(out))
