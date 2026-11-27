# ADR-035 — Model download policy: `auto`, `ask`, `never`

**Status:** Proposed (2026-11-27) · the pure half exists; no config key, default or CLI change; awaiting the maintainer's decision  
**Decision owner:** YazSes maintainer (pending). A new config key is L3 work (AGENTS.md, "Public interfaces").  
**Tracking:** [#928](https://github.com/MSKazemi/yazses/issues/928) (epic), [#929](https://github.com/MSKazemi/yazses/issues/929) (workstream 1)  
**Context:** [ADR-011](adr-011.md), [ADR-019](adr-019-egress-inventory-and-escalation.md), [ADR-028](adr-028-feature-addon-packs.md), [ADR-029](adr-029-runtime-residency.md), [ADR-030](adr-030-agent-era-direction.md) §3 (breadth freeze)

## Context

Several model fetches happen without the user asking for them: a daemon start with an
uncached speech model or with read-back enabled and no voice, the first time a camera
feature opens. On a
locked-down network the speech-model fetch used to end in a traceback
([#310](https://github.com/MSKazemi/yazses/issues/310)); it now ends in a held daemon with
instructions, but a user still cannot say "do not fetch" in `config.toml`. The existing
route is the `HF_HUB_OFFLINE` environment variable, which reaches only the loaders that go
through `huggingface_hub`, not the Kokoro or MediaPipe downloads.

`yazses.models.registry` already lists every model kind and holds a pure
`ensure_model(kind, name, policy, is_cached=, download=)`. What is not decided is what the
policy governs and where a user sets it.

## Decision (proposed)

1. **Three values, default `auto`.**

   | Policy | Missing model, fetched implicitly | Missing model, fetched by an explicit command |
   |---|---|---|
   | `auto` | downloaded, as today | downloaded |
   | `ask` | not downloaded; name, size and the command that fetches it are reported | downloaded (the command is the answer to the question) |
   | `never` | not downloaded; the manual URL and destination are reported | refused, with the same manual route |

2. **The policy covers model weights only.** Package installs (`features enable`,
   `setup`) and the update check keep their own consent rules.
3. **A missing model never stops the daemon.** Under `ask` or `never` a missing speech
   model takes the existing `ModelUnavailableError` path: IPC and the tray stay up and the
   message names the route. A missing optional model leaves its feature inactive and says
   so. A cached model loads under every policy.
4. **Every implicit fetch goes through `ensure_model`.** The decision is made in one pure
   function; the code that can open a connection stays in the modules ADR-019 already
   lists. The policy is not a sandbox: for a dependency that fetches by model name, it is
   enforced by loading local-only (`local_files_only=True` or `system/hfcache.py`), and the
   `--network none` container check remains the proof for the whole process.
5. **`HF_HUB_OFFLINE` keeps its meaning.** Either it or `never` forbids a fetch; neither
   overrides the other into allowing one.

## Open question for the owner: where the key lives

#929 proposes `[stt] download`. This record recommends **`[models] download`** instead,
because the same value decides the Read-Back voice, the gaze asset and diarization, and a
user turning downloads off should not need to know that a speech-section key does it. The
cost is one new config section. Either way it is a single key with default `auto`.

## Where each fetch stands

| Fetch | Triggered by | Through `ensure_model` |
|---|---|---|
| Kokoro voice (`tts/kokoro.py` → `tts/download.py`) | implicit: voice built (daemon start with `[tts]` enabled) | yes, policy fixed at `auto` |
| Whisper (`stt/faster_whisper.py`) | implicit: daemon start, fallback engine, file and meeting decode | no |
| Parakeet, Moonshine (`stt/parakeet.py`, `stt/moonshine.py`) | implicit: engine start | no |
| FaceLandmarker (`gaze/download.py`, called by the gaze, perception and face-gesture backends) | implicit: camera feature start | yes, policy fixed at `auto` |
| ECAPA speaker model (`voiceprint/ecapa.py`, by way of `system/hfcache.py`) | implicit: voiceprint enrol or match | yes, policy fixed at `auto` |
| pyannote pipeline (`recimport/pyannote_backend.py` by way of `system/hfcache.py`, sends the user's HF token) | implicit: first diarized run on that backend | yes, policy fixed at `auto` |
| Whisper on purpose (`yazses model download`, `yazses language set`) | explicit | no |
| Intent-routing GGUF (`commands/model_manager.py`) | explicit | no |
| sherpa diarization (`recimport/download.py`) | explicit: `yazses transcribe --download-models` | no |
| Silero VAD (`meeting/silero_vad.py`) | never fetched: the weights ship inside the wheel | not needed |

Until every implicit row says yes, no config key should ship: a `never` that some features
ignore is worse than no setting. The explicit rows need routing too before `never` can
refuse them.

For a model a library fetches by name, "is it cached" is answered by the cache-only load
itself (`system/hfcache.load_cache_first` with a kind and a name). The ECAPA encoder is
filed under the `diarization` kind, since the registry has no speaker kind; neither it nor
pyannote has a `build_registry` row, so `yazses model list` does not show them.

## Consequences

- An existing install is unchanged: `auto` is today's behaviour.
- Later workstreams (#931 lazy load, #932 other kinds, #934 picker) build on one decision
  function and one listing instead of one per downloader.
- `language set --no-download` already refuses per invocation; it stays, and `ask` /
  `never` must not weaken it.

## Alternatives considered

- **Document `HF_HUB_OFFLINE` and add nothing.** Rejected: it does not reach the non-hub
  downloads and a daemon started by a service manager does not inherit a shell variable.
- **One policy per feature.** Rejected: six settings for one intention, and the one a user
  forgets is the connection they did not expect.
- **An interactive prompt under `ask`.** Rejected for this record: the daemon has no
  terminal, and a modal question is one a voice user may not be able to answer
  ([ADR-022](adr-022-a-confirmation-a-voice-user-cannot-give.md)). A settings or tray
  download button (#934) can answer `ask` later.
