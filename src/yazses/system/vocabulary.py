"""Personal dictionary — words STT mis-hears, primed into Whisper's initial_prompt.

Stored one word/phrase per line in ``vocabulary.txt`` next to config.toml. The
daemon merges these into the STT ``initial_prompt`` so hard-to-recognise names are
spelled correctly. Managed with ``yazses vocab add/list/remove``.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def vocab_path(config_dir) -> Path:
    return Path(config_dir) / "vocabulary.txt"


def load_vocab(path, *, strict: bool = False) -> list[str]:
    """Return the dictionary words (order preserved), or [] if absent.

    Tolerant by default, because `core/daemon.py::_on_hold_end` reads this file on EVERY
    burst. It used to decode strictly, so a single non-UTF-8 byte -- one word pasted from
    an editor in another encoding -- raised `UnicodeDecodeError` inside the burst's `try`
    and every dictation failed with a generic "could not type that", naming nothing. A
    directory at that path raised `IsADirectoryError` the same way.

    Losing one mojibake term costs a word that would not have matched anyway. Losing every
    burst costs the product. So a bad byte is replaced, an unreadable file yields nothing,
    and both are logged with the path.

    ``strict=True`` raises instead, and is what the writers below use: `add_vocab` and
    `remove_vocab` rewrite the WHOLE file from this list, so a tolerant read there would
    persist the replacement characters into the user's dictionary. Refusing to rewrite a
    file we could not read exactly is the only safe half of that pair.
    """
    p = Path(path)
    if not p.exists():
        return []
    # Decode strictly FIRST even when tolerant, so the fallback is detectable. Reading
    # straight through with `errors="replace"` never raises, so a warning hung off an
    # `except UnicodeDecodeError` there can never fire -- the file would be silently
    # mangled with nothing said, which is the failure this function is meant to end.
    try:
        raw = p.read_bytes()
    except OSError as exc:
        if strict:
            raise
        log.warning("could not read vocabulary file %s (%s); continuing without it", p, exc)
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if strict:
            raise
        text = raw.decode("utf-8", errors="replace")
        log.warning(
            "vocabulary file %s is not valid UTF-8; unreadable bytes were replaced. "
            "Dictation continues -- fix the file, or re-add the affected words with "
            "`yazses vocab add`.", p,
        )
    out: list[str] = []
    for line in text.splitlines():
        w = line.strip()
        if w:
            out.append(w)
    return out


# How many dictionary words to name before saying "and N more". Enough to
# recognise your own list at a glance, short enough for one `doctor` row.
_PREVIEW_TERMS = 3


def prompt_summary(
    configured: str,
    words,
    env_terms=(),
    *,
    mined: bool = False,
    context: bool = False,
) -> str:
    """One line naming everything that really reaches Whisper's ``initial_prompt``.

    ``doctor`` used to build this row from ``[stt] initial_prompt`` alone and print
    *"app name only (set [stt] initial_prompt to add vocabulary)"* — on a machine whose
    ``vocabulary.txt`` held 24 words that the daemon was merging on every burst. The row
    was not merely incomplete: it advised adding vocabulary to someone who had already
    added it, by the route the product itself recommends, and so read as proof that
    ``yazses vocab add`` had done nothing.

    ``core/daemon.py::_effective_initial_prompt`` is the composition; this is the
    description of it, and the two are pinned together by
    ``test_doctor_names_every_prompt_source``. Kept here rather than in ``stt/`` so a
    diagnostic can import it without pulling a speech engine in behind it.

    ``mined`` and ``context`` are passed as *gates*, not terms. Mining reads the
    encrypted corpus and context priming reads the focused window, the selection and the
    clipboard — far too much work for a status row, and both are transient by design, so
    naming any particular term would be a lie by the time it was printed. Whether they
    contribute at all is decidable from config, and that is the part worth reporting.
    """
    parts: list[str] = []
    text = (configured or "").strip()
    if text:
        preview = text if len(text) <= 40 else text[:37] + "..."
        parts.append(f"[stt] initial_prompt {preview!r}")
    terms = [w for w in words if str(w).strip()]
    if terms:
        shown = ", ".join(str(w).strip() for w in terms[:_PREVIEW_TERMS])
        extra = len(terms) - _PREVIEW_TERMS
        more = f", +{extra} more" if extra > 0 else ""
        parts.append(f"{len(terms)} from `yazses vocab` ({shown}{more})")
    env = [t for t in env_terms if str(t).strip()]
    if env:
        parts.append(f"{len(env)} from YAZSES_VOCABULARY")
    if mined:
        parts.append("terms mined from your corpus ([personalize] on)")
    if context:
        parts.append("salient terms from the active window ([context] on)")
    if not parts:
        return "app name only — add words with `yazses vocab add <word>`"
    return "app name + " + "; ".join(parts)


def add_vocab(path, words) -> list[str]:
    """Append *words* (case-insensitively de-duplicated), return the full list."""
    p = Path(path)
    existing = load_vocab(p, strict=True)
    seen = {w.lower() for w in existing}
    for w in words:
        w = w.strip()
        if w and w.lower() not in seen:
            existing.append(w)
            seen.add(w.lower())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(existing) + ("\n" if existing else ""), encoding="utf-8")
    return existing


def remove_vocab(path, word) -> list[str]:
    """Remove *word* (case-insensitive), return the remaining list."""
    p = Path(path)
    remaining = [w for w in load_vocab(p, strict=True) if w.lower() != word.strip().lower()]
    p.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
    return remaining


# --- moving the dictionary between machines (#295) ---------------------------
#
# The vocabulary is the main lever anyone has over recognition of *their own*
# proper nouns, package names, flags and acronyms — the words a general model gets
# wrong and that matter most in technical dictation. Without these, every new
# machine starts that work from zero, and a team with shared jargon cannot share
# the fix at all.


def export_vocab(path) -> str:
    """The dictionary as text: one entry per line, trailing newline, or "".

    Deliberately the same format as the stored file rather than JSON or TOML — it
    is a list of words, it should be greppable, diffable in a dotfiles repo, and
    obvious enough that someone can hand-write one to share.
    """
    words = load_vocab(path)
    return "\n".join(words) + ("\n" if words else "")


def parse_vocab(text: str) -> list[str]:
    """Read entries out of exported text.

    Blank lines are skipped and ``#`` comments are honoured, so a shared domain
    vocabulary can explain itself. Within one import, duplicates collapse
    case-insensitively — the same rule :func:`add_vocab` already applies.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    return out


def import_vocab(path, text: str, *, replace: bool = False) -> tuple[list[str], int]:
    """Import entries from *text*. Returns (full list, number actually added).

    Merging is the default and de-duplicates case-insensitively: repeated imports
    would otherwise grow the file and dilute the prompt, and prompt length is not
    free — `stt/vocabulary.py::merge_initial_prompt` puts every one of these in
    front of the decoder.

    ``replace`` discards the existing dictionary. It is the destructive one, so
    the caller is expected to confirm it; this function does not prompt, because
    the confirmation belongs where the user is, not in a pure helper.
    """
    incoming = parse_vocab(text)
    if replace:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(incoming) + ("\n" if incoming else ""), encoding="utf-8")
        return incoming, len(incoming)

    before = len(load_vocab(path))
    full = add_vocab(path, incoming)
    return full, len(full) - before
