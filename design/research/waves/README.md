# The v2 research waves

The v2 feature line (adr-v2-000 through the 120s, `design/adr/`) was not designed from a single
backlog — it came out of a repeating cycle: a state-of-the-art literature/product sweep, then a
ranked list of candidate features, then ADRs for the ones worth building. This directory is that
research trail, published so the ADRs have a visible "why" behind them instead of appearing
pre-formed.

Every file here is a **snapshot of the field on the date it was written**, not a live roadmap.
Where a candidate feature is discussed and never shipped, that is a research note, not a promise —
run `yazses features` and check the linked ADRs for what is actually built today. Citations have
not been re-run through
[`research/verify_refs.py`](../verify_refs.py) since the original sweep; treat arXiv IDs and
figures as pointers to chase, not confirmed facts.

| File | Fed | Domain |
|---|---|---|
| [01-voice-hci.md](01-voice-hci.md) | adr-v2-001 – 009 | Voice/speech HCI & dictation SoA |
| [02-agentic-os.md](02-agentic-os.md) | adr-v2-004 – 010 | On-device LLM agents & agentic OS |
| [03-ar-wearables.md](03-ar-wearables.md) | adr-v2-010, 011, 013 | AR/VR/wearable input |
| [04-accessibility.md](04-accessibility.md) | adr-v2-009, 012, adr-015 | Accessibility & assistive input |
| [05-ambient.md](05-ambient.md) | adr-v2-004, 005 | Ambient/context-aware computing & memory |
| [06-wave-d.md](06-wave-d.md) | adr-v2-014 – 024 | Wave D: translation, denoise, meeting scribe, RAG, silent speech |
| [07-wave-e.md](07-wave-e.md) | adr-v2-025 – 034 | Wave E: hallucination guard, math/code modes, wake-word |
| [08-wave-f.md](08-wave-f.md) | adr-v2-035 – 044 | Wave F: speaking coach, smart-paste, read-back voice |
| [09-wave-g.md](09-wave-g.md) | adr-v2-045 – 054 | Wave G: ITN, redaction, field-aware dictation, sign language |
| [10-wave-h.md](10-wave-h.md) | adr-v2-055 – 064 | Wave H: spreadsheet mode, temporal/unit conversion, self-repair |
| [11-wave-i.md](11-wave-i.md) | adr-v2-065 – 074 | Wave I: terminal safety gate, contextual biasing, diarized capture |
| [12-wave-j.md](12-wave-j.md) | adr-v2-075 – 084 | Wave J: confidence-gated re-ask, git choreographer, recording import |
| [13-wave-k.md](13-wave-k.md) | adr-v2-085 – 094 | Wave K: chorded shortcuts, undo/redo timeline, focus-class profiles |
| [14-wave-l.md](14-wave-l.md) | adr-v2-095 – 104 | Wave L: non-speech & prosodic interaction (Vocal Joystick, earcons) |
| [15-wave-m.md](15-wave-m.md) | adr-v2-105 – 114 | Wave M: minimal-bandwidth AAC & text intelligence (Vocal Morse) |
| [16-wave-n.md](16-wave-n.md) | adr-v2-115 – 124 | Wave N: structural editing, i18n, accessibility-output correctness |
| [17-diarized-recording-import.md](17-diarized-recording-import.md) | adr-v2-125, 126 | Wave O: diarized recording import (`yazses transcribe`) |
