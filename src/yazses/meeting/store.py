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
import logging
from pathlib import Path

from yazses.postprocess.cleaner import clean_text
from yazses.recimport.align import Utterance, merge_utterances
from yazses.recimport.naming import resolve_names
from yazses.recimport.pipeline import cleaned_utterance
from yazses.recimport.render import render_transcript

log = logging.getLogger(__name__)

_META = "meeting.json"
_CANONICAL = "transcript.json"
_LIVE = "live.jsonl"
_AUDIO = "audio.wav"
# Rendered from `live.jsonl` at every finalize and every recovery, unconditionally.
# `live.jsonl` has existed since Meeting Mode shipped and is the artefact that saved a
# real 41-minute meeting whose batch pass collapsed -- but it is newline-delimited JSON,
# which is not a thing anyone reads after a meeting. Rendering it costs nothing and
# turns a recovery format into a second, independent transcript.
_LIVE_MD = "live-transcript.md"
_QUALITY = "quality.json"
_SUMMARY = "summary.md"
# Previous outputs are moved here rather than overwritten when a meeting is re-run.
# A retry that replaces a transcript with a worse one is a data loss that looks like a
# repair, and the whole point of retrying is that the first result was not trusted.
_ATTEMPTS = "attempts"
# A `wave` file opened for writing has its 44-byte canonical header on disk before
# a single frame is appended, so "the file exists" is not "there is a recording".
_WAV_HEADER_BYTES = 44
_EXT = {"md": "transcript.md", "txt": "transcript.txt", "srt": "transcript.srt",
        "vtt": "transcript.vtt", "json": _CANONICAL}


# What the recording itself turned out to hold. `ok` is written explicitly rather
# than left absent, so a meeting from before this field existed ("" / missing) is
# distinguishable from one that was checked and passed.
CAPTURE_OK = "ok"
CAPTURE_NO_SIGNAL = "no_signal"
CAPTURE_NO_SPEECH = "no_speech"


def capture_state(silent_input: bool, no_speech: bool) -> str:
    """The recording's verdict, from the two flags ``transcribe_file`` returns. Pure."""
    if silent_input:
        return CAPTURE_NO_SIGNAL
    if no_speech:
        return CAPTURE_NO_SPEECH
    return CAPTURE_OK


def duration_summary(meta: dict) -> str:
    """How long the meeting ran, read at a glance. ``""`` when it was never recorded.

    Every ``meeting.json`` has carried ``duration_s`` since Meeting Mode shipped and no
    surface ever printed it. Measured on a real machine: four meetings listed as four
    bare timestamps, holding **11.6 s, 26.6 s, 56.7 s and 8081.4 s** — one real meeting
    and three accidental starts, indistinguishable without opening four files. Telling
    them apart is what a person opens this list to do, and the fact was already there.

    Empty rather than ``"unknown"`` when the key is missing: a meeting that never
    finalized has no ``meeting.json`` at all, and its row already says ``unfinished``.
    A second word for the same fact is noise. ``0s`` is *not* that case and is shown —
    a meeting that recorded nothing is worth seeing.

    Thresholds match ``cli._format_uptime``; ``test_the_two_formatters_agree`` pins that,
    since two formatters for one idea are how surfaces drift apart.
    """
    raw = meta.get("duration_s")
    if raw is None:
        return ""
    try:
        total = int(float(raw))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    return f"{total // 3600}h {(total % 3600) // 60}m"


def capture_warning(meta: dict) -> str | None:
    """One line for a meeting whose audio held nothing worth transcribing, else None.

    A meeting is unattended and long, which is what makes this worth a field of its
    own. `yazses transcribe` can print a note to stderr and be read; a meeting
    finalizes hours later into `status: "done"`, and by default its audio is deleted
    the moment the post-pass returns (`[meeting] retain_audio`). Without this the
    only evidence left is a transcript of words nobody said.

    The two states are kept apart because the remedies are: a dead capture is a
    device problem, an empty room is not.
    """
    state = meta.get("capture")
    if state == CAPTURE_NO_SIGNAL:
        return (
            "⚠ the recording carried no signal — any text in this meeting was invented, "
            "not heard. The microphone was muted, held by another application, or the "
            "wrong device was recorded (`yazses audio devices`)."
        )
    if state == CAPTURE_NO_SPEECH:
        return (
            "⚠ sound was recorded but a speech detector found none in it — any text in "
            "this meeting was invented, not heard. Nobody spoke, the room was captured "
            "instead of the call, or the speech was too faint to detect."
        )
    return None


def has_recording(wav: Path | str) -> bool:
    """True when the file holds recorded frames, not just a header. Never raises.

    Public because the listing and ``recover``'s refusal must answer this question the
    same way. They did not: the refusal carried its own literal 44, so a drift in either
    would have produced a meeting the listing offers to recover and the command declines
    (or worse, the reverse).
    """
    wav = Path(wav)
    try:
        return wav.exists() and wav.stat().st_size > _WAV_HEADER_BYTES
    except OSError:  # pragma: no cover - a racing delete or an unreadable mount
        return False


def recovery_advice(meta: dict, live_lines: int = 0) -> list[str]:
    """Indented lines saying what survives an unfinished meeting. Pure.

    Ordered by which artefact is worth reaching for: the recording re-runs the real
    post-pass (diarization, naming, minutes), the live transcript is what the rolling
    decode happened to catch. Returning both when both exist matters -- the audio is
    the better route, but a user who wants to read something *now* should not have to
    discover the other file by listing the directory.
    """
    if not meta.get("recoverable"):
        return []
    lines: list[str] = []
    # "did not finish" and "finished, but the transcript is not usable" send the reader
    # to the same command and to two completely different expectations, so they are not
    # allowed to share a sentence.
    bad = bool(meta.get("quality_suspect"))
    lead = "⚠ the transcript is NOT usable" if bad else "⚠ did not finish"
    if bad and meta.get("live_transcript_path"):
        lines.append(
            f"{lead} — read {_LIVE_MD} in this folder instead (an independent decode "
            "of the same audio)."
        )
        lead = "…and"
    if meta.get("audio_path"):
        lines.append(
            f"{lead} — the whole recording was kept. "
            f"`yazses meeting recover {meta.get('id', '')}` re-runs the post-pass on it."
        )
        lead = "…and"
    if live_lines and not meta.get("live_transcript_path"):
        lines.append(
            f"{'…and ' if lines else lead + ' — '}{live_lines} line(s) of live "
            f"transcript are readable in {meta.get('dir', '')}/{_LIVE}"
        )
    if not lines:
        # Recoverable was set, so something is there; say so rather than print nothing.
        lines.append(f"{lead} — see {meta.get('dir', '')}")
    return [f"    {line}" for line in lines]


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
        # A meeting that never reached a clean finalize leaves one or both of two
        # artefacts, and they are not equally good. `live.jsonl` is the rolling
        # low-quality transcript streamed during capture. `audio.wav` is the whole
        # recording -- the daemon deletes it only *after* the post-pass succeeds, and
        # its own failure log says the file "has been KEPT ... so it can be retried".
        # That promise was made to the log and to nothing else: this listing checked
        # only for the live file, so a crash before the first utterance was decoded
        # (or `[meeting] live_transcript = false`) printed the meeting as if it had
        # finished, with the entire recording sitting in the same folder.
        # A meeting is worth offering a retry for when it never finished OR when it
        # finished badly. The second case did not exist as a concept: `status: "done"`
        # was taken to mean the transcript was good, and a decode that collapsed into a
        # repetition loop sets it exactly like a healthy one does. That meeting is the
        # one that most needs a retry, and it was the one the listing called finished.
        if meta.get("status") != "done" or meta.get("quality_suspect"):
            wav = d / _AUDIO
            if has_recording(wav):
                meta["recoverable"] = True
                meta["audio_path"] = str(wav)
            elif (d / _LIVE).exists():
                meta["recoverable"] = True
        if (d / _LIVE_MD).exists():
            meta["live_transcript_path"] = str(d / _LIVE_MD)
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
    if view.diarized:
        # merge_utterances treats None as "inherit"; empty speaker means unassigned word.
        merge_input = [((spk or None), s, e, t) for (spk, s, e, t) in assigned]
        utterances = merge_utterances(merge_input)
    else:
        # Not diarized: `recimport/pipeline.py` calls merge_utterances only under
        # `if diarized:` and gives an undiarized recording exactly one utterance for the
        # whole of it -- there are no turns to break a run on, and a silence gap is not
        # one. Running it here re-cut, on the 1.0 s default, a transcript the user asked
        # only to re-label. Remapping speakers is all this branch owes; the shape stays.
        utterances = [
            Utterance(remap(u.speaker), u.start, u.end, u.text) for u in view.utterances
        ]

    # The same cleaning the finalize pass applies. `assigned`/`words` are stored
    # deliberately uncleaned (they are timing data feeding alignment and subtitle spans),
    # so anything rebuilt from them brings back the artefacts Whisper narrates over
    # silence -- an 11.6 s meeting of room noise stored as ". . .".
    utterances = [u for u in (cleaned_utterance(u) for u in utterances) if u is not None]

    # Preserve prior non-anonymous names (mapped through merges), let renames win.
    carried: dict[str, str] = {}
    for raw, name in view.speaker_names.items():
        if name and not name.startswith("Speaker "):
            carried[remap(raw)] = name
    carried.update({k: v for k, v in renames.items() if v})
    speaker_names = resolve_names(utterances, renames=carried)

    updated = _ResultView(
        text=clean_text(view.text),
        utterances=utterances,
        assigned=assigned,
        language=view.language,
        diarized=view.diarized,
        speaker_names=speaker_names,
    )
    return write_outputs(meeting_dir, updated, fmt=fmt)


# --- second transcript, quality record, and the end-of-meeting readout -----------
# Everything below exists to make a meeting survive its own post-pass. The batch decode
# is one fallible step; these turn its failure into a warning plus a second copy, rather
# than into a folder of plausible-looking text nobody can tell is wrong.


def live_text(meeting_dir: str | Path) -> str:
    """All live-transcript lines joined into one string (``""`` when there are none)."""
    return " ".join(
        str(r.get("text", "")).strip()
        for r in read_live_lines(meeting_dir)
        if str(r.get("text", "")).strip()
    )


def live_word_count(meeting_dir: str | Path) -> int:
    """Word count of the rolling live decode — the second opinion on the batch pass."""
    from yazses.meeting.quality import tokenize

    return len(tokenize(live_text(meeting_dir)))


def render_live_transcript(records: list[dict], meeting_id: str = "") -> str:
    """``live.jsonl`` records → readable markdown. Pure.

    Timestamps are kept on every line because this file's whole job is to be readable
    when the batch transcript — the one with word-level timing — cannot be trusted.
    """
    head = f"# Live transcript{f' — {meeting_id}' if meeting_id else ''}"
    lines = [
        head,
        "",
        "_Streamed incrementally during the meeting. This is an independent decode of "
        "the same audio as `transcript.md`; when the two disagree, `quality.json` says "
        "which one to trust._",
        "",
    ]
    for r in records:
        text = str(r.get("text", "")).strip()
        if not text:
            continue
        t = r.get("t")
        stamp = ""
        if t is not None:
            try:
                total = int(float(t))
                stamp = f"[{total // 60:02d}:{total % 60:02d}] "
            except (TypeError, ValueError):
                stamp = ""
        lines.append(f"{stamp}{text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_live_transcript(meeting_dir: str | Path, meeting_id: str = "") -> Path | None:
    """Render ``live.jsonl`` to ``live-transcript.md``. Best effort — never raises.

    Never raises because it is called from the finalize path: a failure to render the
    *backup* transcript must not cost the primary one.
    """
    records = read_live_lines(meeting_dir)
    if not records:
        return None
    p = Path(meeting_dir) / _LIVE_MD
    try:
        p.write_text(render_live_transcript(records, meeting_id), encoding="utf-8")
    except OSError:  # pragma: no cover - disk-full / read-only mount
        log.warning("Could not write %s", p)
        return None
    return p


def write_quality(meeting_dir: str | Path, quality) -> Path | None:
    """Persist the quality metrics as ``quality.json``. Best effort — never raises.

    Written for every meeting, healthy or not: a verdict is only meaningful next to the
    numbers of the meetings it did *not* fire on, and those numbers exist exactly once —
    at finalize, while the transcript is in hand.
    """
    p = Path(meeting_dir) / _QUALITY
    try:
        payload = quality.as_dict() if hasattr(quality, "as_dict") else dict(quality)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError):  # pragma: no cover - defensive
        log.warning("Could not write %s", p)
        return None
    return p


def read_quality(meeting_dir: str | Path) -> dict:
    """``quality.json`` as a dict, or ``{}`` when absent/unreadable."""
    p = Path(meeting_dir) / _QUALITY
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def archive_outputs(meeting_dir: str | Path) -> Path | None:
    """Move the current transcript/notes/summary into ``attempts/<n>/``. Returns the dir.

    Called before a re-run writes over them. Nothing is ever deleted — a second decode
    can be *worse* than the first (that is the nature of the failure this whole module
    exists for), and the user must be able to compare rather than take the newest on
    faith. ``None`` when there was nothing to archive.
    """
    d = Path(meeting_dir)
    movable = [
        d / name
        for name in (_CANONICAL, _SUMMARY, _QUALITY, "notes.md", *_EXT.values())
        if (d / name).exists()
    ]
    # dict.fromkeys: `_EXT` maps "json" to `_CANONICAL`, so the canonical file is named
    # twice and would otherwise be moved, then looked for again at a path that no longer
    # exists. Ordered-unique rather than a set so the archive is written deterministically.
    movable = list(dict.fromkeys(movable))
    if not movable:
        return None
    root = d / _ATTEMPTS
    n = 1
    while (root / str(n)).exists():
        n += 1
    dest = root / str(n)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for src in movable:
            src.replace(dest / src.name)
    except OSError:  # pragma: no cover - read-only mount
        log.warning("Could not archive previous outputs under %s", dest)
        return None
    log.info("Previous meeting outputs archived to %s", dest)
    return dest


def summary_lines(meta: dict, *, live_lines: int = 0, quality: dict | None = None) -> list[str]:
    """The end-of-meeting readout: what came out, where it is, what to distrust. Pure.

    A meeting is the one capability with no key to hold and no terminal in front of it.
    Its post-pass finishes minutes after the user has walked away, so everything the
    product knows about the result has to survive into a form they find later. This is
    that form; it is printed, notified, *and* written to ``summary.md`` in the folder,
    because the three surfaces disagreeing about a 2-hour meeting is its own failure.

    Ordered by what a returning reader needs: is it usable, what is it, where is it.
    """
    quality = quality or {}
    mid = str(meta.get("id", ""))
    d = str(meta.get("dir", ""))
    out: list[str] = [f"Meeting {mid}" if mid else "Meeting"]

    if length := duration_summary(meta):
        out.append(f"  Duration: {length}")

    # Bad news first and unhedged. A warning printed under the file list is a warning
    # read after the reader has already decided the meeting went fine.
    if warn := capture_warning(meta):
        out.append(f"  {warn}")
    if quality.get("suspect"):
        from yazses.meeting.quality import QUALITY_DEGENERATE, QUALITY_THIN

        verdict = quality.get("verdict")
        if verdict == QUALITY_DEGENERATE:
            out.append("  ⚠ transcript.md collapsed into a repetition loop — do NOT read it as a record.")
        elif verdict == QUALITY_THIN:
            out.append("  ⚠ transcript.md holds almost no words for a recording this long.")
        else:
            out.append("  ⚠ transcript.md disagrees sharply with the live transcript of the same audio.")
        for reason in quality.get("reasons", [])[:4]:
            out.append(f"      · {reason}")
    if suspect := meta.get("attribution_suspect"):
        out.append(f"  ⚠ {suspect}")

    speakers = meta.get("speakers") or []
    if meta.get("diarized") and speakers:
        out.append(f"  Speakers: {', '.join(str(s) for s in speakers)}")
    elif not meta.get("diarized"):
        out.append("  Speakers: not separated (diarization off or unavailable)")

    out.append("  Files:")
    files = describe_files(meta, live_lines=live_lines, quality=quality)
    out.extend(f"    {line}" for line in files)
    if d:
        out.append(f"  Folder: {d}")
    return out


def describe_files(meta: dict, *, live_lines: int = 0, quality: dict | None = None) -> list[str]:
    """One line per artefact that exists, each saying what it is *for*. Pure.

    Existence is read from ``meta`` rather than the filesystem so this renders the same
    way for a meeting on another machine and stays testable without fixtures on disk.
    The ordering is the recommendation: when the batch pass is suspect the live
    transcript is listed first, because a list is read top-down and the first entry is
    what most people open.
    """
    quality = quality or {}
    suspect = bool(quality.get("suspect"))
    batch = f"transcript.md — batch transcript{' ⚠ UNRELIABLE' if suspect else ''}"
    n = quality.get("live_words") or 0
    live = f"{_LIVE_MD} — live transcript streamed during the meeting" + (
        f" ({n} word{'' if n == 1 else 's'})" if n else ""
    )
    out: list[str] = []
    if live_lines and suspect:
        out.append(f"✅ {live} — READ THIS ONE")
        out.append(f"   {batch}")
    else:
        out.append(f"   {batch}")
        if live_lines:
            out.append(f"   {live}")
    out.append(f"   {_CANONICAL} — word-level timings + speakers (machine-readable)")
    if live_lines:
        out.append(f"   {_LIVE} — raw live-decode records")
    if meta.get("has_notes"):
        out.append("   notes.md — generated minutes")
    if quality:
        out.append(f"   {_QUALITY} — decode-quality metrics for this meeting")
    if meta.get("audio_kept"):
        out.append(f"   {_AUDIO} — recording KEPT (re-run: `yazses meeting recover {meta.get('id', '')}`)")
    return out


def write_summary(meeting_dir: str | Path, lines: list[str]) -> Path | None:
    """Persist the readout as ``summary.md``. Best effort — never raises."""
    p = Path(meeting_dir) / _SUMMARY
    # A fenced block, not prose: these lines are aligned two- and four-space indents
    # naming files, and a markdown renderer would eat the indentation that makes them
    # readable — which is the only reason this file is written at all.
    body = "\n".join(["```text", *lines, "```", ""])
    try:
        p.write_text(body, encoding="utf-8")
    except OSError:  # pragma: no cover - disk-full / read-only mount
        log.warning("Could not write %s", p)
        return None
    return p


def ensure_quality(meeting_dir: str | Path, meta: dict | None = None) -> dict:
    """Return this meeting's quality record, computing and backfilling it if absent.

    Every meeting recorded before the quality check existed has a ``transcript.json``
    and no verdict, and one of them is the collapsed 41-minute meeting that motivated
    the check. Recomputing on demand from the stored transcript is what lets the fix
    reach meetings that already happened, rather than only ones recorded from now on —
    a repair that cannot be applied backwards leaves the user's actual problem in place.

    The result is persisted (``quality.json``, plus ``quality``/``quality_suspect`` in
    ``meeting.json``) so the listing — which must stay cheap and does not re-read a
    1.7 MB transcript per row — sees it from then on. Never raises: a meeting with no
    transcript, or an unreadable one, yields ``{}`` and is described as it was before.
    """
    existing = read_quality(meeting_dir)
    if existing:
        return existing

    d = Path(meeting_dir)
    canon = d / _CANONICAL
    if not canon.exists():
        return {}
    try:
        data = json.loads(canon.read_text(encoding="utf-8"))
        text = str(data.get("text", ""))
    except (ValueError, OSError):
        log.warning("Could not read %s to judge its quality", canon)
        return {}

    meta = read_meta(d) if meta is None else meta
    # `duration_s` over the word timings, in that order: the metadata is authoritative
    # and cheap, and the timings are the fallback for a meeting whose meta predates it.
    duration = meta.get("duration_s")
    if duration is None:
        words = data.get("words") or []
        duration = float(words[-1].get("end", 0.0)) if words else 0.0

    from yazses.meeting.quality import assess

    q = assess(text, duration, live_word_count(d))
    write_quality(d, q)
    if meta:
        # Merged into the existing metadata rather than rewritten from the verdict: this
        # runs over meetings finalized by older versions, and dropping a field they wrote
        # would be this function destroying the record it exists to complete.
        #
        # `dir`/`recoverable`/`audio_path`/`live_transcript_path` are injected into the
        # dict by `list_meetings` at read time and are not part of the stored record --
        # writing them back bakes this machine's absolute paths into a meeting folder
        # that can be copied, and freezes a "recoverable" flag that is meant to be
        # recomputed from what is on disk.
        runtime = ("dir", "recoverable", "audio_path", "live_transcript_path")
        stored = {k: v for k, v in meta.items() if k not in runtime}
        write_meta(d, {**stored, "quality": q.verdict, "quality_suspect": q.suspect})
    return q.as_dict()
