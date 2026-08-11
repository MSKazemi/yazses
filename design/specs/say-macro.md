# Spec: Say-Macro — User-Programmable Voice Launcher

| Field | Value |
|---|---|
| **ID** | spec-say-macro |
| **Status** | Ready to implement |
| **Date** | 2026-06-14 |
| **Modules** | `src/yazses/commands/macros.py` (new), `commands/grammar.py`, `commands/dispatch.py`, `config.py`, `core/daemon.py` |
| **Vision card** | the Say-Macro vision card (internal) |
| **Evidence** | the 2026-06-14 ten-feature SoA dossier (internal) (Say-Macro block) |
| **Related** | ADR-004 (grammar-constrained tool calls), ADR-v04-001 (SLM inference), ADR-011 (offline-only, off-by-default) |

---

## Context

YazSes classifies every dictation burst through a two-tier pipeline:
`commands/grammar.py::classify()` (grammar.py:83) runs Tier-1 regex rules returning a
`CommandIntent` (`DICTATE` if nothing matches), then an optional Tier-2 `SLMRouter`.
`commands/dispatch.py::dispatch()` (dispatch.py:28) routes `DICTATE`→`injector.inject(text)`,
everything else→`injector.inject_key_sequence(...)`, with a raw-text fallback on error
(dispatch.py:45). The daemon wires this at `core/daemon.py:393` (classify) → `:417` (dispatch).

**Missing:** user-defined expansions. There is no way to say a short trigger and have YazSes emit
stored boilerplate prose or a code snippet. Voice macros are the highest-retention feature in the
clinical SR literature — **91% used / 72% very-helpful** among long-term users
[paper:PMC6051768, tier2, A] — and bounded-trigger speech-to-intent is where offline accuracy is
strongest (**>99% clean / 97% @9 dB**, Rhino 619-command grammar [bench:Picovoice, tier4, B]).
Prior offline tools (Talon, Caster, numen) ship trigger→expansion [repo:talonhub, tier7, B]; their
gap is **misfire gating** — none stop a trigger phrase that appears inside ordinary prose from
firing mid-dictation. Closing that gap is the whole job; the dossier verdict is **ready-now**.

## Current state (verified 2026-06-14)

| Element | Location | Relevant fact |
|---|---|---|
| `IntentType` enum | grammar.py:9 | members: `DICTATE`, `EDIT`, `NAVIGATE`, `TERMINAL`, `REFACTOR`. No `MACRO`. |
| `CommandIntent` dataclass | grammar.py:17 | fields `intent`, `action`, `args: dict[str,str]`, `raw_text`. |
| `classify()` | grammar.py:83 | `(text, profile="default", slm_router=None)`; regex loop then SLM fallthrough. |
| `dispatch()` / `_execute()` | dispatch.py:28 / :49 | switches on `intent.intent`; `DICTATE`→`inject(raw_text)`. |
| `CommandsConfig` | config.py:109 | has `profile`, `slm_*`, `lsp_*`. No macro fields. |
| daemon wiring | core/daemon.py:393, :417 | `classify(text, self._config.commands.profile)` then `cmd_dispatch(intent, injector)`. |

## Decision

Add a **user-defined macro table** matched as a new Tier-1 lookup that runs **before** the regex
grammar, with **whole-utterance exact match** as the default misfire gate.

### 1. Macro table — `macros.toml`

Macros live in a dedicated `macros.toml` in the YazSes config dir (sibling of `config.toml`), not
inline, so the table can grow, `yazses tune` can append learned triggers, and a missing file means
"feature dormant". `config.toml` carries only the switches.

```toml
# macros.toml
[[macro]]
trigger = "license header"
type = "text"
text = "# SPDX-License-Identifier: MIT\n# Copyright (c) ${date} ${author}\n"

[[macro]]
trigger = "try except"
type = "snippet"          # like text, but ${cursor} marks final caret position
snippet = "try:\n    ${cursor}\nexcept Exception as exc:\n    raise"

[[macro]]
trigger = "run my tests"
type = "actions"          # P2 — parsed but DISABLED in P1 (logged, never fires)
actions = [ { key = "ctrl+grave" }, { text = "uv run pytest -q" }, { key = "Return" } ]
```

### 2. Trigger matching — whole-utterance exact match (default)

A macro fires only when the **entire normalized burst equals the normalized trigger**.
Normalization (shared by trigger and burst): `lower()`, strip, collapse internal whitespace to
single spaces, strip trailing `.?!,`. So "license header" said alone fires; "add the license
header here" does not. This is the dossier's recommended gate and directly bounds the riskiest
LOFA (false fire inside prose). Per-macro opt-out `match = "substring"` is reserved for a later
phase, not in P1.

Ambiguity rule: trigger set is validated at load; **duplicate normalized triggers are rejected**
with a logged warning (first-defined wins), so match is deterministic.

### 3. Placeholders — fixed safe set, no code execution

Resolved at expansion time against a `MacroContext`:

| Placeholder | Value | Source |
|---|---|---|
| `${cursor}` | caret position marker (snippet only; first occurrence) | removed from text, yields caret offset |
| `${clipboard}` | current clipboard text | clipboard backend; `""` if unavailable |
| `${date}` | ISO date `YYYY-MM-DD` | injected clock (testable) |
| `${time}` | `HH:MM` | injected clock |
| `${author}` | `[macros] author` config value | config; `""` if unset |

Unknown `${...}` tokens are left **literal** (logged once at load). No shell/`$(...)` execution —
explicitly rejected (security + offline-safety).

### 4. Routing

`classify()` gains a `macro_table` param. Order inside `classify()`: empty-text guard →
normalize → **macro_table.match(normalized)** → regex rules → SLM. A match returns
`CommandIntent(intent=MACRO, action="expand", args={"text": <resolved>, "cursor_offset": <int>})`.
`dispatch._execute()` gains a `MACRO` branch: `injector.inject(text)`; if `cursor_offset > 0`,
`injector.inject_key_sequence(["Left"] * cursor_offset)`. On any error, existing raw-text fallback
applies. A `type="actions"` macro in P1 resolves to a no-op that logs "actions macros land in P2".

### 5. Config — `[macros]`, off by default (ADR-011)

```python
@dataclass
class MacrosConfig:
    enabled: bool = False          # master switch; False = fully dormant
    path: str = "macros.toml"      # relative to config dir, or absolute
    author: str = ""               # ${author} value
```

Added to the top-level config dataclass as `macros: MacrosConfig`. When `enabled is False`,
the daemon passes `macro_table=None` and nothing loads — zero footprint.

### 6. Loader — `commands/macros.py`

- `@dataclass(frozen=True) Macro`: `trigger_normalized`, `type`, `template`, kind-specific data.
- `MacroTable`: `{normalized_trigger: Macro}` + `match(normalized_text) -> Macro | None`.
- `load_macros(path) -> MacroTable`: parse TOML via stdlib `tomllib`; validate each entry
  (known `type`, non-empty trigger, dup detection); skip+log invalid entries (never raise on a bad
  single entry — a broken macro must not break the daemon). Missing file → empty table.
- `expand(macro, ctx) -> tuple[str, int]`: resolve placeholders → `(text, cursor_offset)`.
- `build_macro_table(config, config_dir) -> MacroTable | None`: returns `None` when
  `not config.macros.enabled` (mirrors the dormant `build_writer`/`build_cleaner` pattern).

## Acceptance criteria

1. With `[macros] enabled = false` (default), `classify()` behavior is byte-identical to today
   (regression: existing grammar/dispatch tests unchanged and green).
2. A `type="text"` macro whose trigger exactly matches the burst injects the resolved text once;
   `${date}`/`${time}`/`${author}`/`${clipboard}` resolve from the injected context; unknown tokens
   stay literal.
3. The same trigger spoken as part of a longer sentence does **not** fire the macro (whole-utterance
   gate) — it routes to `DICTATE`.
4. A `type="snippet"` with one `${cursor}` injects the full snippet then moves the caret left by the
   exact number of characters after the marker; a snippet with no `${cursor}` yields `cursor_offset == 0`.
5. A macro trigger that also matches a built-in regex rule (e.g. "save") resolves to the **macro**
   (macro lookup precedes regex) — documented and tested.
6. Duplicate normalized triggers are rejected at load with a warning; the surviving mapping is the
   first defined; loader never raises on one bad entry.
7. A `type="actions"` macro loads without error in P1 and is a logged no-op (does not inject keys).
8. Missing or empty `macros.toml` with `enabled = true` → empty table, no error, all bursts dictate.
9. `tomllib`-unparseable `macros.toml` → table loads as empty + one logged error; daemon still runs.
10. No new third-party dependency is added (stdlib `tomllib` + existing injector).

## Testing plan

| Layer | What | Count |
|---|---|---|
| Unit | `normalize()`, `MacroTable.match` (exact vs in-sentence), `expand()` placeholders + cursor offset, `load_macros` validation/dedup/bad-file | +12 |
| Unit | `classify()` with `macro_table`: precedence over regex, fallthrough to regex/SLM, dormant when `None` | +5 |
| Unit | `dispatch._execute()` MACRO branch: inject + Left×offset; actions no-op; error fallback | +4 |
| Integration | config `enabled=false` regression parity; `enabled=true` end-to-end burst→inject via a fake injector | +3 |

All offline, no models, no audio, no desktop — runnable in CI via `uv run python -m pytest`.

## Files reference

| File | Change |
|---|---|
| `src/yazses/commands/macros.py` | New: `Macro`, `MacroTable`, `MacroContext`, `load_macros`, `expand`, `build_macro_table`. |
| `src/yazses/commands/grammar.py:9` | Add `MACRO = "macro"` to `IntentType`. |
| `src/yazses/commands/grammar.py:83` | `classify(..., macro_table=None)`; macro lookup before regex loop. |
| `src/yazses/commands/dispatch.py:49` | `_execute()` gains `MACRO` branch (inject + caret Left). |
| `src/yazses/config.py:109` | New `MacrosConfig`; add `macros` field to top-level config + TOML parse. |
| `src/yazses/core/daemon.py:393` | Build table once at startup (when enabled); pass `macro_table` into `classify`. |
| `tests/test_macros.py` | New: unit + integration tests (above). |
| `docs/cli-reference.md` / config docs | Document `[macros]` + `macros.toml` format. |

## Rollback

Single feature, off by default. Revert the PR, or set `[macros] enabled = false`. No data
migration, no persisted state beyond the user-authored `macros.toml` (left in place, harmless when
disabled).

## Effort

~1h loader+expand, ~0.5h grammar/dispatch wiring, ~0.5h config, ~1.5h tests, ~0.5h docs ≈ **4h**.

## Out of scope

- OS/app **action chains** firing (type=actions) — parsed-but-dormant in P1, activated in P2 behind
  `require_macro_mode`.
- Substring / fuzzy / SLM-gated trigger matching — P1 is whole-utterance exact only.
- Learned-trigger auto-population via `yazses tune` — future, enabled by the dedicated-file design.
- Any shell/command substitution in expansions — permanently rejected.
