# Research: streaming endpointing, thinking pauses and safe text delivery

**Issue:** [#796](https://github.com/MSKazemi/yazses/issues/796), parent [#787](https://github.com/MSKazemi/yazses/issues/787)  
**Snapshot:** YazSes `main` at `fa8159d89aac73bc556bfb994a7defe0fb61df0c`, inspected 2026-11-03  
**Status:** Research finding and design recommendation; **not a new implementation authorization**  
**Scope:** desktop dictation, LocalAgreement partials, release/endpoint semantics, staged mode, and external text-injection ownership

## Executive decision

**Adopt a pure, offline, synthetic replay and safety-gate specification now; defer any streaming rollout or default change; reject silence-triggered completion of a physical hold-to-talk burst.** A proposed, **unaccepted** ADR is [here](2026-11-03-proposed-adr-streaming-delivery-boundary.md); the testable contract is [here](../specs/streaming-commit-replay-protocol.md). The synthetic fixture corpus is [here](fixtures/streaming-replay-v1.jsonl).

The main problem is **not choosing a faster endpointer**. YazSes already uses the correct end-of-turn signal for a held key: actual key release. The safety risk is allowing provisional text to cross into an external app before the definitive transcript has survived classification, filtering, target checks, and (where configured) staged review. LocalAgreement confirmation is *model stability*, **not** permission to mutate a user's document.

### Evidence labels

- **[C] Code-inspected:** current source/tests at the exact YazSes snapshot above. An inferred failure is not a reproduced desktop incident.
- **[H] Historical recorded measurement:** published YazSes measurements; not re-executed in this study.
- **[P] Primary external source:** linked upstream repository at a named commit, or original paper. An upstream number is never a YazSes benchmark.
- **[U] Unknown/unverified:** requires deterministic replay, hardware, or user evaluation.

## 1. Existing pipeline and what it actually guarantees

| Seam | Observed at the pinned snapshot | Implication |
|---|---|---|
| `stt/streaming.py` | Whole accumulated audio is decoded every `partial_interval_ms` (default 300); LocalAgreement-2 computes a common **character** prefix of successive hypotheses. A single pending delta slot is consumed by `get_partial()`. `commit()` decodes final audio again. [C] | The "stable" prefix can still change on a later hypothesis; a slow consumer can miss overwritten deltas. CPU work grows with an untrimmed buffer. |
| `inject/streaming.py` | Partial injection, final replacement and cancel share a lock; commit seals the injector against late partials; final replacement uses `shift+Left` repeated by the counted number of injected Python characters. [C] | Fixes the previously reported ordering race **inside this wrapper**; not an atomic target-app transaction and not a guarantee about Unicode cursor units, focus, selection semantics or partially successful OS calls. |
| `core/daemon.py::_on_hold_start` | With streaming enabled and not in dedicated command mode, it starts the partial-injection poll, **regardless of staged mode**. [C] | A staged prompt may become visible in the target app before review. |
| `core/daemon.py::_on_hold_end` | The poll stop is signalled; a one-second join is advisory; the injector's seal/lock is the concurrency boundary. The full final text passes through filters/guards and optional staging. [C] | Partial text can already be in the editor when a later guard refuses or stages the utterance. |
| `staged/buffer.py` | Staged review is an opt-in pure buffer; explicit nonspoken commit is default, while spoken commit is separately opt-in. [C] | Its promise is "review *before* anything is typed", which conflicts with uncontrolled live partial injection. |
| `audio`, `autostop` and `hesitation` | Physical hold-to-talk ends on release. Automatic silence/hesitation endpointing applies to separately enabled hands-free turns, not ordinary held-key turns. [C] | A long deliberate thinking pause is not a completion signal for hold-to-talk. |

Source anchors: [streaming engine](../../src/yazses/stt/streaming.py), [streaming injector](../../src/yazses/inject/streaming.py), [daemon](../../src/yazses/core/daemon.py), [staged buffer](../../src/yazses/staged/buffer.py), [agent use case](../../docs/use-cases/voice-input-for-ai-agents.md), [hesitation ADR](../adr/adr-v2-101-hesitation-hold-endpointing.md), and [Ghost Ahead spec](../specs/ghost-ahead.md).

### 1.1 High-priority code-level failure: staged + live-streamed partials

At `daemon.py` lines 3955–3976, the partial injector is constructed when `[streaming] enabled` regardless of `[staged] enabled`. At 6503–6527, the poll loop forwards partial deltas directly to that injector. At 5199–5209, the normal `_stage_or_commit` result of `None` returns from `_on_hold_end` without first calling `stream_injector.cancel()`. The final replacement call at 5283–5285 is never reached in that branch.

**Finding [C]:** the control flow admits provisional typing in a staged burst and has no matching cleanup in its ordinary stage-only return path. **Not yet established [U]:** how often this occurs in a real editor and the exact content observed. The existing `tests/test_staged_daemon.py` tests staging in isolation, not this combination.

**Important:** blindly adding `cancel()` at the return is **not** a complete safety repair. If focus or caret moved while the speech was being decoded, the cancel's backspaces can erase *other* text. The safe design boundary is to **prevent external partial injection up front** when staging or another precommit safety policy applies. Any final delivery should still be explicitly reviewed and target-guarded.

### 1.2 Prefix revision and dropped-delta corner cases

The engine sets `stable_prefix = common_prefix(previous, current)` then computes `delta = stable_prefix[len(last_emitted):]`. But `last_emitted` never decreases on a later contradictory hypothesis. Example, entirely synthetic:

1. Two outputs agree on `alpha`, so `alpha` is emitted.
2. Subsequent outputs change the accepted prefix to `alpba` (same length). No retraction is emitted.
3. The next accepted prefix grows to `alpbaX`. The code emits only `X`, leaving `alphaX` in the live target until the final re-decode/replacement.

Likewise, `_pending_partial` is one slot, not a queue: two new deltas before the poll consumes the first overwrite rather than concatenate. These are **reasoned possible traces from the current code [C]**, not measured regression frequencies. The replay contract includes each trace and requires a target-independent oracle.

### 1.3 Existing #153 fix narrows, but does not close, the problem

Closed [#153](https://github.com/MSKazemi/yazses/issues/153) documents a long-X11-dictation incident: a fixed ten-second `xdotool` timeout produced partial side effects plus fallback duplicate typing; selection and an in-flight poll were other hazards. The current code adds length-aware timeout handling and a lock/seal. The [synthetic screen regression](../../tests/test_streaming_duplication_reproducer.py) explicitly covers duplicate text and unintended deletion of a known prefix. That is useful **regression evidence [C]**, not evidence for every real application or all scripts. The reported literal repeated "D" remains unexplained in that historical report; this research does not assign it a cause.

A separate test weakness: [`test_streaming_engine_emits_partial`](../../tests/test_streaming_engine.py) ends with `assert partial is not None or True`, which is tautological and cannot fail when emission is absent [C].

## 2. Primary research and architectural tradeoffs

| Source (version pinned) | Demonstrated/claimed relevance | Transfer limit |
|---|---|---|
| Macháček, Dabre & Bojar, [*Turning Whisper into Real-Time Transcription System*](https://aclanthology.org/2023.ijcnlp-demo.3/), 2023, [arXiv landing](https://arxiv.org/abs/2307.14743) [P] | LocalAgreement on successive updates plus segmentation/context; paper reports **3.3 s** long-form latency on its evaluation setup (NVIDIA A40). | **Not** a YazSes desktop CPU or target-injection safety result. |
| [UFAL Whisper-Streaming](https://github.com/ufal/whisper_streaming/tree/6da90b44b7e50d79695e68166d2a2c7609c75abb), snapshot `6da90b4` [P] | Documents confirmation of common prefixes across updates with new audio, sentence-based buffer trimming, reprocessing and overlap handling; identifies SimulStreaming as successor. | Do not mistake YazSes' untrimmed whole-buffer/character-prefix variant for an equivalent tested implementation. |
| [UFAL SimulStreaming](https://github.com/ufal/SimulStreaming/tree/077ea37d5ab4ff98bc567e4507f140dc4e5d5ad6), snapshot `077ea37` [P] | Documents AlignAtt and LocalAgreement; separates confirmed from unconfirmed output and supports long-audio replay. | PyTorch-oriented server/demonstrator; its own performance claims cannot justify extra CPU/RAM/dependency burden or a new networking path in YazSes. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper/tree/2a3a857737d17d974f30d818ebec69ce11929e5c), snapshot `2a3a857` [P] | Existing batch and decoder window backend; VAD may filter speech/silence. | VAD is not user consent to submit/replace target text or to end a held-key turn. |

### 2.1 Latency and error evidence

[`docs/configuration.md`](../../docs/configuration.md) records an older real-time-fed benchmark (`n=15`): speech-end-to-final on `tiny.en` was 0.92 s batch versus 1.22 s with streaming; on `base.en`, 1.42 s versus 2.21 s. The base model produced **no visible confirmed prefix before release on 9/15** cases. [H] These measurements are *as published*, not reproduced or extrapolatable: the cited historical bench script is not present in the current public repository. **No new WER/CER, latency, throughput, CPU or memory measurements were made in this research.**

The current streaming loop re-decodes the growing accumulated buffer every interval [C]. It has no source-level bound equivalent to Whisper-Streaming's sentence-trimmed window [P]. Worst-case decode workload and stability over 30–120-second prompts remain unmeasured [U].

### 2.2 Dependency, platform, licensing and egress ledger

| Category | Current cost or constraint | Proposed incremental cost |
|---|---|---|
| Linux X11 | Historical `xdotool` correction/fallback faults and modelled #153 tests; app selection differs. | Pure replay: zero install/runtime dependencies; on-device application validation still required. |
| GNOME/KDE Wayland | Delivery backends, focus and selection semantics depend on compositor/application [U]. | Replay first, hardware later; no "full Wayland" claim absent verification. |
| macOS / Windows | Both are **preview** per [validation matrix](../../docs/validation-matrix.md); editor-input correctness with streaming is unverified [U]. | No status change or new platform claim. |
| Runtime | Existing `faster-whisper>=1.2.1`, CTranslate2, NumPy and platform injectors; `[streaming]` is off by default. | **Zero** new package/model required for the synthetic design. |
| Upstream code licenses | [whisper_streaming MIT](https://github.com/ufal/whisper_streaming/blob/6da90b44b7e50d79695e68166d2a2c7609c75abb/LICENSE), [SimulStreaming MIT](https://github.com/ufal/SimulStreaming/blob/077ea37d5ab4ff98bc567e4507f140dc4e5d5ad6/LICENCE.txt), [faster-whisper MIT](https://github.com/SYSTRAN/faster-whisper/blob/2a3a857737d17d974f30d818ebec69ce11929e5c/LICENSE), [CTranslate2 MIT](https://github.com/OpenNMT/CTranslate2/blob/7f59ae114cba0f7d5fb1fe6099142e4c3b0037c8/LICENSE) [P]. | No upstream code or weights vendored. A future runtime/model experiment must independently pin model license, weights revision/hash and downstream dependency obligations. |
| Privacy / egress | [ADR-011](../adr/adr-011.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-030](../adr/adr-030-agent-era-direction.md): offline microphone, no telemetry. Debug logs can contain partial/final text at some local callsites [C]. | Synthetic-only public fixtures; do not upload user audio, real prompts, transcripts or research-participant data. No new outbound primitive, log payload or third-party service. |

## 3. Options, recommendation and gates

| Option | Verdict | Why |
|---|---|---|
| A. Keep batch-after-release as reliable default, staged review as an external-injection boundary; test stream via pure event replay. | **ADOPT design/research** | Meets ADR-030, no new runtime/egress or unsafe editor operations. |
| B. Expose provisional text only in a local review/overlay surface, with a single verified final handoff after release/explicit staged commit. | **DEFER implementation** | Promising and compatible with policy; requires UX/evidence and safeguards against overlay transcript logging. |
| C. Continue target-app live partial overwrite, changing defaults or expanding endpoint heuristics now. | **REJECT for present research** | #153 history, focus/selection variability and missing safety tests make correctness unproved. |
| D. Add a separate heavyweight streaming engine or allow silence to end a held-key prompt. | **REJECT as proposed** | New dependency/pipeline, conflicts with ADR-030 and the user's intention to think silently while holding the key. Hands-free auto-stop remains a separate opt-in decision. |

**Research acceptance gates (for any later implementation request):**

1. Synthetic replay suite contains **zero** premature staged target writes, cross-target/cross-boundary deletions, duplicate final commits, post-seal partial writes, and release-before-release violations across deterministic negative tests.
2. Trace-based assertions prove that prefix regressions, pending-delta replacement, late poll completion, decode failure, empty final, no editable target, and subsequent user edits all fail without damaging pre-existing text.
3. Benchmarks publish model weights hash, `faster-whisper`/CTranslate2 versions, host CPU/core count, OS/backend, dataset manifest, normalization, full results, p50/p95 tail and CPU/RSS; compare streaming **against batch on the same input**.
4. Human-in-the-loop desktop validation is explicitly opt-in and uses safe test editors rather than users' active terminals. Linux GNOME X11 + GNOME/KDE Wayland, then macOS/Windows, require individually labelled verified reports; never promote platform or default claims on pure simulation alone.
5. Maintainer reviews and accepts the companion *proposed* ADR, and separately authorizes any delivery milestone/task. Until then the existing default stays unchanged.

## 4. Open questions for follow-up

1. Does the staged+streaming leak arise on a deterministic daemon-level fake injector and on any real editor? **Code-path hazard [C]; real reproduction [U].**
2. Should streaming + staged be mutually exclusive, or should streaming inference feed a *private preview* only? The policy draft favours preview-only long term and suppression of target partials immediately.
3. Is a single shared `_pending_partial` intentionally a latest-only display policy? If so, a source-state versioned snapshot (not suffix-only deltas) may be necessary.
4. Which target APIs, if any, can prove caret ownership/selection boundaries reliably on each platform? Until proven, external multi-keystroke rollback must not be called atomic.
5. What are p50/p95 onset→first-useful-preview and release→safe-final latencies after 10, 30, 60, 120 s prompts with long silent gaps? No current measurement.
6. How should physical held-key release and separately enabled hands-free auto-stop be represented in one replay event model without collapsing their different permission semantics?

**No user study was performed, no human transcript/audio was collected, no model was downloaded, and no runtime was changed.** This is a reproducible research/design deliverable for the evergreen issue, not evidence that the proposed fixes ship or that all current failures have been reproduced.
