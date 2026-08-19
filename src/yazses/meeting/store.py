"""Meeting-folder persistence + post-hoc relabelling (pure filesystem) — ADR-v2-127.

Each meeting is a folder ``<meetings_dir>/<id>/`` holding ``meeting.json`` (metadata),
``transcript.json`` (lossless canonical: per-word speaker + timestamps), the rendered
human transcript, an optional ``notes.md``, and optionally ``audio.wav`` (kept only when
``retain_audio``). ``relabel`` fixes an unknown-count miscount — merge two speaker
clusters and/or rename them — by **re-rendering from ``transcript.json``**, never
re-diarizing (ADR-v2-127 §unknown-count). All functions here are pure filesystem/logic
and unit-testable with ``tmp_path`` (no models).
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.recimport.align import Utterance, merge_utterances
from yazses.recimport.naming import resolve_names
from yazses.recimport.render import render_transcript

_META = "meeting.json"
_CANONICAL = "transcript.json"
_LIVE = "live.jsonl"
_EXT = {"md": "transcript.md", "txt": "transcript.txt", "srt": "transcript.srt",
        "vtt": "transcript.vtt", "json": _CANONICAL}


def meetings_dir(config) -> Path:
    """Directory holding per-meeting folders (``[meeting] output_dir`` or the data dir)."""
    override = getattr(config, "output_dir", "") or ""
    if override:
        return Path(override).expanduser()
    from yazses.platform import get_platform

    return get_platform().paths.data_dir / "meetings"


def new_meeting(config, meeting_id: str) -> Path:
    """Create and return the folder for a new meeting id."""
    d = meetings_dir(config) / meeting_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_meta(meeting_dir: str | Path, meta: dict) -> Path:
    p = Path(meeting_dir) / _META
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def read_meta(meeting_dir: str | Path) -> dict:
    p = Path(meeting_dir) / _META
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def list_meetings(config) -> list[dict]:
    """All stored meetings' metadata, newest first (by ``id`` — a sortable timestamp)."""
    root = meetings_dir(config)
    if not root.exists():
        return []
    out = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        meta = read_meta(d)
        meta.setdefault("id", d.name)
        meta["dir"] = str(d)
        # A meeting that never reached a clean finalize but left a live.jsonl can be
        # recovered from that partial transcript.
        if meta.get("status") != "done" and (d / _LIVE).exists():
            meta["recoverable"] = True
        out.append(meta)
    out.sort(key=lambda m: m.get("id", ""), reverse=True)
    return out


def append_live_line(meeting_dir: str | Path, text: str, t: float | None = None) -> None:
    """Append one finalized live-transcript line to ``live.jsonl`` (crash-resilient).

    Written incrementally during capture so a daemon crash mid-meeting still leaves a
    partial transcript on disk. This is a *recovery* artefact, separate from the
    authoritative ``transcript.json`` produced by the batch post-pass at stop. Best
    effort — a write failure never interrupts capture.
    """
    text = (text or "").strip()
    if not text:
        return
    rec: dict[str, object] = {"text": text}
    if t is not None:
        rec["t"] = round(float(t), 2)
    try:
        line = json.dumps(rec, ensure_ascii=False)
        with (Path(meeting_dir) / _LIVE).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:  # pragma: no cover - disk-full/permission; capture must not crash
        pass


def read_live_lines(meeting_dir: str | Path) -> list[dict]:
    """Read back ``live.jsonl`` as a list of ``{text, t?}`` records (empty if absent)."""
    p = Path(meeting_dir) / _LIVE
    if not p.exists():
        return []
    out: list[dict] = []
    # errors="replace", because this file exists precisely for the case where the daemon
    # died mid-write -- and a write cut in the middle of a multi-byte character makes
    # strict decoding raise UnicodeDecodeError for the WHOLE file. Every complete line
    # before the tear was readable and was being thrown away with it. The torn line
    # itself is then dropped by the json guard below, as a truncated line already was.
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def write_outputs(meeting_dir: str | Path, result, *, fmt: str = "md", notes_md=None) -> dict:
    """Write the canonical json, the human transcript in *fmt*, and optional notes.

    Returns ``{name: Path}`` for the files written.
    """
    d = Path(meeting_dir)
    written: dict[str, Path] = {}

    canon = d / _CANONICAL
    canon.write_text(render_transcript(result, "json"), encoding="utf-8")
    written["json"] = canon

    fmt = (fmt or "md").lower()
    if fmt != "json":
        human = d / _EXT.get(fmt, "transcript.md")
        human.write_text(render_transcript(result, fmt), encoding="utf-8")
        written[fmt] = human

    if notes_md:
        notes = d / "notes.md"
        notes.write_text(notes_md if notes_md.endswith("\n") else notes_md + "\n", encoding="utf-8")
        written["notes"] = notes
    return written


class _ResultView:
    """Duck-typed stand-in for ``TranscriptResult`` rebuilt from ``transcript.json``."""

    def __init__(self, *, text, utterances, assigned, language, diarized, speaker_names):
        self.text = text
        self.utterances = utterances
        self.assigned = assigned
        self.language = language
        self.diarized = diarized
        self.speaker_names = speaker_names


def load_result_view(meeting_dir: str | Path) -> _ResultView:
    """Rebuild a renderable result from the canonical ``transcript.json``."""
    data = json.loads((Path(meeting_dir) / _CANONICAL).read_text(encoding="utf-8"))
    assigned = [
        (w.get("speaker") or "", float(w["start"]), float(w["end"]), w["text"])
        for w in data.get("words", [])
    ]
    utterances = [
        Utterance(u.get("speaker") or "", float(u["start"]), float(u["end"]), u["text"])
        for u in data.get("utterances", [])
    ]
    return _ResultView(
        text=data.get("text", ""),
        utterances=utterances,
        assigned=assigned,
        language=data.get("language", "en"),
        diarized=bool(data.get("diarized", False)),
        speaker_names=dict(data.get("speakers", {})),
    )


def relabel(meeting_dir: str | Path, *, merges=None, renames=None, fmt: str = "md") -> dict:
    """Merge/rename speakers and re-render — no re-diarization (ADR-v2-127).

    ``merges`` maps a source cluster id to the target it folds into
    (``{"speaker_2": "speaker_1"}``); ``renames`` maps a (post-merge) cluster id to a
    display name (``{"speaker_1": "Alice"}``). Prior custom names are preserved unless
    renamed; anonymous "Speaker N" labels are renumbered. Re-writes json + the human file.
    """
    merges = dict(merges or {})
    renames = dict(renames or {})
    view = load_result_view(meeting_dir)

    def remap(spk: str) -> str:
        return merges.get(spk, spk) if spk else spk

    assigned = [(remap(spk), s, e, t) for (spk, s, e, t) in view.assigned]
    # merge_utterances treats None as "inherit"; empty speaker means unassigned word.
    merge_input = [((spk or None), s, e, t) for (spk, s, e, t) in assigned]
    utterances = merge_utterances(merge_input)

    # Preserve prior non-anonymous names (mapped through merges), let renames win.
    carried: dict[str, str] = {}
    for raw, name in view.speaker_names.items():
        if name and not name.startswith("Speaker "):
            carried[remap(raw)] = name
    carried.update({k: v for k, v in renames.items() if v})
    speaker_names = resolve_names(utterances, renames=carried)

    updated = _ResultView(
        text=view.text,
        utterances=utterances,
        assigned=assigned,
        language=view.language,
        diarized=view.diarized,
        speaker_names=speaker_names,
    )
    return write_outputs(meeting_dir, updated, fmt=fmt)
