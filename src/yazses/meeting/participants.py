"""Cross-meeting participant enrollment (ADR-v2-127 P5 · ADR-011/012).

Turn a diarized speaker cluster from a *stored* meeting into a named, enrolled voiceprint
so that person is auto-named ("Alice") in *future* meetings. Strictly opt-in and explicit
— never automatic (biometric-consent policy, ADR-011/012): the user names a specific
cluster with ``yazses meeting enroll``. The embedding is biometric, so it is stored only
encrypted with the machine-bound key (reusing ``voiceprint/store.py`` + ``learning/crypto``)
and never leaves the machine.

Requires the meeting's ``audio.wav`` to still exist, which only happens when
``[meeting] retain_audio = true``. The audio-slicing and profile I/O are pure/injectable
(embedder + cipher passed in), so the whole flow is unit-testable with fakes.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from yazses.meeting import store
from yazses.meeting.session import read_wav_mono_f32
from yazses.voiceprint.store import load_voiceprint, save_voiceprint

log = logging.getLogger(__name__)

_SUFFIX = ".vp"


def participants_dir(config=None) -> Path:
    """Directory holding enrolled participant voiceprints (machine-global)."""
    override = getattr(config, "participants_dir", "") or "" if config is not None else ""
    if override:
        return Path(override).expanduser()
    from yazses.platform import get_platform

    return get_platform().paths.data_dir / "participants"


def participant_stem(name: str) -> str:
    """Filesystem-safe stem for a display name (preserves it where possible). Pure."""
    cleaned = "".join(c for c in name.strip() if c not in '/\\\0').strip()
    return cleaned or "participant"


def _cluster_audio(audio, assigned, speaker_id, sample_rate: int) -> np.ndarray:
    """Concatenate the audio spans belonging to ``speaker_id``. Pure."""
    parts = []
    n = int(np.asarray(audio).shape[0])
    for spk, start, end, _text in assigned:
        if spk != speaker_id:
            continue
        a = max(0, int(float(start) * sample_rate))
        b = min(n, int(float(end) * sample_rate))
        if b > a:
            parts.append(audio[a:b])
    return np.concatenate(parts) if parts else np.array([], dtype="float32")


def participant_path(name: str, config=None) -> Path:
    """Where ``name``'s enrolled voiceprint lives, resolved against what is enrolled.

    A name is one participant regardless of case: asking for ``alice`` when ``Alice`` is
    already enrolled returns *Alice's* profile, and enrolling under it replaces her.

    This is not a preference, it is the only behaviour that can be the same everywhere.
    The display name is stored nowhere but the filename, so the file *is* the identity —
    and on a case-insensitive filesystem (macOS APFS, NTFS) ``Alice.vp`` and ``alice.vp``
    are one file whatever this function returns. Deriving the path from the name alone
    made ``existing_participant`` truthfully warn that ``alice`` would replace ``Alice``
    while these two paths compared unequal, so the warning and the write disagreed —
    and on Linux the same two names were two people. Which one you got was a property of
    the filesystem, not of YazSes.

    Resolving here keeps the identity uniform: at most one of a set of case-variants can
    be enrolled on any platform, and it keeps the case it was enrolled with. An exact
    stem match still wins, so a machine that already holds both variants (only reachable
    on a case-sensitive filesystem) keeps returning each of them for its own name.

    Reads the directory, so it is *not* pure — ``participant_stem`` is the pure half.
    """
    d = participants_dir(config)
    stem = participant_stem(name)
    if d.is_dir():
        folded = stem.casefold()
        fallback: Path | None = None
        # sorted() so a directory holding several case-variants resolves the same way
        # every time rather than in whatever order the filesystem hands them over.
        for existing in sorted(d.glob("*" + _SUFFIX)):
            if existing.stem == stem:
                return existing
            if fallback is None and existing.stem.casefold() == folded:
                fallback = existing
        if fallback is not None:
            return fallback
    return d / (stem + _SUFFIX)


def existing_participant(name: str, config=None) -> Path | None:
    """The already-enrolled profile this name would replace, or ``None``.

    Enrolling the same name twice is legitimate -- a longer or cleaner recording gives a
    better voiceprint -- so this does not block anything. But it overwrites biometric data
    the user deliberately enrolled, and doing that without a word is the wrong kind of
    quiet: a second Alice silently destroys the first, and nothing distinguishes the two
    cases from inside YazSes.
    """
    path = participant_path(name, config)
    return path if path.exists() else None


def enroll_participant(
    meeting_dir: str | Path,
    speaker_id: str,
    name: str,
    *,
    embedder,
    cipher,
    config=None,
    sample_rate: int = 16000,
) -> Path:
    """Embed ``speaker_id``'s audio from a stored meeting and save it as ``name``.

    Raises ``FileNotFoundError`` when the recording was not retained, or ``ValueError``
    when the cluster has no audio. Returns the written profile path.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a participant name is required")
    meeting_dir = Path(meeting_dir)
    audio_path = meeting_dir / "audio.wav"
    if not audio_path.exists():
        raise FileNotFoundError(
            "this meeting's recording was not retained; enrollment needs the audio "
            "(set `[meeting] retain_audio = true` before recording)"
        )
    view = store.load_result_view(meeting_dir)
    audio = read_wav_mono_f32(audio_path)
    clip = _cluster_audio(audio, view.assigned, speaker_id, sample_rate)
    if clip.size == 0:
        raise ValueError(f"no audio found for speaker {speaker_id!r} in {meeting_dir.name}")
    embedding = embedder.embed(clip, sample_rate)
    path = participant_path(name, config)
    save_voiceprint(embedding, path, cipher)
    log.info("Enrolled participant %r from %s.", name, meeting_dir.name)
    return path


def load_participants(config, cipher) -> dict[str, np.ndarray]:
    """Load all enrolled participants as ``{name: embedding_vector}`` (empty if none)."""
    d = participants_dir(config)
    out: dict[str, np.ndarray] = {}
    if not d.exists():
        return out
    for p in sorted(d.glob("*" + _SUFFIX)):
        emb = load_voiceprint(p, cipher)
        if emb is not None:
            out[p.stem] = np.asarray(emb.vector, dtype="float32")
    return out
