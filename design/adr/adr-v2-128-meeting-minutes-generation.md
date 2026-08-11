# ADR-v2-128 — On-device Meeting Minutes (speaker-aware notes)

**Status:** Proposed (2026-07-10) · Wave P
**Context links:** [[adr-v2-127-live-meeting-mode]] (consumes its speaker-labelled transcript),
[[adr-013-llm-cleanup]] (reuses the offline llama.cpp plumbing), [[adr-v2-062-on-device-condense]]
(summarisation kin), [[adr-011]] (on-device, zero telemetry), [[adr-v2-126-cloud-escalation]] (deferred)

## Context

Meeting Mode (ADR-v2-127) produces a speaker-attributed transcript. The user wants **notes**, not a wall
of text: a summary, the decisions taken, and action items — attributed to who said what. This is a
distinct decision from capture/diarization because it introduces a **generative LLM step** with its own
cost, failure modes, and privacy surface.

Research (`design/meeting-mode/`) found on-device notes are realistic but **minutes of CPU compute, not
seconds**, and constrained:

- A one-hour transcript **exceeds a small model's context window** → naive "summarise the whole thing" fails.
- Free-form prompting yields inconsistent prose; **schema-constrained decoding** (GBNF / JSON) is needed for
  reliable structured minutes.
- Feasible CPU models (Q4): **Phi-4-mini**, **Qwen2.5-3B/7B**. YazSes already has offline llama.cpp plumbing
  in `postprocess/llm_cleanup.py` (ADR-013) — extend it, don't add a second LLM stack.
- Evaluation grounding exists (AMI, ICSI, QMSum meeting-summarisation corpora).

## Decision

Add an **opt-in, offline meeting-minutes generator** that turns ADR-127's speaker-labelled transcript into a
structured `notes.md`. OFF by default (`[meeting] notes=false`); dormant unless a local notes model is
configured. On-device only (ADR-011); no cloud (deferred to ADR-v2-126).

**New module `src/yazses/meeting/notes.py` (pure orchestration; LLM injected):**
- `generate_minutes(utterances, config, *, llm=None) -> Minutes`. Backend injected; when `llm=None`
  (no model configured) returns `None` and ADR-127 writes transcript-only. Fully testable with a fake LLM.
- **Turn-aware map-reduce** for long meetings: window the utterances (respecting speaker turns), summarise
  each window, then reduce the window-summaries into the final `Minutes`. Windowing is pure and unit-tested;
  only the per-window call touches the model.
- **Schema-constrained output** — a `Minutes` dataclass `{summary: str, decisions: list[str],
  action_items: list[ActionItem(owner, task)], per_speaker: list[SpeakerNote(name, points)]}` produced via
  GBNF/JSON-constrained decoding so the shape is guaranteed, not hoped for.
- **Render** to `notes.md` (human minutes) with the structured form also in `transcript.json`.

**Reuse:** the ADR-013 `postprocess/llm_cleanup.py::build_cleaner`/llama.cpp loader (shared model path,
same length/safety guards philosophy). Do not introduce a parallel LLM runtime.

**Config — extend `MeetingConfig`:** `notes=False`, `notes_model=""` (path to a local GGUF; empty = dormant),
`notes_window_turns=40` (map-reduce window size), `notes_max_tokens=1024`, `notes_language=""`
(→ transcript language). Reuse `[filters.disfluency]` llama.cpp settings where they overlap.

**CLI:** surfaced through ADR-127 — `yazses meeting start --notes`, `yazses meeting notes <id>`,
`yazses meeting relabel <id> --notes`. Notes generation shows a "generating minutes…" progress line
(it is slow) and is always re-runnable against a stored transcript.

**Extra:** a `notes` extra pulling the llama.cpp binding already used by ADR-013 (if not in base). Model
weights are user-supplied/downloaded on demand, never bundled.

## Consequences

- Turns the raw meeting transcript into the artifact users actually want (summary + decisions + action
  items + per-speaker), fully offline — an unoccupied niche for a local tool (cloud tools do this; local
  ones mostly stop at "Speaker N: text").
- Reuses the ADR-013 LLM stack → **no second inference runtime**; base install unchanged (notes behind an
  extra + a user-supplied model).
- Pure windowing/reduce/render (injected fake LLM) unit-test with **zero model downloads**; `llm=None`
  degrades to transcript-only. CI stays green.
- On-device, zero-telemetry (ADR-011): the transcript never leaves the machine; no cloud summarisation.
- **Caveats (carried honestly):** notes are **minutes of CPU compute**, not interactive — always async,
  always re-runnable; small local models hallucinate/omit → constrained JSON + map-reduce reduce but do
  not eliminate this, so notes are labelled "auto-generated, verify against transcript"; map-reduce can
  blur cross-window context on very long meetings; quality is model-dependent (Phi-4-mini/Qwen2.5-3B
  baseline). **Cloud escalation** for higher-quality minutes is deferred to ADR-v2-126.
