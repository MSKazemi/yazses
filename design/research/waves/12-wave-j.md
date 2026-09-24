# Wave J — SoA research, 10 net-new features

**Date:** 2026 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-075](../../adr/adr-v2-075-phonetic-spelling-mode.md) through
[adr-v2-084](../../adr/adr-v2-084-crowd-proof-dictation.md). See the [waves index](README.md).

> A snapshot of the field, kept as the research record behind the ADRs it fed. Feature status
> should be checked against `yazses features` and the linked ADRs, not this note.

All on-device, off by default, distinct from the 72 features existing before this wave (v2 +
Waves D-I). Ranked strongest-first; anchors web-verified at the time (2025-2026). Two
independent research streams converged on the #1 flagship (confidence-gated re-ask).

1. **Confidence-Gated Re-Ask** *(flagship)* — hold only the low-confidence span and interactively
   resolve it (A/B confusable disambiguation or "say that word again"), patching the placeholder.
   Anchor: arXiv 2503.15124, 2502.13446, 2402.06509. Pure: `low_confidence_spans(tokens, logprobs,
   thresh)` + `confusion_set` + `parse_choice`. Distinct from Confidence Ink (marks only; this
   repairs). faster-whisper already emits token log-probs. → [adr-v2-077](../../adr/adr-v2-077-confidence-gated-reask.md).
2. **Phonetic Spelling Mode** — NATO words → exact characters ("capital alpha bravo double lima" →
   "Abll") for passwords/codes/IDs. Anchor: Picovoice NATO engine (user-value, weak novelty). Pure:
   `spell_parse(words)` dict+modifier grammar. Distinct from Entity ITN (normalizes prose).
   → [adr-v2-075](../../adr/adr-v2-075-phonetic-spelling-mode.md).
3. **Verbatim ⇄ Autoformat Live Toggle** — reserved phrases flip a per-burst flag freezing/
   restoring ITN+punctuation+reflow mid-burst. Anchor: Azure "Display text formatting", arXiv
   2505.24229. Pure: `VerbatimGate.apply` + `detect_mode_command`. A runtime ITN switch.
   → [adr-v2-078](../../adr/adr-v2-078-verbatim-autoformat-toggle.md).
4. **Crowd-Proof Dictation (target-speaker extraction)** — reconstruct the enrolled voice out of
   babble pre-STT. Anchor: LGTSE arXiv 2508.19583, SpeakerBeam-SS 2407.01857. Pure: enrollment +
   overlap-add + A/B mix (numpy); Conv-TasNet/SSM model deferred. Rescues Cocktail Filter.
   → [adr-v2-084](../../adr/adr-v2-084-crowd-proof-dictation.md).
5. **Voice Git Choreographer** — structured git argv grammar (never free-form shell); a
   reversibility classifier gates destructive ops behind confirm + always speaks the undo.
   Anchor: NaSh arXiv 2506.13028, 2510.06445. Pure: `build_git_argv` + `reversibility` +
   `undo_hint`, no deferred backend. Distinct from Terminal Safety Gate (git-porcelain intent
   build vs generic matching). → [adr-v2-076](../../adr/adr-v2-076-voice-git-choreographer.md).
6. **Self-Learning Correction Dictionary** — mine repeated ASR-output→edit pairs (via
   `EditWatcher`) into a boundary-guarded auto find→replace. Anchor: arXiv 2406.07589. Pure:
   `mine_substitutions` + `apply_corrections`. Distinct from Phonetic Corrector (pronunciation) /
   `tune` (config). → [adr-v2-079](../../adr/adr-v2-079-self-learning-correction-dictionary.md).
7. **Voice Fuzzy File Open** — "open the notes about the mortgage" → fuzzy/semantic match over a
   local file index, `xdg-open`. Anchor: arXiv 2410.11843, EmbeddingGemma-300M. Pure: `fuzzy_rank`
   + `resolve_open`; semantic extra deferred. Distinct from Spoken Recall (dictation memory).
   → [adr-v2-080](../../adr/adr-v2-080-voice-fuzzy-file-open.md).
8. **Voice Jump-to-Symbol / Structural Hop** — "jump to function tokenize", "go to line 240" →
   editor motion. Anchor: Cursorless, ACM CUI 2023 DOI 10.1145/3571884.3597130. Pure:
   `resolve_target` + `fuzzy_pick` + `plan_motion`; LSP symbol list deferred. No camera/grid.
   → [adr-v2-081](../../adr/adr-v2-081-voice-jump-to-symbol.md).
9. **Recording Import (batch transcription)** — `yazses transcribe <file>` → .txt/.srt offline at
   tens-hundreds× RT. Anchor: NVIDIA Parakeet-TDT-0.6B-v2 (RTFx~3386, 2025). Pure: discovery +
   chunking + SRT/VTT writer + timestamp merge; Parakeet backend deferred (faster-whisper
   fallback). Distinct from live Meeting Scribe/Diarize (pre-recorded batch).
   → [adr-v2-083](../../adr/adr-v2-083-recording-import.md).
10. **Spoken Shell Pipeline Builder (dry-run first)** — speak stages → render `ls | grep error |
    wc -l` as text, never execute until "run it". Anchor: NaSh 2506.13028, NL2SH NAACL 2025
    2502.06858. Pure: `parse_stages` + `render_pipeline` (`shlex.quote`) + `dryrun_wrap`; NL2Bash
    SLM deferred. Distinct from Terminal Safety Gate (constructs vs classifies).
    → [adr-v2-082](../../adr/adr-v2-082-spoken-shell-pipeline-builder.md).

## Ship-now pure (do first)
#2 Phonetic Spelling (pure dict), #3 Verbatim⇄Autoformat (state machine), #1 Confidence Re-Ask
gate (pure log-prob math), #5 Git Choreographer (pure rule table, no deferred backend).

Runner-ups considered and cut at the time: Spoken Diff/Patch Review, Flow Dictation (Kyutai STT),
Intonation Punctuation (emotion2vec+), Ask-This-Clip (Voxtral), Spoken Shortcut Coach.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
