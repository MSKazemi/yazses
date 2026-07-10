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
from dataclasses import dataclass, field

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


def window_turns(utterances, size: int):
    """Split utterances into contiguous windows of at most ``size`` turns. Pure."""
    size = max(1, int(size))
    return [utterances[i:i + size] for i in range(0, len(utterances), size)]


_WINDOW_PROMPT = (
    "You are taking minutes for a meeting. Summarise this transcript excerpt. "
    "Return ONLY JSON: {{\"summary\": str, \"decisions\": [str], "
    "\"action_items\": [{{\"owner\": str, \"task\": str}}]}}.\n\nTranscript:\n{body}"
)
_REDUCE_PROMPT = (
    "Combine these partial meeting summaries into final minutes. Deduplicate and keep the "
    "most important points. Return ONLY JSON: {{\"summary\": str, \"decisions\": [str], "
    "\"action_items\": [{{\"owner\": str, \"task\": str}}], "
    "\"per_speaker\": [{{\"name\": str, \"points\": [str]}}]}}.\n\nPartials:\n{body}"
)


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
    windows = window_turns(utterances, size)
    partials = []
    for w in windows:
        body = format_turns(w, speaker_names)
        try:
            partials.append(_parse_minutes(llm(_WINDOW_PROMPT.format(body=body))))
        except Exception as exc:  # pragma: no cover - model-dependent
            log.warning("Minutes window failed (%s); skipping.", exc)

    if not partials:
        return None
    if len(partials) == 1:
        return partials[0]

    reduce_body = "\n\n".join(_minutes_to_json(m) for m in partials)
    try:
        return _parse_minutes(llm(_REDUCE_PROMPT.format(body=reduce_body)))
    except Exception as exc:  # pragma: no cover - model-dependent
        log.warning("Minutes reduce failed (%s); returning merged partials.", exc)
        return _merge_partials(partials)


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
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
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


def _build_llm(config):
    """Build a local-LLM callable from ``[meeting] notes_model``, or ``None`` if dormant."""
    if not getattr(config, "notes", False):
        return None
    model_path = getattr(config, "notes_model", "") or ""
    if not model_path:
        return None
    try:  # pragma: no cover - heavy, exercised only when a real model is configured
        from llama_cpp import Llama

        llm = Llama(model_path=model_path, n_ctx=4096, verbose=False)
        max_tokens = int(getattr(config, "notes_max_tokens", 1024) or 1024)

        def _call(prompt: str) -> str:
            out = llm(prompt, max_tokens=max_tokens, temperature=0.2)
            return out["choices"][0]["text"]

        return _call
    except Exception as exc:  # pragma: no cover
        log.warning("Local notes model unavailable (%s); skipping minutes.", exc)
        return None
