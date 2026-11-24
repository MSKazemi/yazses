# Research: Moonshine v2 upgrade spike (`useful-moonshine-onnx` → `moonshine-voice`)

**Status:** RESEARCH SPIKE — REVIEW PENDING. No dependency, extra, pin, default, config key
or engine code is changed by this note. The diff in §7 is a proposal for whoever does the
upgrade, after the measurement in §6 has been run.

**Plan item:** M1 in the [2026-11-19 start plans](2026-11-19-landscape-start-plans.md)
(upgrade half: steps 1–2; streaming half: the addendum to the
[streaming delivery boundary candidate](2026-11-03-proposed-adr-streaming-delivery-boundary.md)).
**Governing records:** [ADR-030 breadth freeze](../adr/adr-030-agent-era-direction.md),
[ADR-033 reproducible ASR evaluation gate (proposed)](../adr/adr-033-reproducible-asr-evaluation-gate.md),
[ADR-019 egress inventory](../adr/adr-019-egress-inventory-and-escalation.md).
**Base:** branch `research/landscape-2026-11` at `af322ca1` (main at `8ecfd4ae`, YazSes 2.51.0).
**Read on:** 2026-11-20, unauthenticated. PyPI was read via its JSON API. Three published
wheels of `moonshine-voice` 0.1.6 (Linux x86_64, Windows x86_64, macOS arm64) were
downloaded into a scratch directory and **unpacked and read as text, never installed or
executed**. No model weights were downloaded, so no WER or latency figure appears here.

Labels: **[Fact]** is what a cited source or the unpacked wheel says on the read date.
**[Inference]** is a conclusion drawn from facts. **[Proposal]** is a suggested change.
**[Vendor claim]** is a publisher's statement about its own artefact, not checked.

## 1. Answer in one paragraph

`moonshine-voice` 0.1.6 (2026-11-06, MIT) is a ctypes binding over a native
`libmoonshine` that **bundles its own ONNX Runtime 1.23.2** and declares no `onnxruntime`
dependency, so it does not touch the repository's `onnxruntime` constraint. Wheels exist for
Linux x86_64 (glibc ≥ 2.34), Linux aarch64 (glibc ≥ 2.31), macOS arm64 (macOS ≥ 15) and
Windows x86_64. **There is no Intel macOS wheel and no sdist**, so a straight swap would
remove Moonshine from Intel Macs. The English tiny/base and every streaming model are MIT.
Models come from the package's own CDN (`download.moonshine.ai`), not from Hugging Face,
which changes an ADR-019 row and the manifest row. The migration is **not trivially small**:
it is small in `stt/moonshine.py` but touches the egress inventory, the model manifest, the
cache-first guard, the feature map and the extras. So this spike changes no code, and §7
spells out the diff instead.

## 2. Package facts

| Field | `useful-moonshine-onnx` (shipped) | `moonshine-voice` (candidate) |
|---|---|---|
| Latest version | 20251121 (2025-11-21) | **0.1.6** (2026-11-06); 41 releases since early 2026 |
| Licence (code) | MIT | MIT ([LICENSE](https://github.com/moonshine-ai/moonshine)) |
| `Requires-Python` | ≥ 3.8 | ≥ 3.8; classifiers list 3.8–3.12 only |
| Wheel tag | `py3-none-any` (pure Python) | `py3-none-<platform>`: Python-ABI-agnostic, native code loaded via ctypes |
| Runtime | `onnxruntime` (unversioned dep) + `tokenizers`, `numba`, `librosa`, `huggingface-hub` | Bundled ONNX Runtime **1.23.2**; deps `numpy`, `sounddevice`, `requests`, `tqdm`, `filelock`, `platformdirs`, `google-crc32c` |
| Model format | ONNX from the Hub (`UsefulSensors/moonshine`) | ORT format (`.ort`) from `download.moonshine.ai` |
| Model fetch | `hf_hub_download`, no revision | `requests.get(..., timeout=30)` against a catalog compiled into `libmoonshine`, verified by size and CRC32C |
| Built-in extras | none | VAD line segmentation, streaming, word timestamps, keyterm boosting, speaker identification, spelling model, TTS |

Sources: [PyPI `moonshine-voice`](https://pypi.org/project/moonshine-voice/),
[PyPI `useful-moonshine-onnx`](https://pypi.org/project/useful-moonshine-onnx/),
[GitHub moonshine-ai/moonshine](https://github.com/moonshine-ai/moonshine). The runtime row
for `moonshine-voice` comes from the unpacked wheels: `moonshine_voice.libs/libonnxruntime-13ab8084.so.1`
(Linux), `moonshine_voice/onnxruntime.dll` (Windows) and
`moonshine_voice/libonnxruntime.1.23.2.dylib` (macOS). **[Fact]**

### 2.1 Wheel matrix (0.1.6)

| Platform | Wheel | Floor | Python 3.11 / 3.12 / 3.13 / 3.14 |
|---|---|---|---|
| Linux x86_64 | `manylinux_2_34_x86_64` (20.0 MB) | glibc 2.34 (Ubuntu 22.04, Debian 12, RHEL 9 and later) | installable on all four (`py3-none` tag) |
| Linux aarch64 | `manylinux_2_31_aarch64`, `manylinux_2_34_aarch64` | glibc 2.31 | installable on all four |
| macOS arm64 | `macosx_15_0_arm64` (18.7 MB) | **macOS 15** | installable on all four |
| macOS x86_64 | **none**. A `universal2` wheel last shipped in 0.0.59 (2026-04-20) | — | **no wheel** |
| Windows x86_64 | `win_amd64` (16.6 MB) | — | installable on all four |
| Any other (FreeBSD, Windows arm64) | none, and no sdist | — | no wheel |

**[Fact]** for tags and sizes. **[Inference]** for the Python column: a `py3-none` wheel
installs on every CPython 3.x, and the binding uses only `ctypes`, so no C-API version is
involved. But upstream declares nothing past 3.12, so 3.13 and 3.14 are *installable*, not
*tested upstream*. All the declared dependencies are already in `uv.lock` except
`google-crc32c`, which publishes cp311–cp315 wheels (1.9.0).

SHA-256 of the three wheels that were read, for whoever repeats this:
`04e438f3…edf6c7` (Linux x86_64), `29a54f92…a2cfc` (Windows), `71f0fa9d…00ff4` (macOS arm64).

### 2.2 Runtime and the `onnxruntime` constraint

- **No resolver conflict.** `pyproject.toml` `[tool.uv] constraint-dependencies` caps
  `onnxruntime<1.24` on Intel macOS only, because `useful-moonshine-onnx`, `onnx-asr` and
  `kokoro-onnx` pull an unversioned `onnxruntime`. `moonshine-voice` does not depend on the
  `onnxruntime` distribution, so the constraint neither helps nor blocks it. Once
  `useful-moonshine-onnx` is gone, the constraint's comment loses one of its three names
  but the constraint is still needed for the other two. **[Fact]**
- **Two ONNX Runtimes in one process.** With Parakeet, Kokoro read-back or sherpa-onnx
  diarization enabled, the process loads the pip `onnxruntime` (1.28.0 in the lock) *and*
  the bundled 1.23.2. On Linux the bundled copy has an auditwheel hash in its soname and on
  macOS a versioned name, so they should load side by side. **On Windows the bundled file
  is a plain `onnxruntime.dll`**, the same base name as the pip package's DLL. Windows may
  resolve `moonshine.dll`'s import to whichever `onnxruntime.dll` is already loaded.
  **[Inference — needs a test on Windows with Parakeet and Moonshine both loaded.]** The ORT C
  API is versioned, so a newer DLL standing in would probably work. That is a hope, not a
  measurement.
- **Install footprint.** The swap drops `numba`, `llvmlite`, `librosa` and `tokenizers` from
  the Moonshine closure and adds about 20 MB of wheel. **[Inference]** `make feature-sizes`
  is the measurement.

## 3. Models and licences

The catalog compiled into `libmoonshine` 0.1.6 lists these English speech models. **[Fact]**
They are read from the wheel's embedded URLs.

| Arch (`ModelArch`) | Generation | CDN path | Licence |
|---|---|---|---|
| `tiny`, `base` | legacy, non-streaming (v1 weights re-exported to `.ort`) | `model/{tiny,base}-en/quantized/` | MIT |
| `tiny-streaming` | **v2** | `model/tiny-streaming-en/quantized_26_11_02/` | MIT |
| `small-streaming` | **v2** | `model/small-streaming-en/quantized_26_11_02/` | MIT |
| `medium-streaming` | **v2** | `model/medium-streaming-en/quantized_26_11_02/` | MIT |

- **There is no v2 "base".** The plan says "v2 tiny/base". The v2 English sizes are tiny,
  small and medium streaming. `ModelArch.BASE_STREAMING` exists in the enum but has no
  English model in the catalog. The benchmark (§6) therefore measures `base` (old weights,
  new runtime) as a control as well as the three v2 sizes.
- **Licence split.** Per the repository [LICENSE](https://github.com/moonshine-ai/moonshine),
  all speech-to-text models are MIT unless listed. That includes all streaming models in
  every language, and English tiny and base. The **legacy non-streaming non-English** models
  are under the Moonshine Community License: Arabic, Japanese, Korean, Mandarin, Ukrainian
  and Vietnamese base and tiny, plus Spanish base. It is described as non-commercial, but
  section III grants commercial use after registration, ending above USD 1 M annual revenue.
  **[Fact]**
- **Upstream's own warning is coarser than its licence.** `get_model_for_language` prints the
  Community License notice for *any* language other than `en`, even for MIT streaming
  models. **[Fact, from `download.py`.]** YazSes should not inherit that rule. It should hard-code
  `en` until the model-manifest licence process has cleared a row (§7, step 2).
- **Revision and integrity.** The streaming paths are date-stamped (`quantized_26_11_02`),
  which works as a revision. The catalog verifies by size and **CRC32C, which is not a
  cryptographic hash**. The manifest wants a SHA-256 that YazSes pins itself. **[Inference]**
- **v2 evidence.** The [Moonshine v2 paper](https://arxiv.org/abs/2602.12241) claims sliding-window
  attention gives bounded time-to-first-token and accuracy "on-par with models 6x their
  size". The abstract gives no x86 CPU latency. **[Vendor claim]** The YazSes published
  `moonshine/base` figure (3.17 % WER on the historical set, `docs/benchmarks.md`) is the
  number v2 has to beat or match.

## 4. Python API (0.1.6, read from the wheel)

```python
import moonshine_voice as mv
path, arch = mv.get_model_for_language("en", mv.ModelArch.SMALL_STREAMING)   # network on a cache miss
t = mv.Transcriber(model_path=path, model_arch=arch)                          # options={...} for VAD etc.

# batch
lines = t.transcribe_without_streaming(samples_list, 16000).lines            # list[TranscriptLine]
text = " ".join(l.text for l in lines)

# streaming
s = t.create_stream(update_interval=0.5)
s.add_listener(callback)          # LineStarted / LineUpdated / LineTextChanged / LineCompleted
s.start(); s.add_audio(chunk_list, 16000); ...; final = s.stop()            # stop() = last pass
```

Behaviour that matters for the adapter **[Fact]**:

- Audio crosses the binding as a Python `list` that is copied into a ctypes array
  (`(c_float * n)(*audio)`). That costs O(n) in Python per call. For a 60 s burst that is
  about a million floats per decode. It goes into the decode-time measurement, not around it.
- The transcriber **segments with its own VAD** into lines (`vad_threshold`,
  `vad_max_segment_duration` and others are C options). The 0.1 s / 64 s assertions that
  `stt/moonshine.py` works around are gone. In their place is a VAD that can, in principle,
  drop quiet speech. That is a behaviour change, and the benchmark has to catch it as
  deletions.
- `TranscriptLine.words` carries word start/end/confidence when the
  `word_timestamps` option is set, which needs an extra `decoder_with_attention.ort`
  download. That would let `transcribe_words` stop returning `[]`. Do it later, as its own change.
- Cache behaviour: `download_file` returns early, with no request, when the destination
  exists and matches the catalog size. A cached model therefore loads offline already. On a
  miss there is a 30 s connect timeout, not the unbounded hang `system/hfcache.py` exists to
  avoid. `get_model_for_language` **also best-effort prefetches a spelling model**, a second
  download nobody asked for.

## 5. Freeze and gate status

- **ADR-030:** the upgrade is a dependency change inside an advertised capability
  (`stt-moonshine`), so it is allowed under the freeze. Streaming partials are not, and stay
  in the addendum.
- **ADR-033 (proposed):** a model/engine dependency is not swapped without a matched
  measurement. Nothing here has been measured, and that is the next step (§6).

## 6. The measurement to run

`scripts/bench-moonshine-v2.py` (new, tested in `tests/test_bench_moonshine_v2.py`) runs the v2
arm *through* `scripts/bench-stt.py`. The fallback check, file accounting, normaliser and
per-file JSON are therefore identical to the v1 row's. It adds the ADR-033 provenance that
`bench-stt.py` lacks: a SHA-256 manifest of the weights and of the corpus, the
`moonshine-voice` version, and the bundled ORT file. `compare` pairs runs by file and
refuses unmatched corpora, different normalisers, fallbacks and partial coverage. It reports
ΔWER with a seeded paired bootstrap 95 % interval, resampled by file, and the JSON says so.
ADR-033 asks for speaker blocks wherever the corpus has speaker IDs. The `--streaming` pass
records release-to-final time, first-partial time, text changes and prefix retractions,
which are the inputs the streaming addendum needs.

Arms, English only, on the ADR-033 reference machine:

1. `bench-stt.py --engine moonshine --model moonshine/tiny` and `moonshine/base` (shipped), then `digest` the HF snapshot and the corpus into each JSON.
2. `bench-moonshine-v2.py run --arch base` (control: same weights, new runtime) and `--arch tiny`.
3. `bench-moonshine-v2.py run --arch {tiny,small,medium}-streaming --streaming`.
4. `bench-moonshine-v2.py compare v1-base.json <each v2 run>`.

Run the v2 arms in a separate virtualenv (`pip install moonshine-voice==0.1.6 jiwer numpy av
whisper-normalizer`). The package must not enter the YazSes environment before the swap.

**Decision rule — [Proposal], for the decision owner and not an accepted threshold:** swap
the extra when some v2 arch (or `base` on the new runtime) is within ADR-033's provisional
+0.5 pp non-inferiority margin of shipped `moonshine/base` and no worse on warmed decode
p95. Otherwise keep the shipped package and record the negative result.

## 7. The diff the upgrade would need — [Proposal]

None of this is applied. It is listed so that the PR after the measurement is mechanical.

1. **`pyproject.toml`**. Keep the old package as the Intel-mac fallback for at least one
   release, as the start plan's risk line suggests:
   ```toml
   moonshine = [
       "moonshine-voice>=0.1.6; sys_platform != 'darwin' or platform_machine != 'x86_64'",
       "useful-moonshine-onnx>=20251121; sys_platform == 'darwin' and platform_machine == 'x86_64'",
   ]
   ```
   Make the same change in `all` and the `dev` group, add `"moonshine_voice.*"` to the
   `[tool.mypy]` override list, regenerate `uv.lock`, and update the `[tool.uv]` comment.
   Wheel-less platforms (FreeBSD, Windows arm64, glibc < 2.34 x86_64) need a marker too, or
   `features enable stt-moonshine` fails at install and not at the factory's loud fallback.
2. **`src/yazses/stt/moonshine.py`**. Add a second backend selected by import:
   `moonshine_voice` first, then `moonshine_onnx`, imported in `__init__` so the factory's
   fallback still fires. Map `moonshine/tiny`/`moonshine/base` to `tiny`/`base`, and accept
   `moonshine/{tiny,small,medium}-streaming`. Always request `"en"`; that is the licence
   guard. `_decode_one` → `transcribe_without_streaming(waveform.tolist(), 16000)`, joining
   `lines`. Keep `_decode_long` until the measurement shows the built-in VAD makes it
   redundant. **Do not call `get_model_for_language` on the load path.** Resolve the cached
   path from `find_model_info`/the cache dir and fetch only on an explicit enable or
   `yazses model download`, without the spelling prefetch.
3. **`src/yazses/system/features.py:1261`**. Make the import probe and install spec for
   `stt-moonshine` platform-aware (`moonshine_voice` vs `moonshine_onnx`).
4. **ADR-019 and its guards.** Change the `stt/moonshine.py` loader row's destination to
   `download.moonshine.ai` (← Moonshine weights). Add `get_model_for_language` and
   `Transcriber` to the shared loader vocabulary used by `tests/test_egress_inventory.py`
   and `tests/test_model_cache_first.py`, and record that cache-first is now the package's
   own size check, not `hfcache`.
5. **`design/hci-huggingface/model-manifest.json`, row `moonshine-ai--moonshine`.** Update
   runtime format (`.ort`, bundled ORT 1.23.2), download method (CDN, CRC32C, date-stamped
   path) and the licence evidence (LICENSE per-model list). Add the SHA-256 that YazSes
   pins itself.
6. **Tests.** Add a `moonshine_voice` double next to the existing `moonshine_onnx` one in
   `tests/test_r7_stt_moonshine_long_tail.py`. Add a factory test that a missing
   `moonshine_voice` *and* `moonshine_onnx` still gives the loud fallback. Add
   `needs_moonshine_voice` to `tests/decoder_stack.py`, and `moonshine_voice` to
   `scripts/simulate-missing-deps.py`.
7. **Docs.** `docs/models.md`, `docs/benchmarks.md` (the measured table), `CHANGELOG.md`,
   `make feature-sizes`.

## 8. Risks and open questions

- **Intel macOS loses v2.** The fallback extra keeps v1 working there. Whether to keep it
  beyond one release is the owner's call.
- **macOS 15 floor** on the arm64 wheel. Machines on macOS 14 also fall back to v1, by the
  same marker logic, *if* uv's platform tags are evaluated at install. Check this on a
  macOS 14 runner.
- **Windows DLL name clash** (§2.2). Test it before the swap, with `[stt] engine = moonshine`
  plus Kokoro read-back enabled.
- **Built-in VAD dropping speech** in quiet dictation. The benchmark's deletion counts show
  it, and `options={"vad_threshold": ...}` is the knob.
- **Alpha status.** The package is "Development Status :: 3 - Alpha" and shipped 41 releases
  in roughly ten months. A `>=` floor (rule 4) will pick up breaking changes, so the adapter
  test doubles must mirror the 0.1.6 surface exactly. **[Inference]**
