# Spec: Mid-Thought Undo — Spoken Buffer Revision

| Field | Value |
|---|---|
| **ID** | spec-mid-thought-undo |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/commands/` (new `edit_ops.py`), `commands/grammar.py`, `commands/dispatch.py`, `stt/filters/disfluency.py`, `inject/streaming.py`, `core/daemon.py`, `config.py` |
| **Vision card** | the Mid-Thought Undo vision card (internal) |
| **Related** | ADR-004 (streaming injector / correction-on-commit), ADR-v04-001 (SLM inference), ADR-011 (offline-only), ADR-013 (LLM cleanup guards), spec-say-macro (full-utterance gating pattern) |

---

## Context

YazSes already has the seed of this feature in two places. First, `stt/filters/disfluency.py::filter_transcript` runs a **three-pass** filter whose **Rule C** (`_apply_self_corrections`) already detects self-correction triggers (`"no wait"`, `"scratch that"`, `"never mind"`, `"forget that"`, `"strike that"`, `"delete that"` — `DisfluencyConfig.self_correction_triggers`) and rolls back the text from the last sentence boundary through the trigger phrase. This runs **inside a single transcript**, post-Whisper, before injection — it cannot reach text already typed in a previous burst, and it is invisible to the user (no command, no undo, no feedback). Second, `commands/grammar.py` already classifies `"delete the last word"`, `"delete the last N words"`, `"delete the last line"`, and `"undo (that)"` into `IntentType.EDIT` actions (`delete_words`, `delete_lines`, `undo`), and `commands/dispatch.py` routes those to `injector.inject_key_sequence(...)`.

What is missing is the unification of these into a **first-class, cross-burst, always-undoable buffer-revision layer**: a spoken "scratch that" that deletes the **last injected burst** (not just an intra-transcript span), spoken "delete the last word/sentence" applied to **YazSes-injected characters** we can account for, and — gated and optional — open-ended "no, make it X" rewrites. Today, "scratch that" said as its *own* burst (after the text it refers to already landed) does nothing useful: Rule C only sees the current transcript, which contains only the words "scratch that".

The dossier (internal, §8) verdict is **partial**: *"ship template 'scratch that' / last-burst delete now; gate arbitrary 'no, make it X' rewrites behind confidence + undo."* The evidence frames the split sharply: streaming self-repair detection is cheap (~3.1M params, ~35× smaller, ~80% latency cut, SOTA streaming-F1 on Switchboard [paper:arXiv2205.00620, tier1, A]) and batch reparandum removal is ~0.93 F1 [paper:arXiv2403.08229, tier2, B] — so **templates are reliable**. But open-ended spoken edits cap at **30% @1.3 s (small model) / 55% @7 s (large LLM)** [paper:arXiv2307.04008, tier1, A] — so **open-ended rewrite is wrong roughly half the time** and must never auto-apply. Fixed-template "Scratch That" is the only mature shipped pattern (Dragon/macOS/Talon [doc:Apple/Talon, tier6, C]); open-ended is a research frontier. A 1–3B Q4 GGUF parses an edit command in <1 s on CPU [bench:ggml-discussion, tier5, B] — fast enough, but parse-speed is not parse-correctness.

## Decision

Add a **buffer-revision layer** with a strict ownership rule — **YazSes may only delete or rewrite characters it injected itself**, tracked via the existing `StreamingInjector` char counter — split into a shippable Tier-1 template layer (P1) and a gated, opt-in, always-undoable open-ended rewrite (P2).

### 0. Buffer ownership (the safety invariant)

The daemon maintains a small **edit history** of YazSes-injected bursts for the current session:

```python
# core/daemon.py — in-memory, session-scoped, capped
@dataclass
class InjectedBurst:
    text: str                 # exactly what we injected (post-cleanup, with continuation prefix)
    char_count: int           # len(text) — characters we are responsible for
    monotonic: float          # time.monotonic() at inject
```

A bounded deque `self._edit_history: deque[InjectedBurst]` (maxlen `revision.history_depth`, default 5) is appended in `_on_hold_end` **only for dictation injections we performed** (the `is_dictation` branch, after the existing `injector.inject(text)` / `stream_injector.commit(text)`). Command injections (key sequences) are **not** recorded as deletable bursts.

**Invariant:** a revision command may delete at most the sum of `char_count` over the bursts it targets — never more. We never reach into the user's pre-existing text. If the edit history is empty (or the window expired), a revision command is a no-op that degrades to dictating its literal words (so "scratch that" with nothing to scratch types "scratch that", which the user can then delete — fail-visible, never destructive).

### 1. Tier-1 template layer (P1 — shippable)

A new `IntentType.REVISE = "revise"` and a small, **boundary-anchored** command set parsed in `commands/grammar.py`, evaluated *before* the existing EDIT rules so a revision phrase is never mis-typed as content:

| Spoken command (whole-utterance) | Action | Effect |
|---|---|---|
| "scratch that" / "delete that" / "strike that" / "never mind" / "forget that" | `scratch_last_burst` | Backspace over the **last** recorded `InjectedBurst` (within `revision.window_ms`). |
| "delete the last word" / "delete the last N words" | `delete_last_words` (`n` default 1) | Backspace over the last *N* word tokens of YazSes-injected text, spanning bursts only up to the ownership boundary. |
| "delete the last sentence" | `delete_last_sentence` | Backspace from the previous sentence boundary (`. ! ?`) within injected text to the end. |
| "undo that" / "undo" | `undo_revision` | Re-inject the text removed by the **most recent** revision (the undo stack, §3). |

These are matched only when the **entire normalised utterance** is the command (the Say-Macro full-utterance gate, reused), so dictating the literal prose *"and then I said scratch that to him"* does **not** fire — it contains other words and dictates normally. This directly addresses the riskiest LOFA (false deletion) from the vision card.

```python
# commands/grammar.py — new rules, added BEFORE the existing EDIT block,
# all anchored ^...$ so they must be the whole (normalised) utterance.
_add(r'^(?:scratch|delete|strike)\s+that$', IntentType.REVISE, "scratch_last_burst", [])
_add(r'^(?:never\s*mind|forget\s+that)$',    IntentType.REVISE, "scratch_last_burst", [])
_add(r'^delete\s+(?:the\s+)?last\s+sentence$', IntentType.REVISE, "delete_last_sentence", [])
# (existing delete-last-word / delete-last-N-words rules are re-tagged REVISE
#  and routed through the buffer-ownership path rather than blind key sequences.)
_add(r'^undo\s+that$', IntentType.REVISE, "undo_revision", [])
```

The existing intra-transcript **Rule C** in `disfluency.py` stays — it still handles *"send it Friday, scratch that, Thursday"* spoken as **one breath** (the trigger appears mid-transcript). The new layer handles the trigger spoken as **its own subsequent burst**, after the target text already landed. The two are complementary: Rule C is intra-burst, the REVISE layer is cross-burst.

### 2. Deletion mechanics (reusing `StreamingInjector`)

Deletion is expressed as **backspaces over a known character count** — the only injector-agnostic primitive (`InjectorBackend.inject_backspaces(count)` already exists, used by `StreamingInjector.cancel`). `dispatch.py` gains a `RevisionContext` (the edit history + undo stack, threaded from the daemon) and handles `IntentType.REVISE`:

```python
if intent.intent == IntentType.REVISE:
    removed = revision.apply(intent.action, intent.args, injector)
    # removed: str | None — text deleted (for the undo stack), or None if no-op
    if removed is None and revision.history_empty:
        injector.inject(intent.raw_text)   # fail-visible: type the literal words
    return
```

`RevisionContext.apply`:
- **scratch_last_burst:** pop the last `InjectedBurst`; `injector.inject_backspaces(burst.char_count)`; push the removed text onto the undo stack. Account for the continuation-prefix space (`postprocess/spacing.py`) so we delete exactly what we added.
- **delete_last_words(n):** walk back over injected text tokenwise up to the ownership boundary; backspace the spanned char count.
- **delete_last_sentence:** find the last sentence boundary within injected text; backspace to end.
- **undo_revision:** pop the undo stack; `injector.inject(removed_text)` to restore it (and re-push as a fresh `InjectedBurst`).

All deletions are capped by the ownership invariant (§0): never more backspaces than characters we injected. `revision.window_ms` (default 30 000, mirroring `injection.continuation_window_ms`) bounds how far back "the last burst" reaches; `0` disables cross-burst revision (intra-transcript Rule C still works).

### 3. Always-undoable (the undo stack)

Every revision (template or open-ended) pushes the removed/replaced text onto a bounded undo stack (`revision.undo_depth`, default 3). "undo that" pops it and re-injects. This is the safety floor required by the vision card: **no voice edit is irreversible**. Where the platform offers it, an optional `revision.use_os_undo` (default `false`) issues the editor's native undo key instead of re-injection — off by default because OS undo state is opase and may undo the user's own edits, violating the ownership invariant.

### 4. Tier-2 open-ended rewrite (P2 — gated, opt-in, never silent)

"no, make it X" / "actually, make that X" / "no, change it to X" — an open-ended reformulation of the last burst. **Off by default** (`revision.rewrite_enabled = false`). When enabled and a configured GGUF model is present, it reuses the **existing** `llama-cpp` stack behind `commands/slm_router.py` (ADR-v04-001) — no new model class, no new dependency. The flow, mirroring ADR-013's guarded-rewrite discipline:

1. `grammar.classify` detects the open-ended rewrite frame (whole-utterance `^(?:no,?\s*|actually,?\s*)?make (?:it|that) (.+)$` and siblings) → `IntentType.REVISE`, action `rewrite_last_burst`, arg `instruction`.
2. The daemon asks the SLM to apply `instruction` to the **last `InjectedBurst.text`**, with a constrained prompt ("Rewrite the following text per the instruction; output only the rewritten text"), reusing ADR-013's **length-ratio + token-preservation guards** to reject unsafe rewrites (numbers, proper nouns, URLs must survive unless the instruction explicitly changes them).
3. The router returns `(rewrite, confidence)`. If `confidence < revision.rewrite_confidence_threshold` (default 0.75, mirroring `commands.slm_confidence_threshold`) **or** a guard rejects → **no edit**; the daemon logs and either dictates the literal instruction or does nothing (config: `rewrite_on_low_confidence = "ignore" | "dictate"`, default `ignore`).
4. Above threshold, the rewrite is **never applied silently**. Two UX modes (`revision.rewrite_apply`):
   - `"undoable"` (default): apply immediately (backspace old burst, inject rewrite, push old text to undo stack), and emit an IPC `revision_applied` notification so the tray/CLI can flash "rewrote — say 'undo that' to revert". This is the lowest-friction safe mode: instant, but one word reverts it.
   - `"confirm"`: hold the rewrite, emit an IPC `revision_confirm` event showing old→new, and apply only if the **next burst** says "yes"/"confirm" (timeout → cancel). Highest safety, more friction.

The 30–55% correctness ceiling [paper:arXiv2307.04008, tier1, A] is the entire reason for this gating: at best the rewrite is right ~half the time, so it must be cheap to reject (confidence + guards) and cheap to revert (undo stack). It is **WATCH** in the vision card — shipped only behind the flag, never the default.

### Config schema (`config.py`, new `[revision]` section → `RevisionConfig` dataclass)

```python
@dataclass
class RevisionConfig:
    enabled: bool = False                 # master switch for the REVISE layer; False => dormant
    window_ms: int = 30000                # how far back "last burst" reaches; 0 = intra-transcript only
    history_depth: int = 5                # bounded edit history of injected bursts
    undo_depth: int = 3                   # bounded undo stack for "undo that"
    use_os_undo: bool = False             # use editor native undo vs re-injection (opaque state; off)
    # --- Tier-2 open-ended rewrite (P2; off by default) ---
    rewrite_enabled: bool = False         # gate open-ended "no, make it X"
    rewrite_model_path: str = ""          # GGUF path; "" reuses commands.slm_model_path if set
    rewrite_confidence_threshold: float = 0.75
    rewrite_apply: str = "undoable"       # "undoable" (apply+notify) | "confirm" (hold for yes)
    rewrite_on_low_confidence: str = "ignore"   # "ignore" | "dictate"
    rewrite_timeout_ms: int = 1500        # CPU parse budget; over budget => ignore (no edit)
```

All fields default to the dormant/safe value. Loading without a `[revision]` section is valid and changes nothing (consistent with every other config section and ADR-011). With `enabled = true` and `rewrite_enabled = false`, only the reliable template layer is active — the recommended shipping default.

### Integration points

| Surface | Change |
|---|---|
| `config.py` | Add `RevisionConfig`; wire into `Config` like `CommandsConfig` (default factory + `data.get("revision", {})`). |
| `commands/grammar.py` | Add `IntentType.REVISE`; add whole-utterance REVISE rules **before** the EDIT block; re-tag `delete_last_word(s)` as REVISE routed through the ownership path. |
| `commands/edit_ops.py` (new) | `InjectedBurst`, `RevisionContext` (edit history + undo stack), `apply(action, args, injector)` with the ownership cap; word/sentence boundary math over injected text. |
| `commands/dispatch.py` | Handle `IntentType.REVISE` via `RevisionContext`; fail-visible fallback to `inject(raw_text)` when history empty. |
| `stt/filters/disfluency.py` | **Unchanged behaviour**; Rule C remains the intra-transcript path. Document the split (intra-burst = Rule C, cross-burst = REVISE) in the module docstring. |
| `inject/streaming.py` | Reuse `inject_backspaces` / char-count tracking; no new public method needed (deletion is `inject_backspaces(known_count)`). |
| `core/daemon.py` | Maintain `self._edit_history` (deque) + undo stack; record dictation injections in `_on_hold_end` (after the existing inject/commit); thread `RevisionContext` into `classify`/`dispatch`; for P2, call the SLM rewrite path + emit `revision_applied`/`revision_confirm` IPC; record `intent_type="revise"` in the learning event (ADR-012). |
| `commands/slm_router.py` | **Reused** for the P2 rewrite parse — no new model; add a thin `rewrite(text, instruction) -> (str, float)` helper that reuses the loaded GGUF and ADR-013 guards. |
| `cli.py` / IPC | `revision_applied` / `revision_confirm` notifications; optional `yazses status` line showing edit-history depth. |
| `system/doctor.py` | Report whether `[revision]` is enabled, and (if `rewrite_enabled`) whether the GGUF model resolves. |

## Dependencies

**None new.** The template layer (P1) uses only stdlib + the existing injector probe (`inject/auto.py`, `inject_backspaces`). The optional open-ended rewrite (P2) reuses **`llama-cpp-python`** — already an optional dependency behind `SLMRouter` (ADR-v04-001) — and ADR-013's existing guard logic; it is not imported unless `revision.rewrite_enabled = true` *and* a model is configured. This honours the latest-stable policy (no version bumps required) and ADR-011 (no model pulled in by default). When the open-ended path is enabled, keep `llama-cpp-python` at its current stable release (it is already the project's SLM runtime — no separate pin introduced here).

## Phased plan

**P1 — template layer (the shippable core, dossier GO).**
- `RevisionConfig`, `IntentType.REVISE`, whole-utterance REVISE grammar rules, `commands/edit_ops.py` with `InjectedBurst` / `RevisionContext` / ownership cap.
- Daemon edit-history deque + undo stack; record dictation bursts; thread context into classify/dispatch.
- `scratch_last_burst`, `delete_last_words`, `delete_last_sentence`, `undo_revision` via `inject_backspaces` over owned char counts only.
- Ships the reliable, market-proven slice [paper:arXiv2205.00620; doc:Apple/Talon] with deletion bounded to YazSes-injected text and a working undo.

**P2 — gated open-ended rewrite (WATCH, opt-in).**
- `slm_router.rewrite()` helper reusing the loaded GGUF + ADR-013 guards; confidence + token-preservation gating.
- `rewrite_apply = "undoable" | "confirm"` UX paths; `revision_applied` / `revision_confirm` IPC.
- `yazses tune` may later propose rewrite few-shots from the corpus (ADR-012 hook).
- Stays behind `rewrite_enabled = false`; never the default while the 30–55% ceiling stands [paper:arXiv2307.04008].

## Testing approach (pytest)

- **Grammar gating (the critical suite):** parametrised — whole-utterance "scratch that" fires REVISE; "scratch that" *inside* longer prose (e.g. "I told him scratch that idea") does **not** fire and dictates normally (mirrors the 200-utterance false-delete kill test in the vision card); REVISE rules precede EDIT rules; "delete the last 3 words" parses `n=3`.
- **`RevisionContext` ownership (the safety suite):** scratch_last_burst deletes exactly `char_count` backspaces; deletion **never exceeds** total injected chars (assert backspace count ≤ owned chars across multi-burst histories); empty history → no-op → `inject(raw_text)`; window expiry → no-op; continuation-prefix space is accounted for (delete exactly what we injected).
- **Undo:** undo_revision re-injects the last removed text; undo stack bounded at `undo_depth`; undo after multiple deletes restores in LIFO order; `use_os_undo=true` issues the native undo key instead.
- **Cross-burst vs Rule C:** intra-transcript "X scratch that Y" still handled by Rule C (`disfluency.py` test unchanged); cross-burst "scratch that" as its own burst handled by REVISE — both covered, no double-deletion.
- **P2 rewrite (mocked `SLMRouter` via the `mocker` fixture):** below `rewrite_confidence_threshold` → no edit (`ignore` vs `dictate` honoured); guard rejection (number/proper-noun dropped) → no edit; above threshold + `undoable` → backspace+inject+undo-stack push + `revision_applied` IPC; `confirm` mode → holds until next-burst "yes"; over `rewrite_timeout_ms` → no edit. **rewrite disabled by default** (assert no model load when `rewrite_enabled=false`).

Target ≥90% coverage on `commands/edit_ops.py` and the new `grammar`/`dispatch` REVISE branches, per project gate.

## Risks and mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| **False edit** — a deletion fires when the user *dictated* the trigger words | inverse of [doc:Apple/Talon, tier6, C] | Whole-utterance / boundary-anchored matching (REVISE rules are `^...$`, must be the entire normalised burst); pre-registered kill test (>1% false-delete over 200 mixed utterances ⇒ require isolated-burst edit mode). |
| **Deleting the user's own text** — "last burst" overruns into text we didn't inject | [observed:codebase, inject/streaming.py] | Ownership invariant (§0): backspace count is capped by summed `InjectedBurst.char_count`; command injections are never recorded as deletable; empty history degrades to dictating the literal words. |
| **Open-ended rewrite is wrong ~half the time** — the 30–55% ceiling | [paper:arXiv2307.04008, tier1, A] | `rewrite_enabled=false` by default; confidence threshold + ADR-013 token-preservation guards reject unsafe rewrites; always-undoable application + IPC notification; `confirm` mode for highest safety. |
| **Un-undoable wrong rewrite** — a bad edit the user can't take back | [paper:arXiv2307.04008] | Bounded undo stack + "undo that" re-injection; open-ended rewrite does **not** ship unless undo is proven in primary targets (vision-card LOFA-5). |
| **Streaming detection degrades OOD vs batch 0.93 F1** | [paper:arXiv2403.08229, tier2, B] | Operate on the **full post-transcribe utterance** (YazSes's real case), not mid-stream tokens — the regime where reliability lives; no live-token speculation in P1. |
| **CPU parse cost for open-ended rewrite** | [bench:ggml-discussion, tier5, B] | `rewrite_timeout_ms` budget (default 1500); over budget ⇒ no edit; reuse the already-loaded GGUF (no extra load). |
| **OS-undo opacity** — native undo reverts the user's own edits | [observed:codebase] | `use_os_undo=false` by default; prefer re-injection (which respects the ownership invariant). |

## Consequences

**Positive:**
- Delivers the reliable, market-proven slice (template "scratch that" / last-burst & word/sentence delete) almost entirely from existing substrate — the Rule C logic, the EDIT grammar, and `StreamingInjector` char tracking — with no new dependency and a working undo.
- The ownership invariant (only delete what we injected) makes voice deletion *safe* in foreign apps, the gap Dragon/macOS/Talon's last-utterance model leaves under-specified [doc:Apple/Talon, tier6, C].
- The full-utterance gating and undo-stack scaffolding are reusable by Say-Macro, Punch-In, and any future voice-editing feature.
- Open-ended rewrite reuses the SLM stack and ADR-013 guards wholesale — when it matures past the 30–55% ceiling, the substrate is already in place.
- Fully offline, opt-in, dormant by default — honours ADR-011.

**Negative / trade-offs:**
- Whole-utterance-only matching means "scratch that" must be its own burst; mid-sentence reformulation is still the job of intra-transcript Rule C (a deliberate split — safety over convenience).
- A new `IntentType.REVISE` widens the intent enum; the learning corpus schema (ADR-012) gains a `revise` value (forward-compatible, additive).
- Cross-burst deletion depends on accurate `InjectedBurst` accounting; clipboard-paste injectors (which may not land char counts deterministically) degrade to current-burst-only deletion (documented; `yazses doctor` surfaces the active injector).
- Open-ended rewrite, even gated, can still surprise users at the 30–55% ceiling — hence it is off by default, always-undoable, and (optionally) confirm-gated; the friction is the point.

---
### Evidence tags
`[paper:arXiv2205.00620]` "Teaching BERT to Wait" streaming self-repair (~3.1M params, ~35× smaller, ~80% latency cut, SOTA streaming-F1 Switchboard) · `[paper:arXiv2307.04008]` TERTiUS interactive dictation (open-ended edits 30% @1.3 s / 55% @7 s) · `[paper:arXiv2403.08229]` Switchboard reparandum removal ~0.93 F1, streaming/OOD degradation · `[bench:ggml-discussion]` 1–3B Q4 GGUF edit-parse <1 s CPU · `[doc:Apple/Talon]` Dragon/macOS/Talon fixed-template "Scratch That" prior art · `[observed:codebase]` `stt/filters/disfluency.py` (Rule C), `commands/grammar.py` (EDIT rules), `inject/streaming.py` (`StreamingInjector`/`inject_backspaces`), `core/daemon.py::_on_hold_end`.
