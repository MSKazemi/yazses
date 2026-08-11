# ADR-v04-001: llama-cpp-python for Tier 2 SLM Intent Routing

| Field | Value |
|---|---|
| **ID** | ADR-v04-001 |
| **Status** | Accepted |
| **Date** | 2026-05-17 |
| **Module** | `src/yazses/commands/slm_router.py` |

---

## Context

YazSes v0.3.x uses a regex grammar engine (Tier 1) that classifies 28+ command intents from transcribed speech. This approach is deterministic and low-latency but requires exact or near-exact phrasing. Natural variants such as "close this tab" versus "switch to the next tab" or "save what I have" versus "save file now" fall through Tier 1 unmatched and are dispatched as plain dictation instead of commands.

Users who rely on voice control for editor navigation or system actions experience high miss rates when their phrasing drifts from the hardcoded patterns. Expanding the regex set compounds maintenance cost and still fails on paraphrase.

A small language model running locally can resolve natural phrasing to a known intent without requiring cloud connectivity or exact vocabulary match.

---

## Decision

Use `llama-cpp-python >= 0.3.0` as an optional, in-process GGUF inference backend for Tier 2 command classification in v0.4.0.

The model is loaded at daemon startup if `[commands] slm_model_path` points to a valid GGUF file. If the path is absent, points to a missing file, or if `llama-cpp-python` is not installed, the daemon starts normally with Tier 1 only (degraded-graceful mode). The Tier 2 path is never in the critical path for dictation.

Tier 2 routing runs after Tier 1 classification fails. The transcribed text is submitted to the loaded model with a system prompt enumerating the available intents. If the model response maps to a known intent with confidence above `slm_confidence_threshold` (default `0.75`), the intent is dispatched; otherwise the text is treated as dictation.

---

## Rationale

**In-process execution.** `llama-cpp-python` runs the model inside the daemon process via its C extension. There is no external service dependency, no socket roundtrip, and no requirement to start `ollama serve` before launching YazSes. This preserves the project's offline, zero-dependency daemon design.

**GGUF is the de-facto standard for CPU-quantised inference.** The format is supported by all major quantisation tools and model repositories. llama-cpp-python is the dominant Python binding for llama.cpp and is actively maintained with regular wheel releases for Linux, macOS, and Windows.

**TinyLlama-1.1B-Q4\_K\_M is validated for this use case.** At approximately 700 MB on disk, this model runs within 2–3 seconds on a mid-range laptop CPU and achieves sufficient accuracy for a closed 28-intent classification task when prompted appropriately. The model need not generalise; it only routes among a fixed label set.

**Graceful degradation.** Making the feature optional (behind a config key and a separate dep group) means existing users see no behaviour change on upgrade. Power users opt in by downloading a model file and setting one config value.

---

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| **Ollama** | Requires an external `ollama serve` process; adds a system-level dependency; IPC overhead; not available on all platforms by default |
| **ctransformers** | Less actively maintained; GGUF support is partial; narrower hardware compatibility matrix |
| **ONNX Runtime** | Fewer GGUF-format models available; requires separate export tooling; higher barrier for users to supply their own model |

---

## Consequences

- **Memory:** +700 MB–2.2 GB RAM while the model is loaded, depending on quantisation. Unloaded when daemon stops.
- **Startup latency:** +2–5 seconds at daemon start for model load. IDLE state is not reached until load completes.
- **Model distribution:** The model file is not bundled. Users must download it separately. The `yazses doctor` command will report when `slm_model_path` is set but the file is missing.
- **Build complexity:** `llama-cpp-python` wheels are platform and architecture specific. CI (`test.yml`) must install the `slm` extra on each platform matrix leg to validate import and basic inference.
- **No Tier 2 guarantee:** Even with a model loaded, Tier 2 may decline to classify (score below threshold). This is the intended safe fallback.

---

## Configuration

```toml
[commands]
slm_model_path = "~/.local/share/yazses/models/tinyllama-1.1b-chat-q4_k_m.gguf"
slm_confidence_threshold = 0.75
```

`slm_model_path` defaults to `""` (Tier 2 disabled).

---

## Dependency

Optional dep group `slm` in `pyproject.toml`:

```toml
[project.optional-dependencies]
slm = ["llama-cpp-python >= 0.3.0"]
```

Install with:

```bash
uv sync --extra slm
```
