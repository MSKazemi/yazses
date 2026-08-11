# ADR-013 — On-Device LLM Dictation Cleanup (dual-path, parity)

**Status:** Accepted (2026-05-29)
**Context links:** [[adr-002]] (dual STT), [[adr-003]] (LLM backends), [[adr-004]] (grammar-constrained decoding), [[adr-011]] (zero telemetry)

## Context

Every leading commercial dictation tool (Wispr Flow, superwhisper, Aqua Voice) differentiates on LLM post-processing — reformatting raw dictation for punctuation, capitalization, tone, and structure. They all rely on **cloud** LLMs. A 2026 competitive/HRI research pass (an internal planning note, 24/25 claims adversarially verified) identified this as the one real feature gap for YazSes, and noted that Apple's shipping ~3B on-device model proves capable LLM cleanup is viable fully locally. Doing it on-device lets YazSes match the competition **and** preserve the ADR-011 zero-telemetry / offline stance — a differentiator, not just parity.

## Decision

Add optional LLM cleanup that reformats dictated text via user-selectable **modes**, fully on-device, **disabled by default** so default behavior is byte-identical.

**Dual-path, kept in parity until v1.0 GA.** YazSes is mid-migration from the Python v0.4/v0.5 daemon (what ships to users today) to the Rust v1.0 core (the future default, currently beta). Until v1.0 is generally available, the cleanup feature lives in **both**:

- **Rust v1.0 core** — `crates/yazses-llm/src/cleanup.rs`: a `CleanupEngine` that reuses the *already-loaded* `Arc<dyn LLMBackend>` (no second model), runs a free-form (`grammar: None`) completion only on the dictation (`type_text`) branch of `daemon.rs::process_utterance`. Config via `YAZSES_CLEANUP_*` env vars (the core has no TOML loader yet).
- **Python v0.4/v0.5 path** — `src/yazses/postprocess/llm_cleanup.py` (`LlmCleaner` / `build_cleaner`), wired in `core/daemon.py` on the dictation branch. Config via `[filters.disfluency]` (`llm_model` GGUF path, falling back to the `llm_endpoint` Ollama HTTP endpoint, `llm_system_prompt`, `llm_max_tokens`, `llm_timeout_ms`, `llm_min/max_length_ratio`).

Both share the same design: the same anti-hallucination INVARIANT system prompt, the same length-ratio and (Rust) token-preservation guards, the same hard fallback to the raw transcript on disabled/verbatim/empty/timeout/error/failed-guard.

## Alternatives rejected

- **Cloud LLM cleanup** — violates ADR-011 (zero telemetry, offline-by-default). Rejected.
- **Rust-only, treat Python as already-retired** — was the initial call, but Python is what *ships to users now*; a Rust-only feature reaches nobody until v1.0 GA. Rejected in favor of parity.
- **Ollama-only (no in-process GGUF)** — adds an external daemon dependency. The Rust path reuses the in-process backend; the Python path prefers a local GGUF and only falls back to Ollama. 
- **Replace the rule-based disfluency filter** — no; the deterministic disfluency filter remains a cheap pre-pass. LLM cleanup is an additional, opt-in mode layer on top.

## Anti-hallucination guardrails (why)

Dictation's core risk is an LLM that silently changes what you said. Mitigations, all enforced before accepting cleaned output (else fall back to the raw text):
- **Length-ratio guard** (`[0.5, 2.0]×`) — catches dropped content and runaway generation.
- **Token-preservation guard** (Rust) — every input token containing a digit, `_`, `/`, or `.` must survive as a substring; protects numbers, identifiers, URLs.
- **Tight INVARIANT prompt** — "reformat only, do not add/remove information, preserve proper nouns/numbers/identifiers/URLs."
- **Temperature 0**; bounded latency (timeout → raw text). Injection never blocks.

## Consequences

- Off by default → no behavior change for existing users until they opt in.
- The previously-unused `DisfluencyConfig.llm_enabled`/`llm_endpoint` Python stubs are now **load-bearing** (the Python path's config), so they must NOT be removed.
- Modes ship as: `verbatim` (default, no LLM call), `mechanics`, `email`, `notes`, `code-comment`, `formal`.
- Deferred: spoken mode-override, custom-mode authoring UX, tray toggle. Per-app mode resolution (Rust) is built but inert until a real `WindowDetector` is wired.
