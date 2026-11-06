# Research: the seven unresolved licences and revisions in the model manifest (#694)

**Status:** RESEARCH DRAFT — REVIEW PENDING. Nothing in the manifest, the inventory, the
schema, the validator or the product is changed by this note. The diff at the end is a
proposal for a reviewer to apply, together with the matching inventory edit.

**Base:** `main` at `8a72bbc6`. All `file:line` references are to that commit.
**Read on:** 2026-11-06, between 02:16 and 02:40 UTC, unauthenticated, no token. Hub,
PyPI and GitHub API reads were JSON; the three MediaPipe model cards were PDFs read with
`pdftotext`. No model weights were downloaded, so no hash below was recomputed.

Labels: **[Fact]** is what a cited source says on the read date. **[Inference]** is a
conclusion drawn from facts, stated as such. **[Proposal]** is a suggested change.
**[Vendor claim]** is a publisher's statement about its own artefact that was not checked
independently.

## 1. Scope, re-verified against the code

`design/hci-huggingface/model-manifest.json` (schema version 1, inventory date
2026-10-28) holds 54 rows. A count over the file on `8a72bbc6` gives:

- **Licence `unknown`: 7 rows. Revision kind `unknown`: 3 rows.** The three revision gaps
  are inside the seven licence gaps, so seven rows in total. Nothing in Rounds 3-7 changed
  them: the last commits to touch the manifest are `f123383a` and `2989aead` (validator).
- **`pinned_by_yazses` is `false` on all 54 rows.** YazSes passes no revision, tag or
  digest to any loader. Every row below therefore says what was *observed*, never what
  YazSes *uses*.

| Manifest id | Licence | Revision kind |
|---|---|---|
| `openai--whisper-large` | unknown | unknown |
| `silero-vad-package` | unknown | unknown |
| `l2cs-net` | unknown | unknown |
| `silero-vad-v6-faster-whisper-bundled` | unknown | package-version |
| `mediapipe-face-landmarker-float16` | unknown | versioned-path |
| `sherpa-onnx-pyannote-segmentation-3-0` | unknown | tag |
| `3dspeaker-eres2net-base-zh-cn` | unknown | tag |

## 2. Findings per row

### 2.1 `openai--whisper-large` (upstream of `Systran/faster-whisper-large-v1`)

- **[Fact]** `https://huggingface.co/api/models/openai/whisper-large`: `sha`
  `4ef9b41f0d4fe232daafdb5f76bb1dd8b23e01d7`, `lastModified` `2024-02-29T10:57:46Z`,
  `gated: false`, tag `license:apache-2.0`, `cardData.license: apache-2.0`.
- **[Fact]** The README front matter (`https://huggingface.co/openai/whisper-large/raw/main/README.md`)
  ends with `license: apache-2.0`.
- **[Inference]** Same pattern the inventory already records for large-v2 and large-v3
  (`model-provenance.md:143-144`): the Systran conversion says `mit`
  (`model-provenance.md:78`), the upstream Hub card says `apache-2.0`. The
  2026-11-06 runtime note (`design/research/2026-11-06-offline-asr-runtime-and-provenance-audit.md`,
  finding 4) explains why that is a legal rather than an engineering question; YazSes does
  not redistribute the weights.
- **Resolution:** licence `stated`, `apache-2.0`; revision `git-commit` with the sha above.

### 2.2 `silero-vad-package` (optional `silero` extra, Meeting Mode VAD)

- **[Fact]** `pyproject.toml:344` and `:435` declare `silero-vad>=5.1.2` (a floor, not a
  pin). `uv.lock:5654-5655` resolves `silero-vad` `6.2.3`.
- **[Fact]** `https://pypi.org/pypi/silero-vad/json`: latest `6.2.3`, uploaded
  2026-09-23; `license` empty, classifier `License :: OSI Approved :: MIT License`. Wheel
  `silero_vad-6.2.3-py3-none-any.whl` sha256
  `7b7f5436cfcb02fae583a05b512ea96467fd449fe54cb49a5e4f06c51a1e43b8` (PyPI digest).
- **[Fact]** `https://api.github.com/repos/snakers4/silero-vad/license`: `spdx_id: MIT`,
  file `LICENSE` (blob `0bf5e90c…`).
- **[Fact]** The model ships inside the wheel (`src/yazses/meeting/silero_vad.py:7`), so
  the package version is the closest available revision.
- **Resolution:** licence `stated`, `mit`; revision `package-version`,
  `silero-vad 6.2.3 (uv.lock)`. A pip user can resolve any version at or above 5.1.2, which
  the `as_stated`/value text must say.

### 2.3 `silero-vad-v6-faster-whisper-bundled` (`silero_vad_v6.onnx` in faster-whisper)

- **[Fact]** `uv.lock:1210-1211` resolves `faster-whisper` `1.2.1`. At tag `v1.2.1`,
  `faster_whisper/assets/` holds `silero_vad_v6.onnx`, 1,245,151 bytes, git blob
  `9febab9bc0aa5ae2b27e69243d813427212bfb36` (GitHub contents API). The git blob id is a
  SHA-1 of the blob, not a sha256 of the file.
- **[Fact]** `faster_whisper/vad.py:13` at `v1.2.1`: "The code below is adapted from
  https://github.com/snakers4/silero-vad." The faster-whisper repository licence is MIT
  (GitHub licence API). No separate licence file for the ONNX asset exists in `assets/`.
- **[Inference]** The file's licence is most plausibly Silero's MIT, but faster-whisper does
  not say where the ONNX file came from or under which licence it is redistributed. Both
  candidate licences are MIT, so the answer is the same either way; the *source* of the
  statement is not.
- **Resolution (two options for the reviewer):** (a) `stated`, `mit`, with `as_stated`
  saying "MIT is both the faster-whisper repository licence and the Silero VAD repository
  licence; faster-whisper states no separate licence for the bundled file"; or (b) keep
  `unknown` with that sentence as the reason. Option (a) is proposed below because no
  candidate licence differs. Revision unchanged (`faster-whisper 1.2.1`).

### 2.4 `l2cs-net` (gaze backend `l2cs`, manual install) — and a defect

- **[Fact]** Repository licences: `Ahmednull/L2CS-Net` is MIT (licence API, blob
  `e5258bf4…`; head `a4d8f7fa5436a2b2b9f088471623b552a85811bd`, 2023-11-06). The fork
  its README installs from, `edavalosanaya/L2CS-Net`, is MIT (head
  `4a0f978d5b4c426a7d37022d8c927d6ea031dcb6`, 2024-01-19).
- **[Fact]** The weights are not in either repository. The upstream README says: "Download
  the pre-trained models from [here](https://drive.google.com/drive/folders/17p6ORr-JQJcw-eYtG2WGNiuS_qVKwdWd?usp=sharing)
  and Store it to *models/*". No licence is stated for the weights. Google Drive was not
  opened.
- **[Fact — defect]** `https://pypi.org/pypi/l2cs/json`: the PyPI project named `l2cs` is
  **an unrelated library**, summary "Rewrites queries from lucene syntax to Amazon
  Cloudsearch syntax", author Keith Mitchell, home page `github.com/kemitche/l2cs`,
  licence `BSD`, latest `2.0.2`. YazSes's install hint is `pip install "l2cs>=2.0"`
  (`pyproject.toml:367`, `src/yazses/gaze/factory.py:14`). That hint is satisfied by the
  unrelated 2.0.2 and installs a package with no `Pipeline`, so
  `from l2cs import Pipeline` (`src/yazses/gaze/l2cs.py:18`) fails. The upstream README
  installs from git instead: `pip install git+https://github.com/edavalosanaya/L2CS-Net.git@main`.
- **[Fact — defect]** In both repositories `l2cs/pipeline.py` declares
  `weights: pathlib.Path` (line 19) and calls `torch.load(self.weights, ...)` (line 34).
  YazSes passes `weights=None` with the comment "l2cs resolves its bundled pretrained
  ResNet" (`src/yazses/gaze/l2cs.py:25`). **[Inference]** Neither repository bundles or
  resolves weights, so with the real package installed the constructor would call
  `torch.load(None)` and fail. Not executed tonight.
- **[Inference]** The `l2cs` backend is therefore unreachable by its documented install path,
  and the hint sends users to an unrelated third-party package of the same name — a
  name-confusion supply-chain risk, even though that particular package is benign as far
  as its metadata shows. This is outside this note's owned paths and is **not fixed here**;
  it should become its own issue (fix or drop the hint and the `weights=None` call).
- **Resolution:** licence stays `unknown` with the reason "repository code MIT (both
  repositories); the weights live on Google Drive with no stated licence". Revision stays
  `unknown` with the reason "no install path YazSes documents resolves to L2CS-Net; the PyPI
  name `l2cs` is an unrelated project". Do not record a git commit YazSes does not install.

### 2.5 `mediapipe-face-landmarker-float16` (`face_landmarker.task`)

- **[Fact]** The MediaPipe Face Landmarker guide
  (`https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker`, which
  `ai.google.dev/...` now 301-redirects to) lists three model cards for the bundle and
  links the float16 bundle at `.../float16/latest/face_landmarker.task`. The page text
  read shows no licence statement for the bundle.
- **[Fact]** Each card says "LICENSED UNDER Apache License, Version 2.0":
  "Model Card MediaPipe Face Mesh V2" (dated September 15, 2022),
  "Model Card Blendshape V2", and "MediaPipe BlazeFace Model Card (Short Range)", all at
  `https://storage.googleapis.com/mediapipe-assets/`. The `google-ai-edge/mediapipe`
  repository licence is Apache-2.0 (licence API).
- **[Fact]** `HEAD` on the URL YazSes uses (`src/yazses/gaze/download.py:27-30`,
  `.../float16/1/face_landmarker.task`): HTTP 200, `content-length: 3758596`,
  `last-modified: Wed, 03 May 2023 18:02:21 GMT`, `x-goog-hash: md5=sOcnSQehZEQE/vZrKN1thQ==`
  (= the ETag `b0e7274907a1644404fef66b28dd6d85`), `crc32c=2FSEdQ==`. Unchanged from the
  2026-10-28 inventory.
- **[Inference]** The card licences cover the three models the bundle is documented to
  contain; no statement covers the `.task` container itself. YazSes's `/1/` path is the
  pinned-version form; the guide now advertises `/latest/`, which YazSes rightly does not use.
- **Resolution:** licence `stated`, `apache-2.0`, with `as_stated` naming the three cards.
  Revision unchanged (`versioned-path`, `float16/1`). An `md5` is not a schema-valid
  artifact hash (the manifest records sha256), so it goes in text only.

### 2.6 `sherpa-onnx-pyannote-segmentation-3-0` (default diarizer segmentation)

- **[Fact]** GitHub release `speaker-segmentation-models` of `k2-fsa/sherpa-onnx`: created
  2024-09-27, target `master`, body "Please see
  https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html". Asset
  `sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`: 6,958,444 bytes, `updated_at`
  2024-10-08T12:54:10Z, no `digest` field in the API response.
- **[Fact]** Hub mirror `csukuangfj/sherpa-onnx-pyannote-segmentation-3-0`: `sha`
  `9403a6902bb58e3d5ae8c7e77c3422de279db2e0`, `lastModified` 2024-10-08T12:54:11Z, not
  gated, no licence tag; it contains `LICENSE` ("MIT License / Copyright (c) 2022 CNRS")
  and a README saying "Models in this file are converted from
  https://huggingface.co/pyannote/segmentation-3.0/tree/main".
- **[Fact]** Upstream `pyannote/segmentation-3.0`: `license:mit`, gated `auto`, sha
  `e66f3d3b…` (unchanged from the inventory, `model-provenance.md:108`).
- **[Inference]** The Hub mirror and the release asset were updated two seconds apart and
  the mirror carries the upstream CNRS MIT licence, so the converted weights are offered
  under MIT. That the tarball's contents equal the mirror's files was **not** verified (the
  tarball was not downloaded). The release asset page itself states no licence.
- **Resolution:** licence `stated`, `mit`, with `as_stated` quoting the mirror LICENSE and
  the not-verified equivalence. Revision stays `tag` (`speaker-segmentation-models`); tags
  and release assets are mutable and YazSes checks no hash (`src/yazses/recimport/download.py:22-24`).

### 2.7 `3dspeaker-eres2net-base-zh-cn` (default diarizer embedding)

- **[Fact]** GitHub release `speaker-recongition-models` (sic): created 2023-12-08, body
  "This release contains speaker recognition models for sherpa-onnx. Each model has its own
  license. Please see the corresponding repository for the specific license of a given
  model." Asset `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`: 39,593,761
  bytes, `updated_at` 2024-10-14T03:41:16Z, no `digest` field.
- **[Fact]** ModelScope API
  `https://modelscope.cn/api/v1/models/iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k`:
  `License: "Apache License 2.0"`, `Revision: "master"`, last updated 1692869850
  (2023-08-24 UTC).
- **[Inference]** The asset was replaced or uploaded ten months after its release was
  created, which shows concretely that the tag-based URL in
  `src/yazses/recimport/download.py:26-28` can serve different bytes over time.
- **Resolution:** licence `stated`, `apache-2.0`, with `as_stated` quoting the ModelScope
  field and the release's "each model has its own license" notice. Revision stays `tag`.

## 3. Summary

| Manifest id | Proposed licence | Proposed revision | Source(s), read 2026-11-06 |
|---|---|---|---|
| `openai--whisper-large` | apache-2.0 (stated) | git-commit `4ef9b41f0d4fe232daafdb5f76bb1dd8b23e01d7` (2024-02-29) | Hub API + README |
| `silero-vad-package` | mit (stated) | package-version `silero-vad 6.2.3 (uv.lock)` | PyPI JSON; GitHub licence API |
| `silero-vad-v6-faster-whisper-bundled` | mit (stated, option a) or unknown (option b) | unchanged | faster-whisper v1.2.1 tree; both licence APIs |
| `l2cs-net` | **unknown, with reason** | **unknown, with reason** | GitHub licence APIs, README, PyPI `l2cs` |
| `mediapipe-face-landmarker-float16` | apache-2.0 (stated) | unchanged (`float16/1`) | 3 Google model cards; HEAD |
| `sherpa-onnx-pyannote-segmentation-3-0` | mit (stated) | unchanged (tag) | Hub mirror LICENSE + README; release API |
| `3dspeaker-eres2net-base-zh-cn` | apache-2.0 (stated) | unchanged (tag) | ModelScope API; release API |

Six of seven licence gaps close with a quoted source; `l2cs-net` stays unknown with a
reason. Two of three revision gaps close; `l2cs-net` stays unknown with a reason. Every
`apache-2.0`/`mit` id is already in the schema's closed enum, so no schema edit is needed.

## 4. Proposed manifest diff (apply tomorrow, with the inventory edit)

**[Proposal]** The validator requires every Hub id, revision and hash in the manifest to be
quoted whole in `design/hci-huggingface/model-provenance.md` (`scripts/check_model_manifest.py:10`).
So each change below needs the same value written into the inventory row first
(`model-provenance.md:78`/`:142` for whisper-large, `:108-110`, `:111-112` (Silero), `:113`, `:114`), with "observed 2026-11-06" and the source URL. Leave `inventory_date` alone
unless the reviewer re-dates the whole inventory; each changed revision carries its own
`observed_on`.

```diff
 "id": "openai--whisper-large",
-"license": {"status": "unknown", "as_stated": "Not verified (not fetched)"},
-"revision": {"kind": "unknown", "pinned_by_yazses": false},
+"license": {"status": "stated", "id": "apache-2.0",
+  "as_stated": "apache-2.0 (Hub tag and README front matter, read 2026-11-06). The Systran conversion says mit"},
+"revision": {"kind": "git-commit", "value": "4ef9b41f0d4fe232daafdb5f76bb1dd8b23e01d7",
+  "observed_on": "2026-11-06", "last_modified": "2024-02-29", "pinned_by_yazses": false},

 "id": "silero-vad-package",
-"license": {"status": "unknown", "as_stated": "Not verified"},
-"revision": {"kind": "unknown", "pinned_by_yazses": false},
+"license": {"status": "stated", "id": "mit",
+  "as_stated": "MIT (PyPI classifier for silero-vad 6.2.3; snakers4/silero-vad LICENSE via the GitHub licence API, read 2026-11-06)"},
+"revision": {"kind": "package-version", "value": "silero-vad 6.2.3 (uv.lock; pyproject floor >=5.1.2)",
+  "observed_on": "2026-11-06", "pinned_by_yazses": false},

 "id": "silero-vad-v6-faster-whisper-bundled",
-"license": {"status": "unknown", "as_stated": "Not verified in this pass (...)"},
+"license": {"status": "stated", "id": "mit",
+  "as_stated": "MIT is both the faster-whisper repository licence and the snakers4/silero-vad licence (GitHub licence API, read 2026-11-06); faster-whisper states no separate licence for assets/silero_vad_v6.onnx"},

 "id": "l2cs-net",
-"license": {"status": "unknown", "as_stated": "Not verified"},
+"license": {"status": "unknown",
+  "as_stated": "Repository code is MIT (Ahmednull/L2CS-Net and edavalosanaya/L2CS-Net, read 2026-11-06); the weights are on Google Drive with no stated licence. PyPI 'l2cs' is an unrelated project (Lucene to CloudSearch)"},
 (revision stays {"kind": "unknown", "pinned_by_yazses": false}; the reason goes in the inventory row, since the schema forbids a value on an unknown revision)

 "id": "mediapipe-face-landmarker-float16",
-"license": {"status": "unknown", "as_stated": "Not verified. No licence or terms page was read"},
+"license": {"status": "stated", "id": "apache-2.0",
+  "as_stated": "Apache License 2.0 on the Face Mesh V2, Blendshape V2 and BlazeFace (short range) model cards linked from the Face Landmarker guide, read 2026-11-06; no statement covers the .task container itself"},

 "id": "sherpa-onnx-pyannote-segmentation-3-0",
-"license": {"status": "unknown", "as_stated": "Not verified for the conversion. (...)"},
+"license": {"status": "stated", "id": "mit",
+  "as_stated": "MIT (Copyright 2022 CNRS) in the LICENSE of the Hub mirror csukuangfj/sherpa-onnx-pyannote-segmentation-3-0, read 2026-11-06; the release asset states none, and the tarball was not compared with the mirror"},

 "id": "3dspeaker-eres2net-base-zh-cn",
-"license": {"status": "unknown", "as_stated": "Not verified for the weights. (...)"},
+"license": {"status": "stated", "id": "apache-2.0",
+  "as_stated": "Apache License 2.0 (ModelScope API License field for iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k, read 2026-11-06); the sherpa-onnx release says each model has its own licence"},
```

`csukuangfj/sherpa-onnx-pyannote-segmentation-3-0` is a Hub id and its sha
`9403a6902bb58e3d5ae8c7e77c3422de279db2e0` would be a new Hub reference; quote both in the
inventory row if the reviewer adds them to the manifest text.

## 5. Follow-ups for #694 (proposals, not implemented)

1. **[Proposal] File an issue for the `l2cs` backend** (§2.4): the install hint names an
   unrelated PyPI package, and `weights=None` cannot load. Fix the hint (git URL or drop the
   backend) and require an explicit weights path. Code change, needs its own tests.
2. **[Proposal] Pinning stays a #694 follow-up, as before.** All 54 rows remain
   `pinned_by_yazses: false`. For the two GitHub release assets and the MediaPipe bundle, a
   recorded sha256 checked after download would protect against the asset replacement §2.7
   shows is possible; recording it requires downloading the files once, which was not done
   tonight. This is runtime behaviour (L3) and is not proposed for this change.
3. **[Proposal]** Re-run `uv run python scripts/check_model_manifest.py` and
   `uv run python -m pytest tests/test_model_manifest.py -v` after applying §4.

## Sources (all read 2026-11-06, unauthenticated)

- https://huggingface.co/api/models/openai/whisper-large and `/raw/main/README.md`
- https://pypi.org/pypi/silero-vad/json ; https://api.github.com/repos/snakers4/silero-vad/license
- https://api.github.com/repos/SYSTRAN/faster-whisper/contents/faster_whisper/assets?ref=v1.2.1 ;
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/faster_whisper/vad.py ;
  https://api.github.com/repos/SYSTRAN/faster-whisper/license
- https://pypi.org/pypi/l2cs/json ; https://api.github.com/repos/Ahmednull/L2CS-Net/license ;
  https://github.com/Ahmednull/L2CS-Net (README, `l2cs/pipeline.py`) ;
  https://github.com/edavalosanaya/L2CS-Net (`l2cs/pipeline.py`, licence API)
- https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker ; the three
  model cards under https://storage.googleapis.com/mediapipe-assets/ ;
  https://api.github.com/repos/google-ai-edge/mediapipe/license
- https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/speaker-segmentation-models ;
  https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0 ;
  https://huggingface.co/api/models/pyannote/segmentation-3.0
- https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/speaker-recongition-models ;
  https://modelscope.cn/api/v1/models/iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k
