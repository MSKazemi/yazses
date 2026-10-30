# Model provenance and compatibility inventory

Status: inventory dated 2026-10-28; read-only; not a recommendation to add any model.
Part of epic #692 / issue #694. Android pinning was done separately in #683 (closed as
completed on 2026-10-25, through PR #684); this document does not duplicate it.

## How to read this

- **Scope.** Every model YazSes downloads, loads, lists in code, or names as a default,
  plus the models the project benchmarked, plus a short list of candidates for the
  camera/gaze, EMG and EEG research tracks. Nothing was downloaded as weights; Hub
  metadata and model cards were read through the public API and the raw README.
- **Revision (`sha`).** Hugging Face git commit at the head of `main` on the fetch date
  (2026-10-28). It is the commit that the repository pointed to when read. It is **not**
  a pin YazSes uses, and it will drift when the repository changes. Where the code pins
  nothing, the table says so.
- **Licence (as stated).** The value in the Hub metadata (`cardData.license` or the
  `license:` tag) and/or the licence text in the model card, quoted or closely
  paraphrased. "Not verified" means the licence was not read in this pass.
- **Used by YazSes.** Yes/no and `file:line` in this repository. "Listed" means the
  name appears in a lookup table but is not loaded by default. "Opt-in" means a config
  value or extra must be set before the code path runs.
- **Independently benchmarked by YazSes.** "Yes" means a file under `paper/results/`
  records a measurement that names the model. Those files record the model name and,
  for Persian runs only, a `revision` field; most do not record the Hub repository or
  revision actually loaded, so they cannot be tied to a sha. "No" means no result file
  names the model.
- **Two different licences.** For each Whisper-family row, the conversion repository
  (what YazSes downloads) and the upstream original (what it was converted from) are
  listed separately (see Table A3).
- **Code facts.** Every "YazSes does X" statement cites `file:line`. Line numbers are
  for commit `4fda3403` on `main`; every repository file cited here is identical there to
  `0e0dcfd1`, the commit the inventory was written against.

## Table A: models YazSes uses or lists

### A1. Whisper family, faster-whisper / CTranslate2 conversions (downloaded by YazSes)

YazSes resolves a short name through `WHISPER_MODELS` (`src/yazses/stt/download.py:47-67`),
which mirrors upstream `faster_whisper/utils.py:11-31` (verified against the installed
faster-whisper 1.2.1 in this worktree's environment). Every repository below is an
ordinary Hub model; none is gated. Every conversion repository declares `license: mit` in
its front matter; none has a licence section in the body, and each names its upstream
OpenAI or Distil-Whisper card as "the original model" (see Table A3).

| Model (YazSes name) | Original org/author | Official URL | Licence (as stated) and conditions | Immutable revision (sha, lastModified) | Runtime | CPU/GPU requirements | Intended use and limitations (as stated) | Used by YazSes | Independently benchmarked by YazSes |
|---|---|---|---|---|---|---|---|---|---|
| `Systran/faster-whisper-tiny` (`tiny`) | Converted by Systran from openai/whisper-tiny | https://huggingface.co/Systran/faster-whisper-tiny | mit (front matter). Body: none; links upstream card | `d90ca5fe260221311c53c58e660288d3deb8d356` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:64`; loaded only if `[stt] model = "tiny"` | No (only `tiny.en` measured) |
| `Systran/faster-whisper-tiny.en` (`tiny.en`) | Systran, from openai/whisper-tiny.en | https://huggingface.co/Systran/faster-whisper-tiny.en | mit (front matter) | `0d3d19a32d3338f10357c0889762bd8d64bbdeba` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:65`; named in `docs/models.md:90` | Yes: `paper/results/wer.json` (laptop); `probes/wer-matrix.json`, `probes/wer-vm-clean.json`, `wer-test-other.json` (Xeon). Model name only, no repo or sha recorded |
| `Systran/faster-whisper-base` (`base`) | Systran, from openai/whisper-base | https://huggingface.co/Systran/faster-whisper-base | mit (front matter) | `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:48` | Yes, multilingual Persian runs: `paper/results/persian-fleurs-test50-base.json`, `persian-fleurs-test871-base.json` (these record `revision: null`) |
| `Systran/faster-whisper-base.en` (`base.en`) | Systran, from openai/whisper-base.en | https://huggingface.co/Systran/faster-whisper-base.en | mit (front matter) | `3d3d5dee26484f91867d81cb899cfcf72b96be6c` (2023-11-23) | faster-whisper / CTranslate2 | not stated | English only (`en` tag); card does not state limitations | **Yes, default**: `src/yazses/config.py:43` (`model: str = "base.en"`); mapping `stt/download.py:49`; `docs/models.md:15`, `:24` | Yes: `wer.json` (laptop); `probes/wer-matrix.json`, `probes/wer-vm-clean.json`, `wer-test-other.json`, `probes/decode-determinism-base.en-*.json` |
| `Systran/faster-whisper-small` (`small`) | Systran, from openai/whisper-small | https://huggingface.co/Systran/faster-whisper-small | mit (front matter) | `536b0662742c02347bc0e980a01041f333bce120` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:62` | Yes, Persian runs: `persian-fleurs-test50-small*.json`, `persian-fleurs-test871-small*.json`. `persian-cvfa-test10559-small.json` records `revision: 536b0662742c02347bc0e980a01041f333bce120`, which equals this sha |
| `Systran/faster-whisper-small.en` (`small.en`) | Systran, from openai/whisper-small.en | https://huggingface.co/Systran/faster-whisper-small.en | mit (front matter) | `d1d751a5f8271d482d14ca55d9e2deeebbae577f` (2023-11-23) | faster-whisper / CTranslate2 | not stated | English only | Listed: `stt/download.py:63`; `docs/models.md:92` | Yes: `wer.json` (laptop); `probes/wer-matrix.json`, `probes/wer-vm-clean.json`, `wer-test-other.json`, `probes/decode-determinism-small.en-*.json` |
| `Systran/faster-whisper-medium` (`medium`) | Systran, from openai/whisper-medium | https://huggingface.co/Systran/faster-whisper-medium | mit (front matter) | `08e178d48790749d25932bbc082711ddcfdfbc4f` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:60` | Yes, Persian: `persian-fleurs-test50-medium.json` |
| `Systran/faster-whisper-medium.en` (`medium.en`) | Systran, from openai/whisper-medium.en | https://huggingface.co/Systran/faster-whisper-medium.en | mit (front matter) | `a29b04bd15381511a9af671baec01072039215e3` (2023-11-23) | faster-whisper / CTranslate2 | not stated | English only | Listed: `stt/download.py:61` | Yes: `probes/wer-matrix.json`, `wer-test-other.json`, `probes/decode-determinism-medium.en-*.json` |
| `Systran/faster-whisper-large-v1` (`large-v1`) | Systran, from openai/whisper-large (v1) | https://huggingface.co/Systran/faster-whisper-large-v1 | mit (front matter) | `b07c8d4be0be90092aa01a29c975077acb8d15c9` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:56` | No |
| `Systran/faster-whisper-large-v2` (`large-v2`) | Systran, from openai/whisper-large-v2 | https://huggingface.co/Systran/faster-whisper-large-v2 | mit (front matter) | `f0fe81560cb8b68660e564f55dd99207059c092e` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:57` | No |
| `Systran/faster-whisper-large-v3` (`large-v3`, alias `large`) | Systran, from openai/whisper-large-v3 | https://huggingface.co/Systran/faster-whisper-large-v3 | mit (front matter). Upstream card says apache-2.0 (Table A3) | `edaa852ec7e145841d8ffdb056a99866b5f0a478` (2023-11-23) | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:55` and `:58` | Yes: `probes/wer-matrix.json`, `wer-test-other.json`, `wer-vm-clean.json` (English); `probes/largev3-instability-*.json`. No repo or sha recorded |
| `Systran/faster-distil-whisper-large-v2` | Conversion of distil-whisper/distil-large-v2 | https://huggingface.co/Systran/faster-distil-whisper-large-v2 | mit (front matter); upstream distil card mit | `fe9b404fc56de3f7c38606ef9ba6fd83526d05e4` (2024-05-09) | faster-whisper / CTranslate2 | not stated | English only (per upstream card, Table A3) | Listed: `stt/download.py:50` | No |
| `Systran/faster-distil-whisper-large-v3` | Conversion of distil-whisper/distil-large-v3 | https://huggingface.co/Systran/faster-distil-whisper-large-v3 | mit (front matter); upstream mit | `c3058b475261292e64a0412df1d2681c06260fab` (2024-03-25) | faster-whisper / CTranslate2 | not stated | English only (per upstream card) | Listed: `stt/download.py:51` | No |
| `Systran/faster-distil-whisper-medium.en` | Conversion; upstream named by repository name (card not read) | https://huggingface.co/Systran/faster-distil-whisper-medium.en | mit (front matter); upstream mit | `80ddfce281f77766d8943d63109199fc8145dfa5` (2024-01-19) | faster-whisper / CTranslate2 | not stated | English only | Listed: `stt/download.py:53` | No |
| `Systran/faster-distil-whisper-small.en` | Conversion of distil-whisper/distil-small.en | https://huggingface.co/Systran/faster-distil-whisper-small.en | mit (front matter); upstream mit | `ef77d90526ccd62cde3808ee70626a01e5cf83e4` (2024-01-22) | faster-whisper / CTranslate2 | not stated | English only | Listed: `stt/download.py:54` | No |
| `distil-whisper/distil-large-v3.5-ct2` (`distil-large-v3.5`) | distil-whisper (Hugging Face) | https://huggingface.co/distil-whisper/distil-large-v3.5-ct2 | mit. Card: "inherits the MIT license from OpenAI's Whisper model" | `9793ccc07920e0f830e1dba0343efcdf0ef8c903` (2025-03-19) | faster-whisper / CTranslate2 | not stated | English only (`en` tag) | Listed: `stt/download.py:52` | No |
| `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (`turbo`, `large-v3-turbo`) | Requested id is a Mobius Labs repo. **The API call returned HTTP 307 to `dropbox-dash/faster-whisper-large-v3-turbo`**; the content read is at the redirect target | https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo (redirect from the id in code) | mit (front matter, redirect target). Card: conversion of openai/whisper-large-v3-turbo | `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` (2025-11-05), read at the redirect target | faster-whisper / CTranslate2 | not stated | not stated in the conversion card | Listed: `stt/download.py:59` and `:66` | Yes, Persian only: `persian-fleurs-test871-large-v3-turbo.json` (`revision: null`) |

Notes on A1:

- **Whisper large-v3 benchmarks** read the English figures from result files that use the
  model name `large-v3`; the repository actually loaded in those runs is not recorded.
- **The `mobiuslabsgmbh` redirect.** The id in `stt/download.py:59` and `:66` (and in
  upstream faster-whisper 1.2.1) is answered by the Hub with a redirect to a different
  owner. Whether the redirect is permanent, and whether the content is identical, is not
  verified. YazSes does not pin the revision, so a future content change would be picked
  up silently on the next fresh download.

### A2. Speech-to-text engines other than faster-whisper

| Model | Original org/author | Official URL | Licence (as stated) and conditions | Immutable revision (sha, lastModified) | Runtime | CPU/GPU requirements | Intended use and limitations (as stated) | Used by YazSes | Independently benchmarked by YazSes |
|---|---|---|---|---|---|---|---|---|---|
| NVIDIA Parakeet TDT 0.6B v2 (`nemo-parakeet-tdt-0.6b-v2`, YazSes name) | NVIDIA | https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 | cc-by-4.0. Card: "GOVERNING TERMS: Use of this model is governed by the CC-BY-4.0 license" (line 179) | `ae9ad07059c7c739ffaf932226a8fe64ae2620b0` (2026-06-29) upstream NeMo repo | Upstream is NeMo (`.nemo`). YazSes loads via `onnx-asr` (see the ONNX note below) | Card: "designed to run on NVIDIA GPU-accelerated systems" (line 229); "At least 2GB RAM for model to load" (line 350); supported GPU microarchitectures and Linux listed (lines 338-346). No CPU-only figure stated | "Designed for high-quality English transcription" (line 161). Limitations: "Transcripts may be not 100% accurate. Accuracy varies based on language and characteristics of input audio" (line 512) | **Opt-in** engine: `src/yazses/stt/parakeet.py:39` (`DEFAULT_MODEL`); load at `parakeet.py:164` and `:173` (`onnx_asr.load_model`), wrapped by `load_cache_first` at `parakeet.py:194`. Name also in `language/capability.py:51-54` (`ENGINE_DEFAULT_MODELS`) and `:178` | Yes: `probes/wer-matrix.json`, `wer-test-other.json`, `probes/wer-vm-clean.json` (Xeon). Model name only |
| ONNX conversion of Parakeet TDT 0.6B v2 (candidate source of the ONNX files) | Converter account `istupakov` (not the original author), for `onnx-asr` | https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx | cc-by-4.0; `base_model: nvidia/parakeet-tdt-0.6b-v2` | `0bbb45a3365852604aef28b538a8f066f4ccaa85` (2026-02-17) | onnx-asr / ONNX Runtime | not stated | Inherits the upstream card (not separately read) | **Not verified** as the repository YazSes downloads. The code names only the alias `nemo-parakeet-tdt-0.6b-v2` and `onnx-asr` is not installed in this worktree, so the alias-to-repo mapping was not inspected | No (not benchmarked as this repo) |
| NVIDIA Parakeet TDT 0.6B v3 (`nemo-parakeet-tdt-0.6b-v3`) | NVIDIA | https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 | cc-by-4.0 (line 812) | `541d1f99c6b0c3cd0b11a95167540bb8edefd82b` (2026-08-05) | NeMo; safetensors; GGUF variant also listed on the Hub | "Designed for high-throughput speech-to-text" (line 789); hardware statements not read in full | Multilingual (25 European languages per card, line 794) | **Listed only**: `language/capability.py:89` (source) and `:182` (table row). Not the engine default. No code path loads it by default | No (no result file names v3) |
| UsefulSensors Moonshine (now `moonshine-ai/moonshine` on the Hub) | Useful Sensors (card: "Useful Sensors developed the models") | https://huggingface.co/moonshine-ai/moonshine (the id in code, `UsefulSensors/moonshine`, redirects here) | mit (front matter). Redirect target | `48b4e427b587bcf67797a5be706d6ddc4a298149` (2025-11-30) | `useful-moonshine-onnx` (ONNX Runtime) | not stated numerically. Card says intended for platforms "severely constrained in memory capacity and computational resources" (intent, not a figure) | English only; tiny and base are English-only (table, card line 23-24). "prone to generating repetitive texts" (line 58) | **Opt-in** engine: `src/yazses/stt/moonshine.py:46` (`DEFAULT_MODEL = "moonshine/base"`); load at `moonshine.py:131-147`. The installed package downloads from the id `UsefulSensors/moonshine` with `hf_hub_download` and **no revision**: `.venv/lib/python3.14/site-packages/moonshine_onnx/model.py:5-9`, package version 20251121 | Yes: `probes/wer-matrix.json` (tiny 4.20, base 3.17), `wer-test-other.json`, `probes/wer-vm-clean.json`. Model name only |
| SpeechBrain ECAPA-TDNN speaker encoder (`speechbrain/spkrec-ecapa-voxceleb`) | SpeechBrain team; architecture Desplanques et al. (Interspeech 2020, card citation) | https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb | apache-2.0 (front matter and metadata) | `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286` (2025-02-18) | SpeechBrain (PyTorch) | not stated in card (card gives a GPU option, `run_opts={"device":"cuda"}`, line 80) | Trained on VoxCeleb. "The SpeechBrain team does not provide any warranty on the performance achieved by this model when used on other datasets" (line 104-106) | **Optional** (`voiceprint` extra, `pyproject.toml:214`): `src/yazses/voiceprint/ecapa.py:28-29` with `load_cache_first`; default backend value `src/yazses/config.py:788` (`"ecapa"`). Whether the voiceprint feature is on by default was not checked | No (only log files mention speechbrain: `probes/logs/x86-*.log`) |
| pyannote speaker diarization pipeline 3.1 (`pyannote/speaker-diarization-3.1`) | pyannote (Hugging Face organisation) | https://huggingface.co/pyannote/speaker-diarization-3.1 | mit (Hub metadata). **Gated** (`gated: auto`); the model card body returned HTTP 401 without a token and was not read | `84fd25912480287da0247647c3d2b4853cb3ee5d` (2024-05-10) | pyannote.audio (PyTorch) | not stated (not read) | not read | **Opt-in** (`[recimport] backend = "pyannote"`, `src/yazses/config.py:1762` comment; `src/yazses/recimport/pyannote_backend.py:70`, `:196`, `Pipeline.from_pretrained(..., token=...)`). Requires accepted conditions (`pyannote_backend.py:162-163`) | No |
| pyannote segmentation 3.0 (`pyannote/segmentation-3.0`) | pyannote | https://huggingface.co/pyannote/segmentation-3.0 | mit (Hub metadata). Gated (`auto`); body returned HTTP 401 | `e66f3d3b9eb0873085418a7b813d3b369bf160bb` (2024-05-10) | pyannote.audio | not stated (not read) | not read | Loaded by the pyannote pipeline (`pyannote_backend.py:76` comment: "the pipeline loads both"). Its weights, converted, are also the default sherpa segmentation model (next row) | No, as the pyannote runtime. The sherpa conversion is benchmarked (below) |
| sherpa-onnx pyannote segmentation 3.0 ONNX (`sherpa-onnx-pyannote-segmentation-3-0.onnx`) | k2-fsa (sherpa-onnx), converting pyannote segmentation 3.0 | Release asset: https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 (not a Hub repository) | **Not verified** for the conversion. Upstream pyannote segmentation 3.0 is mit per Hub metadata. sherpa-onnx code is Apache-2.0 (`LICENSE` fetched) | Not a commit. Tag-based URL (`speaker-segmentation-models`); no checksum in code. HEAD returned HTTP 200 on 2026-10-28; `Content-Length` not reported | sherpa-onnx (ONNX Runtime, no torch) | not stated | not stated | **Default** diarizer backend: `src/yazses/config.py:1762` (`backend: str = "sherpa"`); URL `src/yazses/recimport/download.py:22-24`; filename `src/yazses/recimport/diarizer.py:18` | Yes: `paper/results/diarization-ami16_corpus-der.json` (backend recorded as "sherpa-onnx (pyannote segmentation-3.0 + 3D-Speaker ERes2Net)"); `diarization-ami16_corpus-maxspk4.json`, `probes/ami16-shipped.json`, `probes/ami-der.json` |
| 3D-Speaker ERes2Net base, zh-cn ONNX (`3dspeaker-eres2net-base.onnx`) | 3D-Speaker project (repository `modelscope/3D-Speaker`). Variant name in URL: `zh-cn` | Release asset: https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx (not a Hub repository; tag spelled `recongition` in the URL) | **Not verified** for the weights. 3D-Speaker repository code licence: Apache-2.0 (`LICENSE` fetched, `raw.githubusercontent.com/modelscope/3D-Speaker/main/LICENSE`) | Not a commit. Tag-based URL; no checksum in code. HEAD returned HTTP 200 on 2026-10-28 | sherpa-onnx | not stated | not stated | **Default** diarizer embedding model: `src/yazses/recimport/download.py:26-28`; `src/yazses/recimport/diarizer.py:19` | Yes: `diarization-ami16_corpus-der.json`, `centroid-merge-ami16_corpus-*.json`, `probes/embmodel-test.json` (compares ERes2Net, CAM++ and WeSpeaker variants) |
| Silero VAD, faster-whisper bundled (`silero_vad_v6.onnx`) | Silero Team (`snakers4/silero-vad`, named in `faster_whisper/vad.py:13` comment) | Bundled in the faster-whisper package; no Hub repo fetched | **Not verified** in this pass (licence of the Silero model was not read; faster-whisper package metadata says MIT) | Not a Hub commit. File in the worktree environment: SHA-256 `4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2`, 1,245,151 bytes (faster-whisper 1.2.1) | ONNX Runtime via faster-whisper | not stated | not stated | **Yes, used**: speech detector for file import (`src/yazses/recimport/audio_io.py:152-160`, `faster_whisper.vad`). No download: the file ships in the package | No measurement file names this VAD model. `paper/results/platform-resolution.json` mentions silero in a resolution context only |
| Silero VAD, `silero-vad` package (optional) | Silero Team | Package `silero-vad` (PyPI); not fetched | **Not verified** | Not fetched | `load_silero_vad(onnx=True)` | Per the project's own docstring (`src/yazses/meeting/silero_vad.py:5-8`, measured by the project 2026-08-23): pulls torch and torchaudio, about 3 GB. Not re-measured here | not stated | **Opt-in** (`[meeting] vad_backend = "silero"`, default `calibrated`): `src/yazses/meeting/silero_vad.py:41-46`; `src/yazses/config.py:1834`; `pyproject.toml:321-322` | No |
| MediaPipe FaceLandmarker, float16 bundle (`face_landmarker.task`) | Google (MediaPipe) | https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task (`src/yazses/gaze/download.py:27-29`) | **Not verified.** No licence or terms page was read | Not a Hub commit. Versioned path `float16/1`; no checksum in code. HEAD on 2026-10-28: HTTP 200, `Content-Length: 3758596`, `ETag` (MD5, hex) `b0e7274907a1644404fef66b28dd6d85`, `Last-Modified: Wed, 03 May 2023`. File not downloaded, so the hash was not recomputed | MediaPipe Tasks (Python), CPU path | not stated in code or read docs | not read | **Opt-in** (gaze/perception features, both off by default: `src/yazses/config.py:585-586` and `:653`): `src/yazses/gaze/download.py:121-130` (fetch once to the user cache, `MIN_MODEL_BYTES`), used by `src/yazses/gaze/mediapipe_backend.py:27-37` and `src/yazses/perception/mediapipe_backend.py:110-120` | No (no result file names `face_landmarker`) |
| L2CS-Net (gaze backend `l2cs`, manual install) | Ahmednull/L2CS-Net (named as base model of the LiteRT conversion in Table B); upstream authors not verified here | Not fetched | **Not verified** | Not fetched | PyTorch, via the `l2cs` package | not stated | not stated | **Opt-in**, manual install only: `src/yazses/gaze/l2cs.py:18` (`from l2cs import Pipeline`), `:25` (`weights=None`, comment says the package resolves its bundled ResNet). `src/yazses/gaze/factory.py:12-14` | No |

Notes on A2:

- **Parakeet ONNX mapping.** `src/yazses/stt/parakeet.py` never names a Hub repository;
  it passes the alias to `onnx_asr.load_model`. The `onnx-asr` package is not installed
  in the worktree environment, so which repository it fetches, and at which revision, was
  **not verified**. The conversion card (`istupakov/...`) shows the same alias in its
  example, which suggests the alias belongs to `onnx-asr`, but that is inference from the
  card, not from the library source.
- **Moonshine revision.** The package fetches `UsefulSensors/moonshine` by subfolder
  (`onnx/merged/base/float`, `model.py:5-9`). Because the id is a redirect, the
  repository being read is `moonshine-ai/moonshine`; the file tree was not compared
  against the `onnx/merged/base/float` files that the package uses.

## Table A3: upstream originals (for provenance; not downloaded by YazSes)

| Upstream | Official URL | Licence as stated on the Hub card | Revision (sha) | What the card says about use or limits | Relation to the conversion in Table A1 |
|---|---|---|---|---|---|
| OpenAI Whisper code | https://github.com/openai/whisper | MIT License, "Copyright (c) 2022 OpenAI" (`LICENSE` fetched 2026-10-28) | GitHub repository (not pinned here) | not in scope of the card | The code. The weights are separate (next rows) |
| `openai/whisper-tiny` | https://huggingface.co/openai/whisper-tiny | apache-2.0 (Hub metadata) | `169d4a4341b33bc18d8881c4b69c2e104e1cc0af` | not read in full; the large-v3 card is representative | Upstream of `Systran/faster-whisper-tiny`. The Systran card says `mit` |
| `openai/whisper-tiny.en` | https://huggingface.co/openai/whisper-tiny.en | apache-2.0 | `87c7102498dcde7456f24cfd30239ca606ed9063` | not read in full | Upstream of `Systran/faster-whisper-tiny.en`. Systran says `mit` |
| `openai/whisper-base` | https://huggingface.co/openai/whisper-base | apache-2.0 | `e37978b90ca9030d5170a5c07aadb050351a65bb` | not read in full | Upstream of `Systran/faster-whisper-base`. Systran says `mit` |
| `openai/whisper-base.en` | https://huggingface.co/openai/whisper-base.en | apache-2.0 | `911407f4214e0e1d82085af863093ec0b66f9cd6` | not read in full | Upstream of `Systran/faster-whisper-base.en` (default). Systran says `mit` |
| `openai/whisper-small` | https://huggingface.co/openai/whisper-small | apache-2.0 | `973afd24965f72e36ca33b3055d56a652f456b4d` | not read in full | Upstream of `Systran/faster-whisper-small`. Systran says `mit` |
| `openai/whisper-small.en` | https://huggingface.co/openai/whisper-small.en | apache-2.0 | `e8727524f962ee844a7319d92be39ac1bd25655a` | not read in full | Upstream of `Systran/faster-whisper-small.en`. Systran says `mit` |
| `openai/whisper-medium` | https://huggingface.co/openai/whisper-medium | apache-2.0 | `abdf7c39ab9d0397620ccaea8974cc764cd0953e` | not read in full | Upstream of `Systran/faster-whisper-medium`. Systran says `mit` |
| `openai/whisper-medium.en` | https://huggingface.co/openai/whisper-medium.en | apache-2.0 | `2e98eb6279edf5095af0c8dedb36bdec0acd172b` | not read in full | Upstream of `Systran/faster-whisper-medium.en`. Systran says `mit` |
| `openai/whisper-large` (v1) | https://huggingface.co/openai/whisper-large | **Not verified** (not fetched) | not verified | not verified | Upstream named by `Systran/faster-whisper-large-v1` |
| `openai/whisper-large-v2` | https://huggingface.co/openai/whisper-large-v2 | apache-2.0 | `ae4642769ce2ad8fc292556ccea8e901f1530655` | not read in full | Upstream of `Systran/faster-whisper-large-v2`. Systran says `mit` |
| `openai/whisper-large-v3` | https://huggingface.co/openai/whisper-large-v3 | apache-2.0 (front matter, line 112 of the README) | `06f233fe06e710322aca913c1bc4249a0d71fce1` | Intended users: AI researchers. Caution against surveillance and "subjective classification" (line 499). Not recommended for high-risk domains (line 499). Repetition loops may occur (line 517). No minimum CPU or RAM stated; GPU speed-ups only (lines 306-459) | Upstream of `Systran/faster-whisper-large-v3`. **Licence mismatch**: Systran says `mit`, the upstream card says `apache-2.0` |
| `openai/whisper-large-v3-turbo` | https://huggingface.co/openai/whisper-large-v3-turbo | mit (Hub metadata) | `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` | not read in full | Upstream of `dropbox-dash/faster-whisper-large-v3-turbo` (the redirect target). Both say mit: **matches** |
| `distil-whisper/distil-large-v2` | https://huggingface.co/distil-whisper/distil-large-v2 | mit | `97d2c8f9cae1b0f6c8fc2e173495ee4cedc05843` | not read in full; the Parakeet-v2-style CC licence does not apply here | Upstream of `Systran/faster-distil-whisper-large-v2`. Both mit: matches |
| `distil-whisper/distil-large-v3` | https://huggingface.co/distil-whisper/distil-large-v3 | mit | `8031d2e6ce6631b7fc45629dddfc00271116d981` | not read in full | Upstream of `Systran/faster-distil-whisper-large-v3`. Matches |
| `distil-whisper/distil-large-v3.5` | https://huggingface.co/distil-whisper/distil-large-v3.5 | mit | `728a7691f3ff1d3d971528d3203a6e9559165d41` | not read in full | Upstream of `distil-whisper/distil-large-v3.5-ct2`. The ct2 card cites MIT inherited from OpenAI Whisper (line 65). Matches on the field |
| `distil-whisper/distil-medium.en` | https://huggingface.co/distil-whisper/distil-medium.en | mit | `6e61418885eaf4d5cc9f64e508e80ac5b4c052b7` | not read in full | Upstream of `Systran/faster-distil-whisper-medium.en` (matched by repository name; the Systran card was not read) |
| `distil-whisper/distil-small.en` | https://huggingface.co/distil-whisper/distil-small.en | mit | `9e4a67ca4569c30be43a3fe7fba1621e504f0093` | not read in full | Upstream of `Systran/faster-distil-whisper-small.en` |

Observation for the record: for the non-distil Whisper family, the code is MIT (OpenAI),
the upstream weights cards are Apache-2.0, and every Systran conversion card says MIT.
The conversion card's licence field does not match its upstream card. This document does
not decide which licence governs the weights; it records what the cards say.

## Table A4: benchmarked by YazSes, not used at runtime

| Model | Official URL | Licence (as stated) | Revision (sha) | Benchmark file | Note |
|---|---|---|---|---|---|
| `steja/whisper-small-persian` (fine-tune, converted to CTranslate2 int8 for the benchmark) | https://huggingface.co/steja/whisper-small-persian | apache-2.0 (Hub metadata) | `8c600b6b69f552730abab77a6a46311d673ea584` (2024-11-28); the MANIFEST says `rev 8c600b6b`, which is a prefix of this sha | `paper/results/persian-cvfa-test10559-steja-small.json`, `persian-fleurs-test871-steja-small.json` | Not in `WHISPER_MODELS`; not shipped as a default; the conversion was done for the benchmark only |

## Table B: candidates, NOT used, NOT recommended

Candidate - requires licence review and independent benchmark; no evidence of fitness.
A Hub model existing is not evidence of accuracy or licence suitability. Model cards are
self-reported; none of the figures below was reproduced.

| Track | Candidate (Hub id) | Licence field | Revision (sha, 2026-10-28) | Status and reason |
|---|---|---|---|---|
| Camera/gaze | `litert-community/L2CS-Gaze360-LiteRT` (base model Ahmednull/L2CS-Net) | mit | `f0c19a658e0a67c913e5704b051378200021e85d` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Upstream L2CS-Net licence not verified. On-device timings are the publisher's own |
| Camera/gaze | `BcantCode/GazeInceptionLite` | mit | `89bf6c3a4ad1313bfdc5346f6dd5bab036029b3c` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Card says "clinical validation needed" and "requires separate face/eye detection" |
| Camera/gaze | `Skulleton12/mediapipe-face-landmarker` (a `face_landmarker.task` re-upload) | apache-2.0 | `e8098a34013a130b8d8c88de0772f162b450dfad` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Card has no provenance text. The file size equals the Google asset's `Content-Length` (3,758,596 bytes); the hash was not compared |
| Camera/gaze | `jkyy/actb-face-landmarker` (a `face_landmarker.task` re-upload) | apache-2.0 | `20cb28de63b6989ad8b3e6692ec4e15b9513d424` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Card (in Chinese) says the weights were re-hosted from Google's MediaPipe release under Apache-2.0; this is a third-party statement and was not checked against Google. Same size and LFS SHA-256 as the row above |
| EEG | `braindecode/eegpt-pretrained` | bsd-3-clause | `e41cb3ae2ce4fd9eb736862292c91f8128d15618` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Pretrained EEG model for `braindecode`; no EEG task, electrode set or accuracy was checked |
| EMG | `braindecode/VEMG2Pose-emg2pose` | cc-by-nc-sa-4.0 | `12043578f59ad21c206aa3229196d1736da0ff70` | Candidate - requires licence review and independent benchmark; no evidence of fitness. Card: weights are Meta's, under CC BY-NC-SA 4.0 (non-commercial, share-alike); UmeTrack labels CC BY-NC 4.0 (lines 35-38) |

Search results with no relevant hit: `openseeface` returned 0 models (search API, 2026-10-28), so
**none identified** for OpenSeeFace. EEG and EMG keyword searches returned many unrelated
hits (for example GGUF language models for "em" in German), which were not padded into the
table.

## Offline and cache behaviour

- **Where models live.** The Hub cache is `HF_HUB_CACHE`, else `HF_HOME/hub`, else
  `$XDG_CACHE_HOME/huggingface/hub` (default `~/.cache/huggingface/hub`).
  `src/yazses/stt/download.py:149-167` (`hub_cache_dir`). `docs/models.md:62-63` says the
  same path on Linux, macOS and Windows.
- **Default engine.** `src/yazses/config.py:23` (`engine = "faster-whisper"`) and
  `src/yazses/config.py:43` (`model = "base.en"`).
- **Whisper load, cache first.** `src/yazses/stt/faster_whisper.py:40-44` calls
  `WhisperModel(..., local_files_only=True)` first. If that raises, it logs "not in the
  local cache; downloading it once" (line 63) and calls `WhisperModel` again with network
  access (line 66). Errors are mapped to `ModelUnavailableError` (lines 67-83). The module
  docstring (`faster_whisper.py:16-31`) records a measured hang on a cached model when the
  hub was consulted on every start.
- **Explicit download.** `src/yazses/stt/download.py:201-214` (`download_stt_model`) calls
  `faster_whisper.utils.download_model(name)` **without a `revision` argument**
  (`download.py:212`). faster-whisper 1.2.1 defaults `revision` to `None`
  (`faster_whisper/utils.py:54`), which resolves to the repository's default branch at the
  time of download.
- **No revision pins anywhere in the loaders.** Searched `src/yazses/stt`,
  `src/yazses/recimport`, `src/yazses/gaze`, `src/yazses/perception`,
  `src/yazses/voiceprint`, `src/yazses/meeting` for `revision`, `sha`, `checksum`, `sha256`:
  none in the model-loading code. Hub loads are therefore floating. The sherpa and
  MediaPipe URLs are versioned by path or tag but carry no hash.
- **Parakeet.** `src/yazses/stt/parakeet.py:152-195`. `onnx_asr.load_model` has no offline
  switch (comment at `parakeet.py:188-190`), so the whole load is wrapped in
  `load_cache_first` (`parakeet.py:194`). No revision argument (`parakeet.py:164`, `:173`).
- **Moonshine.** `src/yazses/stt/moonshine.py:131-147` wraps the load in `load_cache_first`.
  The package's own download (`moonshine_onnx/model.py:5-9`) does not pass a revision.
- **Shared mechanism.** `src/yazses/system/hfcache.py:135-157` (`load_cache_first`). It first
  runs the load with `HF_HUB_OFFLINE=1` (through `cache_first`, lines 82-133). On failure it
  logs and retries online (lines 149-157). If the user already set offline mode, it does not
  retry (lines 143-144). The flag is process-global during the load (module docstring,
  `hfcache.py:33-36`).
- **Gated pyannote.** `src/yazses/recimport/pyannote_backend.py:81` (token env names),
  `:108` (`token=True` uses the stored login), `:162-163` (the user must accept conditions on
  both repositories), `:196` (load through `load_cache_first`).
- **ECAPA.** `src/yazses/voiceprint/ecapa.py:27-31`, through `load_cache_first`.
- **Sherpa diarization (default).** Models are not fetched by the diarizer at run time.
  `src/yazses/recimport/diarizer.py:30-37` (`model_dir`, from the platform data directory
  `diarization/`, or `[recimport] model_dir`). `SherpaDiarizer` raises `FileNotFoundError`
  when the files are missing (`diarizer.py:~88-95`) and points at
  `yazses transcribe --download-models`. The download itself is `recimport/download.py:30-45`,
  using `urllib`, no checksum.
- **MediaPipe FaceLandmarker.** `src/yazses/gaze/download.py:121-130` fetches once into the
  user cache (`model_dir`, `download.py:44-47`, plus `.part` and a minimum size of 1,000,000
  bytes, `MIN_MODEL_BYTES`, `download.py:39`). A truncated transfer is rejected when
  `Content-Length` disagrees (`download.py:112-118`). No checksum. Construction of the
  backends calls it: `src/yazses/gaze/mediapipe_backend.py:36`,
  `src/yazses/perception/mediapipe_backend.py:120`.
- **Silero (faster-whisper bundled).** No download; the ONNX file ships in the package
  (`faster_whisper/assets/silero_vad_v6.onnx`). `src/yazses/recimport/audio_io.py:131-160`
  says the same.
- **Silero (optional package).** `src/yazses/meeting/silero_vad.py:5-8` docstring says the
  wheel carries the ONNX and no model is downloaded. Not verified in this pass (package not
  installed).
- **Repository-level rule.** `AGENTS.md` (Non-negotiable rule 1) requires that outbound
  network paths are registered and classified in ADR-019
  (`design/adr/adr-019-egress-inventory-and-escalation.md`). The gaze download is named in
  `src/yazses/gaze/mediapipe_backend.py:21-24` as the one outbound path there. That ADR was
  not read in this pass.

## Verification log

All requests were GET (or HEAD where marked). No Hugging Face token was used. No upload
or write request was made. Status is the HTTP status observed on 2026-10-28.

Hugging Face public API (`/api/models/<id>`), 200 unless noted:

- `Systran/faster-whisper-tiny`, `-tiny.en`, `-base`, `-base.en`, `-small`, `-small.en`, `-medium`, `-medium.en`, `-large-v1`, `-large-v2`, `-large-v3`, `faster-distil-whisper-large-v2`, `faster-distil-whisper-large-v3`, `faster-distil-whisper-medium.en`, `faster-distil-whisper-small.en`: all 200.
- `distil-whisper/distil-large-v3.5-ct2`: 200.
- `mobiuslabsgmbh/faster-whisper-large-v3-turbo`: **307** (redirect); followed to `dropbox-dash/faster-whisper-large-v3-turbo`: 200.
- `UsefulSensors/moonshine`: **307** (redirect); followed to `moonshine-ai/moonshine`: 200.
- `nvidia/parakeet-tdt-0.6b-v2`: 200. `nvidia/parakeet-tdt-0.6b-v3`: 200.
- `istupakov/parakeet-tdt-0.6b-v2-onnx`: 200.
- `speechbrain/spkrec-ecapa-voxceleb`: 200.
- `pyannote/speaker-diarization-3.1`: 200 (metadata). `pyannote/segmentation-3.0`: 200 (metadata).
- `openai/whisper-large-v3`: 200. `openai/whisper-tiny`, `-tiny.en`, `-base`, `-base.en`, `-small`, `-small.en`, `-medium`, `-medium.en`, `-large-v2`, `-large-v3-turbo`: 200 (metadata).
- `distil-whisper/distil-large-v3`, `-distil-large-v2`, `-distil-large-v3.5`, `-distil-small.en`, `-distil-medium.en`: 200 (metadata).
- `litert-community/L2CS-Gaze360-LiteRT`, `BcantCode/GazeInceptionLite`, `jkyy/actb-face-landmarker`, `Skulleton12/mediapipe-face-landmarker`, `braindecode/eegpt-pretrained`, `braindecode/VEMG2Pose-emg2pose`: 200.
- `Skulleton12/mediapipe-face-landmarker?blobs=true`, `jkyy/actb-face-landmarker?blobs=true`: 200 (file size and LFS SHA-256 of `face_landmarker.task`).
- `steja/whisper-small-persian`: 200.
- Hugging Face search: `api/models?search=gaze`, `face+landmarker`, `openseeface`, `eeg`, `emg`; `api/datasets?search=eeg`, `emg`: all 200.

Hugging Face raw model cards (`/<id>/raw/main/README.md`):

- Systran (15 repos), `distil-whisper/distil-large-v3.5-ct2`, `nvidia/parakeet-tdt-0.6b-v2`, `nvidia/parakeet-tdt-0.6b-v3`, `istupakov/parakeet-tdt-0.6b-v2-onnx`, `speechbrain/spkrec-ecapa-voxceleb`, `openai/whisper-large-v3`: 200.
- `mobiuslabsgmbh/faster-whisper-large-v3-turbo`: 307, followed to `dropbox-dash/...`: 200.
- `UsefulSensors/moonshine`: 307, followed to `moonshine-ai/moonshine`: 200.
- `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`: **401** (gated; not read).
- `Skulleton12/mediapipe-face-landmarker`, `jkyy/actb-face-landmarker`, `litert-community/L2CS-Gaze360-LiteRT`, `braindecode/VEMG2Pose-emg2pose`, `braindecode/eegpt-pretrained`, `BcantCode/GazeInceptionLite`: 200.

Other hosts:

- `https://raw.githubusercontent.com/openai/whisper/main/LICENSE`: 200 (MIT License, Copyright 2022 OpenAI).
- `https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/master/LICENSE`: 200 (Apache License 2.0; code licence, not model licence).
- `https://raw.githubusercontent.com/modelscope/3D-Speaker/main/LICENSE`: 200 (Apache License 2.0; code licence, not model licence).
- `HEAD https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`: 200, `Content-Length: 3758596`, `ETag` `b0e7274907a1644404fef66b28dd6d85`, `Last-Modified: Wed, 03 May 2023 18:02:21 GMT`.
- `HEAD https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`: 200 (after redirects).
- `HEAD https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`: 200 (after redirects).

Local (no network) checks in the worktree:

- `faster_whisper/utils.py` `_MODELS` (faster-whisper 1.2.1 in `.venv`) compared with `src/yazses/stt/download.py:47-67`: same keys and repository ids (19 keys each; identical key set and repository ids).
- `faster_whisper/assets/silero_vad_v6.onnx`: SHA-256 and size recorded above.
- `.venv/lib/python3.14/site-packages/moonshine_onnx/model.py`: repository id and file layout.

## Not verified

- **Parakeet ONNX source.** Which repository `onnx-asr` fetches for `nemo-parakeet-tdt-0.6b-v2`, and at which revision. `onnx-asr` is not installed in this worktree.
- **Moonshine redirect.** Whether `UsefulSensors/moonshine` → `moonshine-ai/moonshine` is permanent, and whether the `onnx/merged/base/float` files are unchanged since the package was released.
- **`mobiuslabsgmbh` redirect.** Same questions for `mobiuslabsgmbh/faster-whisper-large-v3-turbo` → `dropbox-dash/...`.
- **Gated pyannote model bodies.** Model card text (intended use, limits, hardware) of `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` was not read (HTTP 401 without a token). Only Hub metadata (MIT, gated) was read.
- **Licence of sherpa-hosted conversions.** The sherpa-onnx segmentation 3.0 and 3D-Speaker ERes2Net `.onnx` files: licence of the weights not read; only the code licences were fetched.
- **MediaPipe FaceLandmarker licence and hash.** Google's terms for the `.task` file were not read. The file was not downloaded, so its SHA-256 and MD5 were not recomputed; only the HTTP headers were recorded.
- **Silero VAD licence.** Not read. The `silero-vad` package was not installed or fetched.
- **L2CS-Net.** Upstream origin, weights, licence and revision were not verified; the `l2cs` package was not installed.
- **Upstream `openai/whisper-large` (v1), and the full text of most upstream Whisper cards.** Only licence fields and selected sections were read.
- **Parakeet, Moonshine, ECAPA hardware figures for CPU.** Not stated in the cards read; no CPU figure is given here.
- **Whether any optional model is active by default for a user.** Gaze and perception are off by default (`config.py:653`); whether the voiceprint and diarization features are on for a default install was not traced.
- **Benchmark-to-revision link.** Result files record model names, not Hub repositories or revisions, except the Persian `cvfa-small` file (see Table A1). Benchmarked numbers cannot be tied to a sha.
- **Candidate fitness.** None of the Table B candidates was run, benchmarked or validated; their card figures are self-reported.
- **EEG and EMG search coverage.** Keyword searches only; not a survey.
