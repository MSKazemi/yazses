# ADR-v2-051 — Screen-Grounded Dictation

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-004-context-primed]] (LSP source), [[adr-v2-020-voice-rag]] (doc index), [[adr-011]]

## Context

Wave G research (#3) — bias Whisper's `initial_prompt` from on-screen text so names visible on
screen transcribe correctly the first time (a chat with "Aoife"/"Nguyễn", a variable
`useAuthContext` in a browser IDE, a PDF form label). Works in *any* app, including ones with no
LSP and no editor. Anchors: GOT-OCR2.0, dots.ocr, PaddleOCR-VL-0.9B (arXiv 2507.05595, CPU-viable).

Distinct from Context-Primed (LSP source) and Voice-RAG (document index) — this harvests terms
from *whatever is rendered on screen*, the only source that works for non-accessible/non-editor
apps, and something no cloud dictation tool can do (it can't see your screen).

## Decision

Add an opt-in **Screen-Grounded Dictation**: `[screengrounded] enabled=false, max_terms=32`. The
pure core `harvest_terms(sources, max_terms)` + `extract_terms(text)` mine proper-noun/identifier
tokens (Capitalized, camelCase, snake_case, ACRONYM) from visible text sources (accessibility
tree nodes, clipboard/selection) and merge them into `_effective_initial_prompt`. This first tier
ships with **no new dependency**; the OCR VLM pixel path is deferred behind a `screenocr` extra.
OFF by default.

## Consequences

- Context in any app, including non-accessible ones (via the deferred OCR tier).
- Pure term extraction/dedup/cap → fully testable with no screen.
- Privacy (ADR-011): terms harvested in-RAM for one hold, never stored/sent (mirrors the Gaze
  no-frame-storage rule).
- Caveat: over-biasing could hurt general dictation → the term list is capped and off by default.
