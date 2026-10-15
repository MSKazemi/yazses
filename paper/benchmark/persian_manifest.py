"""Persian evaluation-manifest contract: load it, or refuse to run on it.

Part of FA-04 / #513. `bench_persian.py --manifest` scores a JSONL file of utterances; this
module is the gate in front of that: a pure, stdlib-only check that the manifest says what
the audio is, who may use it, and that every audio path stays where the operator said it
may. It carries no audio and decodes nothing, so a unit test can exercise every refusal
with empty files.

Format (one JSON object per line, UTF-8), plus a sidecar ``<manifest>.meta.json`` that
`make_fa_manifest.py` already writes beside the rows:

========== ======== ==============================================================
field      required meaning
========== ======== ==============================================================
id         yes      unique row id
audio      yes      path to a 16 kHz mono file; relative paths resolve against the
                    audio root (default: the manifest's own directory)
reference  yes      reference transcript (string; an empty one is scored as skipped)
speaker    no       opaque pseudonym, ``[A-Za-z0-9_-]{1,64}``
session    no       opaque pseudonym, same pattern
license    see ↓    SPDX-style licence id of the audio and transcript
consent    see ↓    how use of the recordings is authorised, e.g.
                    ``public-corpus-licence`` or ``participant-consent``
========== ======== ==============================================================

``license`` and ``consent`` must be non-blank for **every** row, taken from the row if it
has one and otherwise from the sidecar. The placeholders in `_PLACEHOLDERS` do not count:
a manifest that says ``"none"`` has not said anything. Nothing here can *verify* a
licence or a consent record, or that a pseudonym is really opaque; the check only stops
the harness from running on a manifest that does not make the claim at all, and from
accepting a speaker field that visibly is a name or an address.

The audio root is the only directory the run may read from. A path that resolves (after
``..`` and symlinks) outside it is refused, so a manifest copied from elsewhere cannot make
the harness open ``/etc/passwd``-shaped paths or another user's recordings. Operators whose
corpus lives elsewhere pass that directory explicitly (``--audio-root``).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Letters, digits, ``_`` and ``-`` only. Narrow on purpose: it rejects spaces, ``@`` and
#: Persian-script names, the shapes a real name or e-mail address takes, while any
#: generated token (a counter, a hex digest) passes.
PSEUDONYM_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_PLACEHOLDERS = frozenset(
    {"", "none", "unknown", "n/a", "na", "tbd", "todo", "null", "-", "?"}
)

#: Cap on the problems quoted in one refusal: a 10k-row manifest with one systematic
#: mistake should say so, not print 10k lines.
_MAX_LISTED = 10


class ManifestError(ValueError):
    """The manifest was refused. The message lists what is wrong, not just the first thing."""


@dataclass(frozen=True)
class Entry:
    id: str
    audio: Path  # resolved, inside the audio root, exists
    reference: str
    license: str
    consent: str
    speaker: str | None = None
    session: str | None = None


@dataclass(frozen=True)
class LoadedManifest:
    entries: tuple[Entry, ...]
    #: The rows exactly as read (before path resolution): the input to the result's
    #: ``selection.rows_sha256``.
    rows: tuple[dict, ...]
    meta: dict
    sha256: str  # of the manifest file's bytes
    audio_root: Path


def sidecar_path(manifest: Path) -> Path:
    """Where `make_fa_manifest.write_manifest` puts the metadata for *manifest*."""
    return manifest.with_suffix(manifest.suffix + ".meta.json")


def _filled(value: object) -> str | None:
    """*value* as a stripped string, or ``None`` when absent, blank or a placeholder."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.lower() in _PLACEHOLDERS else text


def _read_rows(manifest: Path) -> list[dict]:
    rows: list[dict] = []
    with manifest.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ManifestError(f"{manifest}:{n}: not valid JSON ({exc.msg})") from exc
            if not isinstance(row, dict):
                raise ManifestError(f"{manifest}:{n}: a row must be a JSON object")
            rows.append(row)
    if not rows:
        raise ManifestError(f"manifest has no rows: {manifest}")
    return rows


def _read_sidecar(manifest: Path) -> dict:
    path = sidecar_path(manifest)
    if not path.is_file():
        return {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: unreadable sidecar ({exc})") from exc
    if not isinstance(meta, dict):
        raise ManifestError(f"{path}: the sidecar must be a JSON object")
    return meta


def load_manifest(manifest: Path, audio_root: Path | None = None) -> LoadedManifest:
    """Read and validate *manifest*; raise `ManifestError` listing every problem found."""
    manifest = Path(manifest)
    try:
        raw = manifest.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest}: {exc}") from exc
    rows = _read_rows(manifest)
    meta = _read_sidecar(manifest)
    root = (Path(audio_root) if audio_root is not None else manifest.parent).resolve()

    problems: list[str] = []
    entries: list[Entry] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        where = f"row {i}"
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            problems.append(f"{where}: id missing")
            continue
        where = f"row {rid!r}"
        if rid in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(rid)

        reference = row.get("reference")
        if not isinstance(reference, str):
            problems.append(f"{where}: reference missing or not a string")
            reference = ""

        lic = _filled(row.get("license")) or _filled(meta.get("license"))
        consent = _filled(row.get("consent")) or _filled(meta.get("consent"))
        if lic is None:
            problems.append(f"{where}: no licence (row or sidecar 'license')")
        if consent is None:
            problems.append(f"{where}: no consent (row or sidecar 'consent')")

        ids: dict[str, str | None] = {}
        for key in ("speaker", "session"):
            value = row.get(key)
            if value is None:
                ids[key] = None
            elif isinstance(value, str) and PSEUDONYM_RE.fullmatch(value):
                ids[key] = value
            else:
                problems.append(
                    f"{where}: {key} must be an opaque pseudonym matching "
                    f"[A-Za-z0-9_-]{{1,64}}; a name or address is refused"
                )
                ids[key] = None

        audio_field = row.get("audio")
        audio: Path | None = None
        if not isinstance(audio_field, str) or not audio_field.strip():
            problems.append(f"{where}: audio missing")
        else:
            candidate = Path(audio_field)
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                problems.append(f"{where}: audio {audio_field!r} is outside the audio root {root}")
            elif not resolved.is_file():
                problems.append(f"{where}: audio {audio_field!r} does not exist")
            else:
                audio = resolved

        if audio is not None and lic is not None and consent is not None:
            entries.append(
                Entry(
                    id=rid,
                    audio=audio,
                    reference=reference,
                    license=lic,
                    consent=consent,
                    speaker=ids["speaker"],
                    session=ids["session"],
                )
            )

    if problems:
        shown = problems[:_MAX_LISTED]
        more = len(problems) - len(shown)
        tail = f"\n  ... and {more} more" if more > 0 else ""
        raise ManifestError(
            f"refusing to run: {len(problems)} problem(s) in {manifest}:\n  "
            + "\n  ".join(shown)
            + tail
        )
    return LoadedManifest(
        entries=tuple(entries),
        rows=tuple(rows),
        meta=meta,
        sha256=hashlib.sha256(raw).hexdigest(),
        audio_root=root,
    )
