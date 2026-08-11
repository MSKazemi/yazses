# ADR-v2-082 — Spoken Shell Pipeline Builder (dry-run first)

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-065-terminal-command-safety-gate]] (classifies formed cmd vs builds pipeline), [[adr-v2-076-voice-git-choreographer]], [[adr-011]]

## Context

Wave J research (#10) — speak pipeline stages ("list files, pipe to grep error, pipe to word
count") → the daemon *renders* `ls | grep error | wc -l` into the terminal as text without
executing; "dry run" wraps a mutating tool with its native `--dry-run`/`-n`; nothing runs until
"run it". Distinct from the Terminal Command Safety Gate, which classifies an *already-formed*
command — this *constructs* the pipeline from spoken stages and defaults to preview. Impossible in
cloud dictation. Anchors: NaSh (arXiv 2506.13028), NL2SH (Westenfelder et al., NAACL 2025, arXiv
2502.06858).

## Decision

Add an opt-in **Spoken Shell Pipeline Builder**: `[shellpipe] enabled=false`. Pure cores:
`parse_stages(text)` splits on "pipe to"/"then"/","; `render_pipeline(stages)` maps each stage to a
command (a curated read-only vocab + `grep/filter <quoted arg>` via `shlex.quote`) and joins with
`|`, returning `None` if any stage is unknown; `dryrun_wrap(pipeline)` swaps a mutating leading
tool (`rm`/`rsync`/`mv`/`git clean`) for its dry-run form. Dependency-free — it only ever renders
text. The NL2Bash-tuned SLM for free-form fallback is deferred. OFF by default.

## Consequences

- Constructs pipelines from speech and defaults to preview — nothing runs without explicit "run it".
- `shlex.quote` on interpolated args removes injection risk.
- Distinct from the Terminal Safety Gate (builds vs classifies).
- Privacy (ADR-011): pure string assembly; nothing executes here.
- Caveat: curated stage vocab → free-form stages need the deferred SLM; unknown stages abort to
  `None`. Off by default.
