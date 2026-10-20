# ADR-v2-141 — Chinese P1 stays on the existing Whisper engine; alternatives must win by measurement

**Status:** Proposed (2026-09-20)  
**Context:** Chinese ASR model selection; CPU-first/offline architecture; `SttEngine` extensibility.

## Context

There are now several strong open ASR families with Chinese coverage, including Qwen3-ASR and FunASR checkpoints such as SenseVoiceSmall and Paraformer-zh.

Adding one immediately is tempting, but YazSes is not only an ASR benchmark harness. Its recognizer must fit:

- the CPU-first hold-to-talk latency budget;
- Linux/macOS/Windows packaging;
- streaming and batch paths;
- word timestamps;
- air-gapped provisioning;
- local/offline operation;
- current memory/install expectations;
- model licensing;
- the existing `SttEngine` seam.

The repository already supports multilingual Whisper through faster-whisper and has a measured Chinese script-normalization path.

## Decision

For the first first-class Mandarin release, use the existing:

```toml
[stt]
engine = "faster-whisper"
model = "small"
language = "zh"
```

with the existing Han-script decorator.

`small` is the **supported baseline candidate**, not a permanent declaration that Whisper is the best Chinese recognizer.

Benchmark alternative models through the existing `SttEngine` protocol. A new runtime is optional and lazy-loaded; it does not become a base dependency merely because it has better upstream benchmark numbers.

### Evaluation priority

1. Same-runtime checkpoints: `large-v3-turbo`, `large-v3` (Whisper code + weights: MIT).
2. Broad dialect candidate: Qwen3-ASR-0.6B (official model card: Apache-2.0).
3. Chinese streaming candidate: Paraformer-zh / Paraformer-zh-streaming, pinned to an
   exact checkpoint/revision whose model weights explicitly declare Apache-2.0.
4. SenseVoiceSmall as a **research-only** comparison while its weights use the custom
   FunASR Model Open Source License; it is not a permissive-license production candidate.
5. Larger models only where target hardware/use case justifies them.

A toolkit's source-code license is not sufficient evidence for a model checkpoint. Every
production candidate records the exact weight repository, immutable revision/commit and
weight-license source. YazSes prefers MIT/Apache-2.0/BSD-style model-weight licenses for
recommended profiles; a custom model license requires explicit maintainer/legal review before
bundling or recommending the weights.

### Promotion requirement

A new engine becomes a recommended profile only if YazSes measurements demonstrate a material product benefit, such as:

- >=20% relative CER reduction, or
- materially better validated dialect coverage, or
- >=30% latency/core-cost reduction at non-inferior quality, or
- a supported language capability the baseline lacks,

while also passing packaging, timestamp, streaming, offline and license gates. The license
gate requires an auditable weight license for the exact revision; permissive licenses are the
default for recommended profiles.

## Consequences

### Positive

- P1 is mostly orchestration/test work rather than a second ML stack.
- English installation size and runtime stay unchanged.
- Chinese support can ship independently from research into specialized models.
- Model changes remain replaceable behind one interface.
- Upstream model hype does not silently redefine YazSes’ hardware contract.

### Costs

- P1 may not deliver the absolute best achievable Mandarin CER.
- The project must build and maintain a reproducible benchmark harness before choosing a specialized model.
- Supporting a future Chinese engine still requires an adapter and package matrix.

## Alternatives considered

### Adopt Qwen3-ASR-0.6B immediately

Rejected for P1. Its broad Chinese dialect support is compelling, but the official runtime/deployment path introduces a substantially different stack, and interactive CPU behavior has not been measured in YazSes.

### Adopt SenseVoiceSmall immediately

Rejected for P1 and not a permissive-license production candidate at present. It is promising
for CPU Chinese/Cantonese and may be benchmarked for research comparison, but its current
weights point to the custom FunASR Model Open Source License rather than MIT/Apache/BSD. Any
future production use requires explicit review of the exact weight revision in addition to
adapter, timestamp, packaging and comparative measurements.

### Use `large-v3` as the default Chinese model

Rejected as an unmeasured default for the CPU-first product. Existing microbench evidence suggests better CER, but its resource/long-form tradeoffs are substantial and the repository has already observed large-v3 conditioning instability on other corpora.

### Auto-select a model by available RAM/CPU

Deferred. First establish validated presets and capability data. Hidden automatic model changes make results harder to reproduce.

## Required evidence before superseding this ADR

A superseding ADR must include:

- exact model repository, immutable revision/commit and model-weight license source;
- corpus/split/normalization;
- CER and error analysis;
- RTF/latency/RSS/core-seconds;
- startup/cache/offline behavior;
- `SttEngine` method coverage;
- package impact on each supported OS;
- streaming and meeting behavior;
- comparison against the currently supported Chinese baseline.
