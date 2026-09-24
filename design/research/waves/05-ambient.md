# SoA research — ambient / context-aware computing & memory augmentation (2024–2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** domain 5 of the 5-domain v2 vision sweep. Fed
[adr-v2-004](../../adr/adr-v2-004-context-primed-dictation.md) (Context-Primed Dictation) and
[adr-v2-005](../../adr/adr-v2-005-spoken-recall.md) (Spoken Recall). Related to
[adr-011](../../adr/adr-011.md) and [adr-012](../../adr/adr-012-self-improvement-loop.md)
(the encrypted, consent-first learning corpus this domain's argument leans on).
See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Where a "candidate feature" below never shipped, treat it as a research note, not a promise —
> check `yazses features` and the linked ADRs for what is actually built.

## Key SoA findings

- **Microsoft Recall = the cautionary tale for ambient lifelogging** — May 2024 unencrypted
  local SQLite; a "TotalRecall" exploit extracted everything trivially; rebuilt (VBS
  enclaves, AES-256-GCM, Hello JIT decrypt), relaunched opt-in April 2025. Advocates still
  say disable it. A strong signal that "record everything on screen" reads as surveillance
  even when local. [Wikipedia; DoublePulsar]
- **A local-first lifelog pioneer moved to cloud, then was absorbed** — Rewind.ai → Limitless
  (cloud + Pendant); Meta acquired Limitless, killed Pendant, ceased EU/UK service over
  regulatory risk. Staying on-device looked like a durable technical choice, not just a
  preference. [WinBuzzer — single source, unconfirmed]
- **Apple ~3B on-device foundation model + dev framework** — "small local LLM as OS
  primitive" became mainstream. [Apple ML Research; arXiv 2507.13575]
- **Ambient meeting transcription split cloud-vs-local** — Granola (cloud) vs 100%-local
  Meetily/OpenWhispr/Jamie/Superwhisper. Local transcription is a real category, but almost
  all of it is Apple-Silicon-centric. [Granola; Meetily; OpenWhispr]
- **Big-lab "universal assistant" designs are proactive + persistent memory, but cloud-bound** —
  Google Project Astra/Gemini Live: <300ms, cross-session memory, proactive tool use,
  learns from email/Drive. The opposite of an on-device-privacy posture. [DeepMind; Google I/O 2025]
- **Proactive context-aware agents are a named 2025 research task** — ContextAgent (NeurIPS 2025,
  arXiv 2505.14668) predicts *when* help is needed from sensory context. [+8.5%/+6.0% per
  abstract, unverified]
- **You may not need an LLM to decide *when* to act** — arXiv 2605.30152 and ProActor (ACL
  2026) separate the cheap timing/trigger decision from the heavy model — relevant to a
  lightweight always-on daemon. Field studies (CHI '25) found proactivity must be timed and
  dismissible or it annoys.
- **On-device LoRA + federated/DP maturing** — Apple federated tuning in production; FLoRA
  (NeurIPS 2024), DP-FedLoRA. Per-user adapters on personal data are feasible and privacy-
  tractable. [Apple; arXiv 2509.09097]
- **"AI-native memory" formalized beyond RAG** — Second Me (arXiv 2503.08102); Karpathy's
  "LLM Wiki" pattern (plain-text notes an agent reads/writes can beat RAG for a personal KB).
  Lightweight file-based personal memory looked credible.
- **Uncertainty signaling improves trust but LLMs are miscalibrated** — verbalized
  confidence can maximize trust, yet LLM confidence is systematically wrong. STT/Whisper
  exposes real token probabilities — a more honest uncertainty source. [ConfTuner arXiv
  2508.18847]
- **Human-AI co-writing favors "scaffolding," not autocomplete** — users want control and
  critical-thinking affordances, not silent generation: surface, don't substitute. [CHI
  2024; arXiv 2603.15777]

## Gaps / opportunities

- **The trust vacuum was unfilled** — Recall poisoned "screen recording"; Limitless showed
  cloud lifelogging is regulatorily fragile. Nobody owned "ambient personal memory that
  provably never leaves your machine" — the posture the market was retreating toward, and one
  an encrypted, no-telemetry corpus is positioned for.
- **Cross-platform on-device underserved** (most local tools are macOS-only).
- **Memory of *language*, not pixels** — what you said/wrote is higher-signal, smaller,
  less invasive than screenshots.
- **Proactivity without a wearable/camera** — window title, selection, clipboard, recent
  speech are cheaper already-consented signals; the "when" trigger can be non-LLM.
- **Honest uncertainty is easy here** — ASR gives real per-token probabilities for free.
- **Personalization loop half-built** — `yazses tune` and the corpus existed; the missing
  rung was a local LoRA/adapter (or cheaper prompt-mining, already sketched in `personalize/`).

## Candidate features considered in this domain

1. **Spoken Recall** — hold-to-talk query answered from your own encrypted dictation
   corpus, offline ("when did I dictate the API rotation plan?"). Recalls *your words*, no
   screenshots, no always-on mic. Risk: retrieval quality on a sparse corpus; a clear
   recall mode.
2. **Proactive Term Surfacing / Uncertainty Ink** — low-confidence Whisper tokens get a
   subtle overlay marker + personal-vocab candidate, from real token probabilities. Risk:
   visual noise → subtle, dismissible, off by default.
3. **Context-Primed Dictation** — read active window title + selection/clipboard to compose
   Whisper's `initial_prompt` (non-LLM trigger, zero sensors). Risk: reading window/clipboard
   is sensitive → strictly local, opt-in, never stored.
4. **Ambient Scratch Capture** — separate hotkey transcribes straight into the encrypted
   corpus without injecting ("note to self"), retrievable via Spoken Recall. Risk: scope
   creep → strictly push-to-talk.
5. **Nightly On-Device Adapter (gated on held-out WER)** — LoRA or n-gram prompt-mining
   from corrections; ship only if it beats base on a held-out slice. Risk: overfit → WER gate.
6. **Recall-Grounded Co-Writing** — while dictating, offer prior phrasing/definitions from
   your corpus (surface, don't substitute). Risk: flow interruption → keep it glanceable.

**Caveats, from the original sweep:** the Meta–Limitless acquisition rested on a single
trade-press source (unconfirmed); ContextAgent's figures came from an abstract, not a
verified result. Load-bearing primary sources were Apple ML Research, arXiv papers,
CHI/NeurIPS/ACL proceedings, DoublePulsar, and the Wikipedia Recall timeline. Citations
here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
