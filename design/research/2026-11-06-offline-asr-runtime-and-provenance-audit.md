# Research: shipped offline ASR runtimes and checkpoints: versions, licences and revision pinning

**Status:** Research note (not a decision). ADR-030 freeze unchanged; no default, dependency, pin or engine is changed and no new engine is proposed.
**Issue:** [NEXT-ASR-01 #792](https://github.com/MSKazemi/yazses/issues/792); parent [#787](https://github.com/MSKazemi/yazses/issues/787); numeric claims belong to [#793](https://github.com/MSKazemi/yazses/issues/793).
**Snapshot:** YazSes `main` at `4695e49adb368c048f156b9aff4a9d079d6260db`; upstream metadata read **2026-11-06**.
**Complements, does not repeat:** the [2026-11-03 runtime/provenance snapshot](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md), which surveys *candidate* runtimes (NeMo-Speech.cpp, parakeet.cpp, Moonshine Voice) and the Parakeet v2/v3 and Nemotron licences. This note covers what that one did not: the **versions YazSes actually resolves today** for its four shipped ASR packages, compared with the current upstream release, and the **exact checkpoint each shipped engine downloads** with its licence and whether it is pinned to a revision. [`docs/models.md`](../../docs/models.md) states that it does not record these details.
**Not done:** no model or wheel was installed or run and no benchmark was taken. This note contains no WER, latency or memory numbers. Upstream metadata was read through the public PyPI JSON API, the Hugging Face model API, the GitHub REST API and one PyPI source distribution (onnx-asr 0.12.0), which was unpacked and read.

## Evidence labels

- **[Fact]**: read directly from a primary source (YazSes source at the snapshot, `uv.lock`, the PyPI/Hub/GitHub API response, the published sdist or wheel) on the date above. Upstream values can change after that date.
- **[Vendor claim]**: an upstream statement about its own software that YazSes has not tested.
- **[Theory]**: an inference from facts, not checked by running anything.
- **[Unverified]**: open, with what would settle it.

## 1. Packages: declared floor vs locked vs current upstream

| Package | How YazSes gets it | Floor in `pyproject.toml` | Resolved in `uv.lock` | Current on PyPI (upload date) | Licence (PyPI metadata) | Delta |
|---|---|---|---|---|---|---|
| `faster-whisper` | base dependency | `>=1.2.1` | 1.2.1 | **1.2.1** (2025-10-31) | MIT | none |
| `ctranslate2` | transitive, through faster-whisper (`ctranslate2<5,>=4.0`) | none of its own | 4.8.1 | **4.8.5** (2026-11-02) | MIT | 4 patch releases behind |
| `onnx-asr` | `parakeet` extra, `onnx-asr[cpu,hub]` | `>=0.12` | 0.12.0 | **0.12.0** (2026-07-15) | MIT | none (unreleased `main` work below) |
| `useful-moonshine-onnx` | `moonshine` extra | `>=20251121` | 20251121 | **20251121** (2025-11-21) | MIT | none |
| `onnxruntime` | transitive (onnx-asr, useful-moonshine-onnx, faster-whisper); declared directly in the `tts`, `silero` and `all` extras | `>=1.27.0`; `>=1.23.2,<1.24` on Intel macOS | 1.28.0; 1.23.2 on Intel macOS | **1.31.1** (2026-10-26) | MIT | 3 minor releases behind (Intel macOS cap is deliberate) |

All values in this table are **[Fact]**. Sources: the `[[package]]` entries in `uv.lock`; `pyproject.toml` lines 70, 201–208 and 287–301; and `https://pypi.org/pypi/<name>/json` for each package. The licences are PyPI's `license` / `license_expression` fields, not a reading of each project's LICENSE file. The installed `.venv` dist-info for faster-whisper, ctranslate2 and useful-moonshine-onnx reports the same versions and the same MIT licence. onnx-asr is not installed in the base venv.

Notes on the deltas:

- **ctranslate2 4.8.1 → 4.8.5.** The v4.8.5 release notes are **[Vendor claim]**. Their new features cover "Drama 3" prompt caching and voice cloning. The fixes are CUDA FP16/BF16 attention precision, a caching-allocator shutdown crash, and an eole converter fix ([release page](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.5)). **[Theory]** None of these targets the CPU int8 Whisper path YazSes uses by default. **[Unverified]** I did not read the 4.8.2–4.8.4 notes. Before calling the lag harmless, read them and run the full suite on a refreshed lock.
- **onnxruntime 1.28.0 → 1.31.1.** **[Fact]** 1.31.1 still declares `requires_python >=3.11`, so the project's Python floor does not block it. The Intel macOS cap below 1.24 is documented in `pyproject.toml`: upstream stopped publishing an x86_64 macOS wheel after 1.23.0. That cap is a compatibility pin, not a lag. **[Unverified]** Whether anything in this lock holds the other platforms at 1.28.0, or the lock simply has not been refreshed. Running `uv lock --upgrade-package onnxruntime` in a throwaway checkout would answer it. That step is the coordinator's or owner's, because workers may not change `uv.lock`.
- **onnx-asr, unreleased.** **[Fact]** On `main`, commit [`6e63052`](https://github.com/istupakov/onnx-asr/commit/6e63052eb760) (2026-10-21, "Add subfolder and revision support for model loading") adds `revision=` and `subfolder=` keywords to `onnx_asr.load_model`. **[Fact]** The released 0.12.0 sdist's `load_model` (`src/onnx_asr/loader.py:306`) has neither keyword, and it has no `offline=` either. Its resolver supports offline mode internally (`resolver.py:48–77`), but `load_model` does not pass it through. That matches the `stt/parakeet.py` comment that "`onnx_asr.load_model` exposes no offline switch", and it is why YazSes wraps the load in `system/hfcache.load_cache_first`.
- **useful-moonshine-onnx dependencies.** **[Fact]** Its PyPI `requires_dist` and the `uv.lock` entry both list `huggingface-hub`, `librosa`, `numba`, `onnxruntime` and `tokenizers`. The comment above the `moonshine` extra (`pyproject.toml:295`) says "onnxruntime + tokenizers only — no torch, no numpy ceiling". The "no torch" part holds. The "only" part does not: librosa and numba come in as well. That is a comment correction for whoever owns `pyproject.toml`; this note does not change it.

## 2. Checkpoints the shipped engines actually download

| Engine (config value) | YazSes default name | Hub repository the library resolves | Hub commit at read (last modified) | Model-card licence | Pinned to a revision by YazSes? |
|---|---|---|---|---|---|
| `faster-whisper` | `base.en` (`stt/decoder_settings.py:40`) | `Systran/faster-whisper-base.en` (`stt/download.py:49`; faster-whisper's own `utils._MODELS` has the same mapping) | `3d3d5dee26484f91867d81cb899cfcf72b96be6c` (2023-11-23) | MIT | **No** |
| `parakeet` | `nemo-parakeet-tdt-0.6b-v2` (`stt/parakeet.py:39`) | `istupakov/parakeet-tdt-0.6b-v2-onnx` (onnx-asr 0.12.0 `resolver.py:29`), an ONNX conversion whose card names `base_model: nvidia/parakeet-tdt-0.6b-v2` | `0bbb45a3365852604aef28b538a8f066f4ccaa85` (2026-02-17); base model `ae9ad07059c7c739ffaf932226a8fe64ae2620b0` (2026-06-29) | CC-BY-4.0 (conversion and base) | **No** |
| `moonshine` | `moonshine/base` (`stt/moonshine.py:46`) | `UsefulSensors/moonshine`, subfolder `onnx/merged/base/float` (hard-coded in `moonshine_onnx/model.py`, 20251121). The Hub API now answers `Temporary Redirect … /api/models/moonshine-ai/moonshine` | `48b4e427b587bcf67797a5be706d6ddc4a298149` (2025-11-30, at `moonshine-ai/moonshine`) | MIT | **No** |

Every cell is **[Fact]**: commit hashes, dates and licences come from `https://huggingface.co/api/models/<repo>` (the `sha`, `lastModified` and `license:` tag / `cardData.license`). The commit hash is the repository's **head** on the read date, not necessarily the commit an existing user's cache holds.

Points that follow from the table:

1. **No shipped checkpoint is pinned. [Fact]** `stt/faster_whisper.py`, `stt/parakeet.py`, `stt/moonshine.py` and `stt/download.py` never pass a revision, so every first download takes the repository's default branch. Cache-first loading (`system/hfcache.py`) then keeps whatever was fetched. **[Theory]** Two users who installed on different dates can therefore run different weights under the same engine name with no visible signal. The risk differs by engine. The Systran repo has not changed since 2023. The Parakeet conversion repo changed in February 2026 and its NVIDIA base in June 2026. Moonshine's repo has changed owner.
2. **What each library allows today. [Fact]** faster-whisper 1.2.1 `WhisperModel` accepts `revision=` (`faster_whisper/transcribe.py:632`). onnx-asr 0.12.0 `load_model` does not (it is unreleased on `main`). useful-moonshine-onnx 20251121 calls `hf_hub_download` with no revision and exposes no parameter for one. So of the three shipped engines, only the Whisper path can be revision-pinned without upstream changes. **[Theory]** Pinning in the product is a behaviour change: existing caches would need a migration story, and choosing a revision is a maintainer decision. It is **not proposed here**. The low-cost step that stays in scope is for the [#793](https://github.com/MSKazemi/yazses/issues/793) evaluation manifest to record the resolved snapshot commit and file digests per run. The 2026-11-03 note already requires that.
3. **The Moonshine repository redirect. [Fact]** A request to `UsefulSensors/moonshine` is redirected to `moonshine-ai/moonshine`. **[Unverified]** Whether `huggingface_hub.hf_hub_download`, at the version in the lock (1.23.0), follows that redirect for file downloads in a fresh cache, and whether an existing cache stored under the old repo name keeps working, has not been tested. A download test in an isolated `HF_HOME` would settle both. If the Hub ever drops the redirect, `stt-moonshine` first-time setup breaks with no change on YazSes's side.
4. **The Whisper weight licence is stated two ways upstream. [Fact]** The Systran conversion card says MIT. The `openai/whisper-base.en` Hub card carries an `apache-2.0` tag. The [openai/whisper GitHub repository](https://github.com/openai/whisper) LICENSE is MIT (GitHub licence API, `spdx_id: MIT`). **[Unverified]** Which statement governs the weights is a legal question, not an engineering one. YazSes does not redistribute weights, because the user's machine downloads them from the Hub, so this only matters if bundling weights is ever proposed.
5. **The Parakeet weights are CC-BY-4.0. [Fact]** Both the conversion and the NVIDIA base model are CC-BY-4.0, which requires attribution. **[Theory]** YazSes does not redistribute them, so it has no attribution duty today. The research page `docs/research/voice-control.md` already labels Parakeet "CC-BY-4.0". Any future bundling or mirroring would need an attribution notice; see the requirements table in the 2026-11-03 note.

## 3. What this changes, and for whom

No product change is proposed and no engine is recommended. Items for the coordinator or owner, all outside this note's write scope:

| # | Item | Kind | Who |
|---|---|---|---|
| 1 | Refresh `uv.lock` for `ctranslate2` (4.8.1 → 4.8.5) and `onnxruntime` (1.28.0 → 1.31.1, except the Intel macOS fork) under the "latest stable" dependency rule, then run the full suite and the FreeBSD missing-deps simulation | lock refresh | coordinator / owner |
| 2 | Correct the `moonshine` extra comment (`pyproject.toml:295`): the package also pulls `librosa`, `numba` and `huggingface-hub` | comment | owner of `pyproject.toml` |
| 3 | Re-check onnx-asr after its next release: if `load_model(revision=...)` ships, Parakeet becomes pinnable. Re-read `stt/parakeet.py`'s "no offline switch" comment against that release | watch | #792 / #798 |
| 4 | Test the Moonshine Hub redirect in an isolated `HF_HOME` (section 2, point 3) | test (needs network, in a sandbox) | maintainer |
| 5 | Record the snapshot commit and file digests per run in the #793 evaluation manifest | protocol | #793 |

## Sources (all read 2026-11-06)

- PyPI JSON: [faster-whisper](https://pypi.org/project/faster-whisper/), [ctranslate2](https://pypi.org/project/ctranslate2/), [onnx-asr](https://pypi.org/project/onnx-asr/), [useful-moonshine-onnx](https://pypi.org/project/useful-moonshine-onnx/), [onnxruntime](https://pypi.org/project/onnxruntime/). Read through `https://pypi.org/pypi/<name>/json`.
- [CTranslate2 v4.8.5 release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.5).
- [onnx-asr repository](https://github.com/istupakov/onnx-asr), its [tags](https://github.com/istupakov/onnx-asr/tags) (latest `v0.12.0`) and [commit 6e63052](https://github.com/istupakov/onnx-asr/commit/6e63052eb760). The onnx-asr 0.12.0 sdist on PyPI was read for `loader.py` and `resolver.py`.
- Model cards: [Systran/faster-whisper-base.en](https://huggingface.co/Systran/faster-whisper-base.en), [openai/whisper-base.en](https://huggingface.co/openai/whisper-base.en), [istupakov/parakeet-tdt-0.6b-v2-onnx](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx), [nvidia/parakeet-tdt-0.6b-v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2), [moonshine-ai/moonshine](https://huggingface.co/moonshine-ai/moonshine) (formerly `UsefulSensors/moonshine`).
- [openai/whisper repository](https://github.com/openai/whisper), licence via the GitHub REST API.
- YazSes at `4695e49a`: `pyproject.toml`, `uv.lock`, `src/yazses/stt/{faster_whisper,parakeet,moonshine,download,decoder_settings}.py`, `src/yazses/system/hfcache.py`, `docs/models.md`. Also the installed `faster_whisper` 1.2.1 and `moonshine_onnx` 20251121 sources in the project venv.
