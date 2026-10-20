# Claude Code entrypoint

@AGENTS.md

This file intentionally contains no separate project rules. `AGENTS.md` is the canonical
YazSes instruction file for coding agents; this adapter exists only so Claude Code loads it
automatically at session start.

Do not run `/init` in a way that replaces this file with duplicated instructions. Update
`AGENTS.md` instead.
