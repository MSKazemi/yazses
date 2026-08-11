# ADR-v2-080 — Voice Fuzzy File Open

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-020-voice-grounded-rag]] (dictation memory vs filesystem), [[adr-v2-070-voice-window-management]], [[adr-011]]

## Context

Wave J research (#7) — "open the notes about the mortgage" → fuzzy (optionally semantic) match
over a local file index, launched via `xdg-open`/`open`/`start`. Removes the file-picker dance for
motor-impaired users. Distinct from Spoken Recall (which searches *dictation memory*) — this
targets the OS filesystem. Anchors: arXiv 2410.11843 (LLM-based semantic file system, AIOS),
EmbeddingGemma-300M (2025 on-device embedding model).

## Decision

Add an opt-in **Voice Fuzzy File Open**: `[fileopen] enabled=false, threshold=0.4`. Pure cores:
`fuzzy_rank(query, filenames)` scores each name by a blend of difflib sequence ratio and
content-token overlap (stopwords stripped), and `resolve_open(query, filenames, threshold)` returns
the top match above the threshold. Dependency-free (stdlib `difflib`). The EmbeddingGemma semantic
match for large libraries is deferred behind a `semanticfs` extra. OFF by default.

## Consequences

- Mouse-free file opening; pure ranking over a local index.
- Distinct from Spoken Recall (filesystem vs dictation memory).
- Privacy (ADR-011): index and embeddings local under `~/.local/share/yazses/`.
- Caveat: lexical fuzzy match only in the pure core → semantic match is the deferred embedding
  tier; off by default.
