# SoA research — on-device LLM agents & agentic OS (2024–2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** domain 2 of the 5-domain v2 vision sweep. Fed
[adr-v2-004](../../adr/adr-v2-004-context-primed-dictation.md) (Context-Primed Dictation),
[adr-v2-005](../../adr/adr-v2-005-spoken-recall.md) (Spoken Recall),
[adr-v2-006](../../adr/adr-v2-006-spoken-mcp.md) (Spoken MCP),
[adr-v2-007](../../adr/adr-v2-007-atspi-voice-pilot.md) (AT-SPI Voice Pilot),
[adr-v2-009](../../adr/adr-v2-009-personal-adapter.md) (Personal Adapter), and
[adr-v2-010](../../adr/adr-v2-010-gaze-routed-dictation.md)'s `needs_confirm` policy.
See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Where a "candidate feature" below never shipped, treat it as a research note, not a promise —
> check `yazses features` and the linked ADRs for what is actually built.

## Key SoA findings

- **Apple shipped a ~3B on-device model with a public API** — Foundation Models
  framework (iOS/macOS 26, Sept 2025): 2-bit QAT, guided generation (constrained
  decoding into Swift structs), tool calling, offline. [Apple Newsroom; Apple ML
  Research tech report 2025]
- **Apple's LoRA hot-swap** is the reference design for local multi-task
  personalization: one frozen ~3B base + many task LoRA adapters (≤~1% weights)
  hot-swapped without recompilation. [Predibase; Orion/ANE paper]
- **Microsoft Phi Silica** — NPU-resident SLM with a public Windows App SDK API
  (Click-to-Do, summarization, parts of Recall); Windows now has native OS-level
  **MCP** support. [Windows Dev Blog Build/Ignite 2025]
- **Google Gemini Nano** to third-party apps via ML Kit GenAI on AICore
  (request-isolated, no retention); Prompt API alpha Oct 2025. [Android Dev Blog]
- **Open small models are agent-capable on CPU/consumer GPU**: Phi-4-mini (3.8B,
  ~3GB Q4), Gemma 3 4B (vision + 140 langs), **Qwen3 designed for agents/tool
  calling**. Caveat: Gemma 3 tool-calling weaker than Llama/Mistral/Qwen. [secondary]
- **llama.cpp GBNF grammars** give fully-local deterministic tool-calling (schema
  cannot be violated); `json-schema-to-grammar` + `LlamaGrammar`. [llama.cpp README]
- **MCP became the industry-standard agent tool interface** in ~12 months (Anthropic
  Nov 2024 → OpenAI, Google DeepMind → Linux Foundation; Nov 2025 spec). [MCP blog]
- **Computer-use/GUI agents work but are below humans on real OS tasks** — OSWorld
  human baseline ~72–84%; frontier ~low-70s%. Long-horizon degrades sharply past
  ~50 steps. [OSWorld; OSWorld-Human arXiv 2506.16042] (highest 2026 figures unverified)
- **Accessibility-tree control beats pixel/vision for local agents** — AT-SPI/UIA/
  macOS AX give exact element IDs, ms actions, nothing leaves machine; historically
  underused. [UFO2 arXiv 2504.14603]
- **Fully-local RAG "second brain" is commodity** — sqlite-vec (SIMD, binary
  quantization + Hamming) handles 100k+ docs, zero infra; Khoj reference app. [sqlite-vec]
- **On-device fine-tuning moved phone-native** — MobileFineTuner/MobileRAG show
  local LoRA + adapter storage. [arXiv 2512.08211, 2507.01079]
- **Context management, not model size, is the on-device bottleneck** for multi-step.
  [arXiv 2511.03728]

## Gaps / opportunities (privacy-first, local, voice-driven agent)

- **Voice is the missing input modality in the agentic-OS wave** — everyone shipped
  on-device *text* SLM APIs + MCP hosts, but flagship demos are text/screenshot.
  Hands-free hold-to-talk into local tool calls was underserved; offline STT + hotkey +
  injection is the hard part most tools don't own.
- **AT-SPI grounding is cited as superior yet barely shipped, especially on Linux** —
  a defensible, privacy-clean approach (structured perception, ms latency, no screenshots).
- **Local structured tool-calling is trivial now but under-exploited for voice.**
- **"Recall-style" screen memory is a privacy lightning rod; a voice-annotated,
  opt-in, encrypted alternative was open space** — this project already had the
  encrypted, consent-first corpus ([adr-011](../../adr/adr-011.md)/[adr-012](../../adr/adr-012-self-improvement-loop.md))
  that Recall lacked.
- **On-device LoRA personalization proven by Apple, absent from open voice tools.**
- **Long-horizon reliability unsolved (<50-step cliff)** — a reason to stay narrow:
  short, verifiable, human-in-the-loop voice actions sidestep the failure mode.

## Candidate features considered in this domain

1. **Voice-to-Tool ("Spoken MCP")** — speak intent → local SLM emits GBNF-constrained
   MCP tool call executed against local MCP servers; fully offline. Risk: misfire →
   mandatory spoken confirm + per-tool allowlist.
2. **AT-SPI Voice Pilot** — "click Save", "focus terminal" resolved against the live
   accessibility tree; no screenshots, ms latency, Linux-first. Risk: broken trees in
   Electron/terminals → fall back to keystrokes.
3. **Encrypted Spoken Recall** — every dictation/command optionally a searchable,
   timestamped, app-tagged memory in the existing encrypted corpus (sqlite-vec). Risk:
   privacy perception → strictly opt-in, honor redaction/retention.
4. **Context-Grounded Commanding** — resolve deictic commands ("rename *this*
   function") via active editor LSP symbols already fed to `initial_prompt`. Risk:
   Neovim-first → degrade to dictation.
5. **Personal Command Adapter** — opt-in nightly local LoRA on the corpus so the intent
   classifier learns your phrasings; gated on held-out win. Risk: overfit →
   hard promotion gate + base fallback.
6. **Verify-Before-Act Voice Loop** — for 2–5 step actions the SLM speaks/overlays the
   plan and executes on "go", to work around the long-horizon cliff. Reuses TTS +
   overlay. Risk: friction → configurable step threshold.

**Verification notes, from the original sweep:** the Apple/MS/Google/MCP/sqlite-vec/
llama.cpp/Khoj facts came from primary sources and were treated as solid; specific SLM
benchmark/VRAM numbers came from secondary roundups and were treated as directional only;
the highest 2026 OSWorld figures (82–85%) were flagged as unverified, trusting only the
~low-70s% frontier and the official leaderboard. Citations here have not been re-verified
against [`research/verify_refs.py`](../verify_refs.py).
