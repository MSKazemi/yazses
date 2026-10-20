# Wave I — SoA research, 10 net-new features

**Date:** 2026 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-065](../../adr/adr-v2-065-terminal-command-safety-gate.md) through
[adr-v2-074](../../adr/adr-v2-074-diarized-conversation-capture.md). See the [waves index](README.md).

> A snapshot of the field, kept as the research record behind the ADRs it fed. Feature status
> should be checked against `yazses features` and the linked ADRs, not this note.

All on-device, off by default, distinct from the ~62 features existing before this wave (v2 +
Waves D-H). Ranked strongest-first. Anchors web-verified at the time (2025-2026); items #5-#10
rest on engineering substrates (AT-SPI2, WM IPC, CSL) rather than a single paper — flagged
honestly in the original sweep.

1. **Hard Contextual Biasing** — decode-time trie/WFST hotword boosting so rare names/jargon
   actually win (vs soft `initial_prompt`). Anchor: WCTC-Biasing (2506.01263), trie K-step
   (2509.09196), sherpa-onnx hotwords. Pure: `build_hotword_trie` + `bias_logits`/rescorer.
   Distinct from Context-Primed (soft prompt) + Personal Adapter (LoRA).
   → [adr-v2-069](../../adr/adr-v2-069-hard-contextual-biasing.md).
2. **Diarized Conversation Capture + Rename-by-Voice** — attributed per-turn Markdown, rename
   "speaker two" → "Alice". Anchor: pyannote community-1 / pyannote.audio 4.0. Pure:
   `SpeakerLabelMap` + `apply_rename` + `render_attributed_markdown`. Distinct from Meeting
   Scribe (bulk) + Multi-User Profiles (auth). → [adr-v2-074](../../adr/adr-v2-074-diarized-conversation-capture.md).
3. **Adaptive Latency Governor** — load-aware decode policy + speculative decoding (a distil
   draft model matching identical output ~2× faster). Anchor: HF spec-decode, distil-large-v3.5
   (2311.00430). Pure: `pick_policy(load, config)`. Distinct from Ghost-Ahead (pre-warm only).
   → [adr-v2-073](../../adr/adr-v2-073-adaptive-latency-governor.md).
4. **Per-Language Auto Model Switching** — LID first ~1-2s → hot-swap a language-specialized model.
   Anchor: Whisper LID + per-language distil/LoRA. Pure: `route_language(lid, registry)`.
   Distinct from Code-Switch (within-utterance) + Polyglot (fixed pair).
   → [adr-v2-072](../../adr/adr-v2-072-per-language-model-switching.md).
5. **Voice-Driven Document-Wide Find-and-Replace** — "replace every utilise with use". Anchor:
   AT-SPI2 EditableText. Pure: `parse_replace_command` + `to_editor_actions`. Distinct from
   Spoken Edit (last utterance only). → [adr-v2-068](../../adr/adr-v2-068-document-find-replace.md).
6. **Terminal Command Safety Gate** — hold `rm -rf`/`curl|sh` until spoken confirm when focus is
   a terminal. Pure: `classify_command_risk` ruleset + confirm state machine. Inspects command
   semantics before injection. → [adr-v2-065](../../adr/adr-v2-065-terminal-command-safety-gate.md).
7. **Structured-Markup Dictation** — speak Markdown/org tables and lists. Pure: `render_markup` +
   structure grammar. Distinct from Spreadsheet (drives an app) + Code/Math.
   → [adr-v2-067](../../adr/adr-v2-067-structured-markup-dictation.md).
8. **Voice Window/Workspace Management** — "move window left half", "workspace 3". Anchor:
   wmctrl/hyprctl/swaymsg. Pure: `parse_wm_command` + backend adapters. Distinct from Mouse
   Grid/Pilot. → [adr-v2-070](../../adr/adr-v2-070-voice-window-management.md).
9. **Spoken Regex Builder** — "four digits dash two digits" → `\d{4}-\d{2}`. Pure: `nl_to_regex`
   compositional grammar. Builds search patterns, not literal code.
   → [adr-v2-066](../../adr/adr-v2-066-spoken-regex-builder.md).
10. **Citation-by-Voice from local BibTeX/CSL** — "cite Vaswani 2017" → formatted citation,
    offline. Pure: `resolve_citation` fuzzy match + `format_citation`. Distinct from RAG
    (retrieve+generate). → [adr-v2-071](../../adr/adr-v2-071-citation-by-voice.md).

## Ship-now pure (do first)
#7 Structured-Markup, #6 Terminal Command Safety, #5 Find-and-Replace, #9 Spoken Regex —
cleanest fully dependency-free cores (pure text functions), each an accessibility/safety win a
cloud tool can't offer.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
