"""On-device meeting minutes (speaker-aware) — ADR-v2-128.

Turn a speaker-labelled transcript into structured minutes — a summary, decisions, action
items (with owners), and per-speaker highlights — with a **local** LLM. A one-hour meeting
exceeds a small model's context, so this uses **turn-aware map-reduce**: summarise windows
of utterances, then reduce the window-summaries into the final ``Minutes``. The LLM is an
injected callable ``llm(prompt) -> str`` returning JSON; when none is configured the
feature is dormant and ``generate_minutes`` returns ``None`` (transcript-only). The
windowing, prompt building, and JSON parsing are pure and unit-tested with a fake LLM;
only the per-window call touches a model. On-device only (ADR-011).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionItem:
    owner: str
    task: str


@dataclass(frozen=True)
class SpeakerNote:
    name: str
    points: list = field(default_factory=list)


@dataclass(frozen=True)
class Minutes:
    summary: str = ""
    decisions: list = field(default_factory=list)
    action_items: list = field(default_factory=list)  # list[ActionItem]
    per_speaker: list = field(default_factory=list)    # list[SpeakerNote]


def format_turns(utterances, speaker_names=None) -> str:
    """Render utterances as ``Name: text`` lines for the LLM prompt. Pure."""
    names = speaker_names or {}
    lines = []
    for u in utterances:
        label = names.get(u.speaker, u.speaker) if u.speaker else "Speaker"
        lines.append(f"{label}: {u.text}".strip())
    return "\n".join(lines)


#: real width once it knows the display names, because "Mohsen Seyedkazemi Ardebili"
#: is not 16 characters and 40 of those per window is not a rounding error.
_LINE_OVERHEAD_CHARS = 16


def line_overhead_chars(speaker_names=None) -> int:
    """Width of the longest ``"Name: "`` prefix :func:`format_turns` will emit. Pure."""
    labels = [str(v) for v in (speaker_names or {}).values() if str(v)]
    if not labels:
        return _LINE_OVERHEAD_CHARS
    return max(_LINE_OVERHEAD_CHARS, max(len(label) for label in labels) + 3)


#: Conservative characters-per-token for a llama.cpp BPE on meeting prose.
#:
#: English prose runs ~3.6-4.0 chars/token on Llama-family vocabularies, so 3.0
#: under-counts on purpose. Erring small only costs an extra window, and an extra
#: window is merged away by the reduce step; erring large costs a whole slice of
#: the meeting. The two directions are not symmetric, so the estimate is not
#: centred.
CHARS_PER_TOKEN = 3.0

#: Prompt boilerplate plus the ``Name: `` prefixes, in tokens. Rounded up.
_PROMPT_OVERHEAD_TOKENS = 200


def window_budget_chars(ctx_tokens: int, max_output_tokens: int) -> int:
    """How many characters of transcript may go into one map-step prompt. Pure.

    llama.cpp gives no room to be optimistic here, and it fails in two different
    ways at two different sizes:

    * At ``len(prompt_tokens) >= n_ctx`` it raises ``ValueError``. The caller logs a
      warning and moves on, so **that slice of the meeting is simply missing from
      the minutes** and the document does not say so.
    * Below that but above ``n_ctx - max_tokens`` it does not raise: it silently
      clips ``max_tokens`` to whatever is left. With the GBNF grammar on, the model
      is then cut off mid-object and the JSON never closes.

    Both bands were reachable with the shipped defaults, because the window was
    sized in **turns** (40) and a turn is one word or a five-minute monologue.
    Measured over the meetings stored on the author's machine, the two with a real
    transcript peak at ~3650 and ~3440 estimated tokens per 40-turn window --- both
    inside the silent-clipping band (``4096 - 1024 = 3072``), one of them at 89% of
    the hard limit on a 15-minute meeting.
    """
    usable = int(ctx_tokens) - int(max_output_tokens) - _PROMPT_OVERHEAD_TOKENS
    return max(1, int(usable * CHARS_PER_TOKEN))


def _split_long_text(text: str, budget: int) -> list:
    """Break one over-long turn on whitespace so it can fit a window at all. Pure."""
    words, out, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > budget:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    return out or [text[:budget]]


def window_turns(utterances, size: int, max_chars: int | None = None,
                 line_overhead: int = _LINE_OVERHEAD_CHARS):
    """Split utterances into contiguous windows of at most ``size`` turns, and at
    most ``max_chars`` characters of rendered text. Pure.

    ``size`` alone was the whole bound and it does not bound anything the model
    cares about --- see :func:`window_budget_chars`. ``max_chars`` is the real
    limit; the turn count stays as a secondary cap so existing behaviour is
    unchanged for short turns.

    A single turn longer than ``max_chars`` is split on whitespace rather than
    dropped: it cannot fit any window otherwise, and a monologue is exactly the
    turn a set of minutes must not lose.
    """
    size = max(1, int(size))
    if not max_chars or max_chars <= 0:
        return [utterances[i:i + size] for i in range(0, len(utterances), size)]

    windows: list = []
    current: list = []
    used = 0
    for utterance in utterances:
        pieces = [utterance]
        # Against the text budget, not the window budget: `format_turns` puts a
        # `"Name: "` label in front of every line, so a chunk of exactly `max_chars`
        # renders longer than `max_chars`.
        text_budget = max(1, max_chars - line_overhead)
        rendered = len(getattr(utterance, "text", "") or "")
        if rendered > text_budget:
            try:
                pieces = [
                    replace(utterance, text=chunk)
                    for chunk in _split_long_text(utterance.text, text_budget)
                ]
            except TypeError:
                # Not a dataclass. The rest of this module duck-types utterances, so
                # a caller may pass something else; give the over-long turn a window
                # to itself rather than refusing to window at all.
                pieces = [utterance]
        for piece in pieces:
            cost = len(getattr(piece, "text", "") or "") + line_overhead
            if current and (len(current) >= size or used + cost > max_chars):
                windows.append(current)
                current, used = [], 0
            current.append(piece)
            used += cost
    if current:
        windows.append(current)
    return windows


#: Default allowance for the ``"Name: "`` label and the newline that
#: :func:`format_turns` puts between lines. `generate_minutes` replaces it with the

_WINDOW_PROMPT = (
    "You are taking minutes for a meeting. Summarise this transcript excerpt. "
    "Return ONLY JSON: {{\"summary\": str, \"decisions\": [str], "
    "\"action_items\": [{{\"owner\": str, \"task\": str}}]}}.\n\nTranscript:\n{body}"
)
_GAP_NOTE = (
    "INCOMPLETE: {skipped} of {total} transcript windows could not be summarised, so "
    "part of this meeting is missing from these minutes. See live-transcript.md."
)
_REDUCE_PROMPT = (
    "Combine these partial meeting summaries into final minutes. Deduplicate and keep the "
    "most important points. Return ONLY JSON: {{\"summary\": str, \"decisions\": [str], "
    "\"action_items\": [{{\"owner\": str, \"task\": str}}], "
    "\"per_speaker\": [{{\"name\": str, \"points\": [str]}}]}}.\n\nPartials:\n{body}"
)


def is_empty(minutes) -> bool:
    """Whether these minutes carry nothing at all. Pure.

    Not the same question as "did the call raise". A model that is cut off mid-JSON
    returns normally and parses to an empty object, so this is the only way to tell a
    summarised window from a lost one.
    """
    return not (
        (minutes.summary or "").strip()
        or minutes.decisions
        or minutes.action_items
        or minutes.per_speaker
    )


def batch_partials(rendered: list, budget: int) -> list:
    """Group rendered partials into batches that each fit ``budget``. Pure.

    Returns a list of index lists. A single partial larger than the budget gets a
    batch of its own --- it cannot be made to fit, and dropping it would lose a
    window that decoded perfectly well.
    """
    batches: list = []
    current: list = []
    used = 0
    for index, text in enumerate(rendered):
        cost = len(text) + 2  # the blank line the join puts between them
        if current and used + cost > budget:
            batches.append(current)
            current, used = [], 0
        current.append(index)
        used += cost
    if current:
        batches.append(current)
    return batches


def _reduce_once(llm, partials, budget):
    """One reduce pass over ``partials``, in batches that fit. Returns a shorter list."""
    rendered = [_minutes_to_json(m) for m in partials]
    out = []
    for batch in batch_partials(rendered, budget):
        group = [partials[i] for i in batch]
        if len(group) == 1:
            out.append(group[0])
            continue
        body = "\n\n".join(rendered[i] for i in batch)
        try:
            out.append(_parse_minutes(llm(_REDUCE_PROMPT.format(body=body))))
        except Exception as exc:  # pragma: no cover - model-dependent
            log.warning("Minutes reduce batch failed (%s); merging it verbatim.", exc)
            out.append(_merge_partials(group))
    return out


def reduce_partials(llm, partials, budget: int):
    """Reduce ``partials`` to a single :class:`Minutes`, in as many passes as it takes.

    The reduce step used to be one call over **every** partial, and it did not fit.
    Measured on realistic per-window summaries it overflows a 4096-token context at
    about **eight** partials --- and the meetings stored on the author's machine
    produce eleven and three. So for anything past roughly twenty-five minutes the
    reduce always raised, always fell back to `_merge_partials`, and the user got a
    wall of concatenated per-window summaries with nothing deduplicated, labelled
    "minutes". The failure was in a `log.warning` and nowhere else.

    Reducing in batches and repeating collapses any number of partials in
    ``ceil(log(n))`` passes. The loop stops if a pass makes no progress, which is the
    only way it could spin: a single partial bigger than the whole budget.
    """
    while len(partials) > 1:
        reduced = _reduce_once(llm, partials, budget)
        if len(reduced) >= len(partials):
            # No progress. Merging is lossless where another pass would be endless.
            return _merge_partials(partials)
        partials = reduced
    return partials[0] if partials else Minutes()


def generate_minutes(utterances, config, *, llm=None, speaker_names=None):
    """Generate :class:`Minutes` from utterances, or ``None`` when dormant/failed.

    ``llm`` is a callable ``str -> str`` (prompt → JSON). When omitted it is built from
    ``[meeting] notes_model``; if no model is configured/available the result is ``None``.
    """
    if not utterances:
        return None
    if llm is None:
        llm = _build_llm(config)
    if llm is None:
        return None

    size = int(getattr(config, "notes_window_turns", 40) or 40)
    budget = window_budget_chars(
        int(getattr(config, "notes_ctx_tokens", 4096) or 4096),
        int(getattr(config, "notes_max_tokens", 1024) or 1024),
    )
    windows = window_turns(
        utterances, size, budget, line_overhead_chars(speaker_names)
    )
    partials, skipped = [], 0
    for w in windows:
        body = format_turns(w, speaker_names)
        try:
            window_minutes = _parse_minutes(llm(_WINDOW_PROMPT.format(body=body)))
        except Exception as exc:  # pragma: no cover - model-dependent
            skipped += 1
            log.warning("Minutes window failed (%s); skipping.", exc)
            continue
        # A window can fail by *returning*, and that is the failure the exception
        # handler above cannot see. llama.cpp clips `max_tokens` to whatever the
        # context leaves rather than raising, so the model is cut off mid-object; the
        # tolerant parser then finds no closing brace, yields `{}`, and hands back an
        # empty Minutes. Counted as a success it is a window of the meeting that
        # vanishes with no warning and no INCOMPLETE note --- the same silent loss the
        # note exists to prevent, arriving through the door the note does not watch.
        if is_empty(window_minutes):
            skipped += 1
            log.warning("Minutes window produced nothing usable; skipping.")
            continue
        partials.append(window_minutes)

    if not partials:
        return None

    # The reduce prompt is bounded by the same context as the map prompts, and for
    # the same reason -- see `reduce_partials`. Room is left for the boilerplate.
    minutes = reduce_partials(llm, partials, max(1, budget - len(_REDUCE_PROMPT)))

    if skipped:
        # Stamped on the FINAL minutes, not fed in as one more partial. The reduce
        # step is a language model asked to "deduplicate and keep the most important
        # points", and a warning about the summariser is exactly the kind of line it
        # drops --- so the disclosure would have survived only by luck, in the one
        # case where it must not. Minutes that quietly omit part of the meeting are
        # worse than none: nobody reading them can tell which part is missing, and
        # the transcript they would check against is the thing they were trying not
        # to read.
        log.warning(
            "%d of %d minutes windows failed; the notes are incomplete.",
            skipped, len(windows),
        )
        note = _GAP_NOTE.format(skipped=skipped, total=len(windows))
        minutes = replace(minutes, summary=f"{note}\n\n{minutes.summary}".strip())
    return minutes


def minutes_gbnf() -> str:
    """GBNF grammar constraining the minutes JSON shape (ADR-v2-128). Pure.

    Guarantees a parseable object with ``summary`` (string), ``decisions`` (string
    list), and ``action_items`` (``{owner, task}`` objects). ``per_speaker`` is
    *optional* so the same grammar validates both the per-window replies (which omit
    it) and the final reduce reply (which includes it). When llama.cpp is asked to
    decode against this grammar the output shape cannot drift, so the tolerant parser
    in :func:`_parse_minutes` only ever handles the (rare) ungrammared fallback path.
    """
    return (
        'root       ::= "{" ws "\\"summary\\":" ws string "," ws '
        '"\\"decisions\\":" ws strlist "," ws '
        '"\\"action_items\\":" ws actlist '
        '( "," ws "\\"per_speaker\\":" ws spklist )? ws "}"\n'
        'action     ::= "{" ws "\\"owner\\":" ws string "," ws "\\"task\\":" ws string ws "}"\n'
        'speaker    ::= "{" ws "\\"name\\":" ws string "," ws "\\"points\\":" ws strlist ws "}"\n'
        'strlist    ::= "[" ws ( string ( ws "," ws string )* )? ws "]"\n'
        'actlist    ::= "[" ws ( action ( ws "," ws action )* )? ws "]"\n'
        'spklist    ::= "[" ws ( speaker ( ws "," ws speaker )* )? ws "]"\n'
        'string     ::= "\\"" char* "\\""\n'
        'char       ::= [^"\\\\] | "\\\\" ["\\\\/bfnrt]\n'
        'ws         ::= [ \\t\\n]*\n'
    )


def render_minutes_md(minutes: Minutes) -> str:
    """Render :class:`Minutes` to Markdown. Pure."""
    out = ["# Meeting minutes", "",
           "> Auto-generated on-device — verify against the transcript.", ""]
    if minutes.summary:
        out += ["## Summary", "", minutes.summary, ""]
    if minutes.decisions:
        out += ["## Decisions", ""] + [f"- {d}" for d in minutes.decisions] + [""]
    if minutes.action_items:
        out += ["## Action items", ""]
        for a in minutes.action_items:
            owner = (a.owner + ": ") if a.owner else ""
            out.append(f"- [ ] {owner}{a.task}")
        out.append("")
    if minutes.per_speaker:
        out += ["## Per speaker", ""]
        for s in minutes.per_speaker:
            out.append(f"**{s.name}**")
            out += [f"- {p}" for p in s.points] + [""]
    return "\n".join(out).rstrip() + "\n"


# --- internals -------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (tolerates prose/fences)."""
    if not text:
        return {}
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        s = s[4:] if s.lower().startswith("json") else s
    start, depth = s.find("{"), 0
    if start < 0:
        return {}
    # String-aware, because a brace inside a *value* is not structure. Counting braces
    # blind closed the object at the first "}" in any summary that contained one:
    #
    #     {"summary": "the config needs a } here"}   ->  {}   (the whole minutes lost)
    #     {"summary": "use { to open a block"}      ->  {}
    #
    # Minutes of a technical meeting are exactly where a brace turns up in prose, and the
    # loss is silent -- `_parse_minutes` returns empty Minutes and the user gets a blank
    # page with no error.
    in_string = escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except ValueError:
                    return {}
    return {}


def _parse_minutes(text: str) -> Minutes:
    d = _extract_json(text)
    return Minutes(
        summary=str(d.get("summary", "") or "").strip(),
        decisions=[str(x).strip() for x in (d.get("decisions") or []) if str(x).strip()],
        action_items=[
            ActionItem(str(a.get("owner", "") or "").strip(), str(a.get("task", "") or "").strip())
            for a in (d.get("action_items") or [])
            if isinstance(a, dict) and str(a.get("task", "")).strip()
        ],
        per_speaker=[
            SpeakerNote(
                str(s.get("name", "") or "").strip(),
                [str(p).strip() for p in (s.get("points") or []) if str(p).strip()],
            )
            for s in (d.get("per_speaker") or [])
            if isinstance(s, dict) and str(s.get("name", "")).strip()
        ],
    )


def _minutes_to_json(m: Minutes) -> str:
    return json.dumps({
        "summary": m.summary,
        "decisions": m.decisions,
        "action_items": [{"owner": a.owner, "task": a.task} for a in m.action_items],
    }, ensure_ascii=False)


def _merge_partials(partials) -> Minutes:
    summary = " ".join(p.summary for p in partials if p.summary).strip()
    decisions, actions = [], []
    for p in partials:
        decisions += p.decisions
        actions += p.action_items
    return Minutes(summary=summary, decisions=decisions, action_items=actions)


def notes_unavailable_reason(
    config,
    *,
    utterances=None,
    model_exists=None,
    have_llama=None,
) -> str | None:
    """Why minutes cannot be generated, or None when they can. Pure by injection.

    `generate_minutes` returns ``None`` for FIVE different reasons and `yazses meeting
    notes` reported every one of them as::

        Notes are off or no local model is set. Enable `[meeting] notes` and set
        `[meeting] notes_model` to a local GGUF.

    For at least one of those states that advice is simply wrong: a meeting whose
    transcript holds no utterances produces no minutes no matter what is configured, and
    the message sends the user to change settings that were already correct. "Off or no
    model" also asks them to check two things when the command knows which.

    The checks are ordered by what the user would have to do first: an empty transcript
    cannot be fixed by configuration at all, a missing dependency cannot be fixed by a
    config key, and a path that does not exist cannot be fixed by setting the path again.

    ``model_exists`` and ``have_llama`` are injected so this is testable without a 4 GB
    GGUF or the `notes` extra; both default to a real probe. `find_spec` is used rather
    than an import because importing llama_cpp costs seconds and loads native code, which
    is far too much for a question asked before any work starts.
    """
    if utterances is not None and not utterances:
        return (
            "This meeting's transcript has no utterances, so there is nothing to "
            "summarise. Nothing is wrong with your notes settings."
        )
    if not getattr(config, "notes", False):
        return (
            "Meeting notes are off. Turn them on with `[meeting] notes = true`, and set "
            "`[meeting] notes_model` to a local GGUF."
        )
    model_path = str(getattr(config, "notes_model", "") or "")
    if not model_path:
        return (
            "`[meeting] notes` is on but `[meeting] notes_model` is empty — point it at a "
            "local GGUF file."
        )
    if have_llama is None:
        import importlib.util

        have_llama = importlib.util.find_spec("llama_cpp") is not None
    if not have_llama:
        return (
            "The local notes model needs llama-cpp-python, which is not installed. "
            "Install it with `uv sync --extra notes`."
        )
    if model_exists is None:
        from pathlib import Path

        model_exists = Path(model_path).is_file()
    if not model_exists:
        return f"`[meeting] notes_model` points at {model_path!r}, which is not a file."
    return None


def _build_llm(config):
    """Build a local-LLM callable from ``[meeting] notes_model``, or ``None`` if dormant."""
    if not getattr(config, "notes", False):
        return None
    model_path = getattr(config, "notes_model", "") or ""
    if not model_path:
        return None
    try:  # pragma: no cover - heavy, exercised only when a real model is configured
        from llama_cpp import Llama

        # The same number `generate_minutes` budgets its windows against. Two
        # constants for one context is how the budget silently stops matching the
        # model: raising `[meeting] notes_ctx_tokens` alone would have grown the
        # windows while llama.cpp stayed at 4096.
        n_ctx = int(getattr(config, "notes_ctx_tokens", 4096) or 4096)
        llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False)
        max_tokens = int(getattr(config, "notes_max_tokens", 1024) or 1024)

        grammar = None
        if getattr(config, "notes_grammar", True):
            try:
                from llama_cpp import LlamaGrammar

                grammar = LlamaGrammar.from_string(minutes_gbnf(), verbose=False)
            except Exception as exc:
                log.warning(
                    "GBNF grammar unavailable (%s); using tolerant JSON parse.", exc
                )

        def _call(prompt: str) -> str:
            kwargs = {"max_tokens": max_tokens, "temperature": 0.2}
            if grammar is not None:
                kwargs["grammar"] = grammar
            out = llm(prompt, **kwargs)
            return out["choices"][0]["text"]

        return _call
    except Exception as exc:  # pragma: no cover
        log.warning("Local notes model unavailable (%s); skipping minutes.", exc)
        return None
