# Chinese support — test and validation plan

**Status:** Proposed release protocol  
**Purpose:** Define what must be tested in CI, what must be benchmarked offline, what requires real desktop hardware, and what requires native-language review before first-class Mandarin support is claimed.

## 1. Validation philosophy

Chinese support has four independent failure classes:

1. **Configuration failure** — the application enters an impossible model/language state.
2. **Recognition failure** — speech is decoded inaccurately or unstably.
3. **Semantic-control failure** — a command is misclassified or normal prose executes an action.
4. **Delivery failure** — correct Han text is recognized but cannot be injected into the target application.

A single “transcribed one Chinese sentence” test covers only a small part of class 2.

The release gate therefore combines deterministic CI tests, reproducible model benchmarks, real-platform injection tests, and native-speaker review.

---

## 2. Test layers

| Layer | Runs in normal CI? | Needs model? | Needs audio? | Needs native speaker? |
|---|---:|---:|---:|---:|
| Profile resolver unit tests | Yes | No | No | No |
| Config transaction tests | Yes | No | No | No |
| Grammar/parser tests | Yes | No | No | Review fixtures |
| STT wiring mocks | Yes | Fake | Synthetic array | No |
| Han converter tests | Yes/optional extra | No ASR | No | No |
| CLI/controller integration | Yes | Fake/cache mocks | No | No |
| File/meeting integration | Yes | Fake engine | Fixture metadata | No |
| Real Mandarin ASR benchmark | No, benchmark job | Yes | Licensed corpus | No for scoring |
| Real desktop injection | Matrix/manual or hardware CI | No ASR needed | No | No |
| Native-speaker acceptance | No | Yes | Reviewer voice | Yes |
| English regression benchmark | Release job | Yes | Existing corpus | No |

---

## 3. Unit-test plan

### 3.1 Language profile aliases

Create `tests/test_language_profiles.py`.

Required cases:

```text
en -> en
EN -> en
zh-CN -> zh-CN
zh-cn -> zh-CN
zh-Hans -> zh-CN
zh_hans -> zh-CN
zh-TW -> zh-TW
zh-Hant -> zh-TW
zh_hant -> zh-TW
```

Refusals:

- empty request;
- unknown profile;
- `zh-HK`;
- `yue` until implemented.

For `zh-HK`, assert the error text mentions both:
- Mandarin + Traditional option (`zh-TW`);
- Cantonese is separate/not P1.

Do not test only exception type; the remediation is part of the user contract.

### 3.2 Resolver: default English -> Simplified Mandarin

Given default `Config()`, assert plan contains exactly relevant mutations:

- `stt.model: base.en -> small`;
- `stt.language: en -> zh`;
- `stt.chinese_script: "" -> simplified`.

Assert it does not alter:

- device;
- compute type;
- beam;
- vocabulary;
- microphone;
- hotkey;
- injection backend;
- unrelated command/app profile.

### 3.3 Resolver: default English -> Traditional Mandarin

Same, script target = traditional.

### 3.4 Resolver preserves compatible model

Examples:

- current `small + en` -> zh-CN keeps small;
- current `large-v3 + en` -> zh-CN keeps large-v3 if capability layer declares it compatible;
- current `small + zh` -> en keeps small.

### 3.5 Recommended-model mode

- `zh-CN --recommended-model` resolves to supported Chinese baseline;
- `en --recommended-model` resolves to English baseline;
- explicit `--model` and recommended mode conflict.

### 3.6 Requirement detection

Mock cache/dependency probes:

- small cached + OpenCC installed => no unsatisfied requirements;
- model absent => one model requirement;
- OpenCC absent => one optional-extra requirement;
- both absent => both reported;
- probes perform no network.

### 3.7 Status derivation

Test:

- exact en;
- exact zh-CN;
- exact zh-TW;
- custom compatible Chinese model;
- zh + base.en incoherent;
- Chinese script set with en/base.en;
- command language override en while speech zh;
- command language auto -> zh.

---

## 4. Transaction tests

Create `tests/test_language_apply.py`.

Use a temporary config file and injected collaborators for downloads/install/restart.

### 4.1 No prerequisite side effects in dry-run

Assert:
- no package install;
- no model download;
- no file write;
- no restart.

### 4.2 Model download failure rolls back fully

Initial file checksum before call == checksum after failure.

Also parse final config to ensure no hidden partial write.

### 4.3 Optional dependency failure rolls back fully

Same invariant.

### 4.4 Candidate parse/validation failure

Inject invalid candidate rendering or validator failure. Original survives byte-for-byte.

### 4.5 Atomic successful commit

Observe config file externally only after complete candidate is ready.

At no point should a watcher see `language=zh` while model remains `base.en`.

A unit test can assert implementation uses same-directory temp + `os.replace`/equivalent. An integration test can watch the file if practical.

### 4.6 Concurrent edit

Simulate:

1. plan generated from version A;
2. another process changes unrelated setting to version B;
3. apply starts.

Required behavior: re-read and re-resolve so unrelated change is preserved; do not overwrite from stale in-memory config.

If project locking makes step 2 impossible during application, test lock acquisition/release instead.

### 4.7 Restart behavior

- zero mutations => no restart;
- successful mutation => one restart;
- `--no-restart` => no restart, clear result flag;
- restart failure => committed config remains syntactically valid and error is distinguishable from config failure.

---

## 5. Command grammar tests

### 5.1 First refactor gate: English parity

Before adding Chinese rules, extract current English grammar behind registry and run:

- all existing grammar tests;
- `contract/vectors/grammar.json`;
- generated contract-vector comparison if project tooling supports it.

No behavior changes should be mixed into the extraction PR.

### 5.2 Chinese fixture file

Add a language-specific vector file, for example:

`contract/vectors/grammar-zh.json`

Schema should include:

```json
{
  "id": "zh-save-simplified",
  "language": "zh",
  "text": "保存文件",
  "expected": {
    "intent": "edit",
    "action": "save",
    "args": {}
  }
}
```

Each semantic action has:

- Simplified natural phrase;
- Traditional natural phrase where wording/script differs;
- ASR punctuation variant;
- spacing variant around digits/Latin identifiers;
- negative near-match/prose example.

### 5.3 Command precision first

Command false positives are more damaging than missed commands because a missed command is typed text, while a false positive changes application state.

Build a negative corpus of ordinary Mandarin sentences containing words such as 保存, 删除, 复制, 运行 in non-command contexts.

Release criterion for deterministic Tier-1 fixtures: **zero false positives** on the curated negative set.

### 5.4 Numeral tests

Test at least:

- `第1行`, `第 1 行`;
- `第一行`;
- `第十行`;
- `第十一行`;
- `第二十五行`;
- `两行` where grammatically accepted;
- out-of-range/malformed numeral stays dictation or non-match.

### 5.5 Chinese punctuation

Outer punctuation accepted:

- `。`
- `！`
- `？`
- full-width variants produced by ASR.

Interior punctuation/filename characters must not be blindly stripped.

### 5.6 Terminal/safety commands

For every Chinese phrase mapping to `run_command` or other terminal action:

- prove same `CommandIntent.action`;
- prove it traverses existing command-safety gate;
- negative tests for prose;
- no catch-all regex broader than the English equivalent.

If this cannot be established in P1, omit those Chinese terminal rules and document partial parity.

---

## 6. STT wiring tests

Generalize existing `test_stt_language.py` where useful.

With fake `WhisperModel`:

- `language="zh"` reaches `transcribe`;
- reaches `transcribe_words`;
- reaches `decode_window`;
- translate task still omits fixed source language;
- initial prompt survives;
- Han wrapper converts final text/words/windows.

Profile-to-engine integration:

```text
default config
 -> resolve zh-CN
 -> candidate SttConfig
 -> build_engine(fake model)
 -> transcribe kwargs contains language=zh
 -> output normalization is Simplified
```

English regression:
- default engine still sees language=en;
- default model remains base.en;
- `build_engine(SttConfig())` behavior unchanged.

---

## 7. Import and dependency regression tests

A fresh default English process should not import:

- `opencc`;
- `funasr`;
- `qwen_asr`;
- `torch` solely due to language support.

Possible test:

- start subprocess importing core/CLI status;
- inspect `sys.modules` or use import sentinel;
- assert language resolver modules remain stdlib/project-only.

This protects startup time and package independence.

---

## 8. CLI integration tests

Use Click test runner / project CLI harness.

### `language list`
- stable IDs;
- zh-CN/zh-TW visible;
- zh-HK not available;
- no model import/download.

### `language status`
- coherent exit;
- incoherent exit;
- JSON schema;
- custom-model indicator.

### `language set --dry-run`
- exact plan;
- no write.

### Real apply with fakes
- writes coherent config;
- restart called;
- output names one-time artifact;
- `--no-download` refuses cache miss.

### Error usability
Snapshot/substring tests for:
- base.en override with zh;
- network/model failure;
- optional package unavailable;
- ambiguous zh-HK.

---

## 9. Settings UI/controller tests

Qt-free controller/model tests first.

- language profile choices;
- current custom-compatible state;
- plan preview;
- confirmation requirement for downloads;
- cancel = zero mutation;
- apply delegates to shared resolver;
- model dropdown compatibility after profile selection;
- selecting UI language never calls STT language setter.

Minimal Qt smoke test verifies widgets reflect controller data; business logic remains Qt-free.

---

## 10. File-transcription validation

### Mock integration

With fake engine, verify:

- config zh applies when no CLI override;
- `--language en` overrides config for one operation;
- override does not rewrite global config;
- script conversion is applied when appropriate;
- metadata records effective values.

### Real benchmark

Take a subset of the Mandarin benchmark corpus through the actual file CLI and compare output to direct engine harness. Differences should be explainable by file preprocessing only.

---

## 11. Meeting validation

Both live and post-pass must record/use effective Mandarin configuration.

Tests:

- fake live path returns Han;
- fake post-pass returns Han;
- quality gate still functions on Chinese transcript;
- no English-specific word-token assumption causes false degeneration where CJK spacing differs.

This is a **confirmed blocker in current `main`**, not only an audit hypothesis. `meeting/quality.py::tokenize()` uses `[^\\W\\d_]+`; with ordinary unsegmented Chinese, a whole Han run between punctuation marks becomes one token. `store.live_word_count()` calls the same tokenizer. The existing `THIN_MAX_WPM` and n-gram thresholds were calibrated on English meetings, so a healthy Mandarin meeting can appear artificially sparse and the live/batch second-opinion ratio is not a language-independent count. Before claiming Chinese Meeting Mode, implement a CJK-valid quality unit (language-aware segmentation or a separately justified character-rate design), re-fit thresholds on healthy + failed Mandarin meetings, and add tests proving healthy Chinese is not marked `thin` while repetition collapse still fires.

Long meeting real test:
- >=30 min Mandarin recording or legally usable corpus composition;
- no repetition collapse;
- live and batch artifacts;
- resource monitoring;
- script consistency.

---

## 12. Postprocessing audit

Search every postprocess/filter for English/whitespace assumptions.

Required review categories:

- filler-word removal;
- sentence casing/capitalization;
- spacing between bursts;
- punctuation cleanup;
- vocabulary correction;
- prosody formatting;
- number/date normalization;
- code formatting;
- meeting word counting;
- transcript quality metrics.

For each component classify:

| Class | Action |
|---|---|
| language-neutral | test with Chinese |
| English-specific but disabled by default | document |
| English-specific and default-on | gate by language or fix before release |
| destructive/unknown | block Chinese support release |

Create a machine-readable or Markdown compatibility matrix from this review.

---

## 13. Injection validation matrix

Use a known test string containing:

```text
你好，世界。简体中文測試123，YazSes。
```

For Traditional target, use reviewed equivalent after conversion.

Test:

### Linux X11
- default injection backend;
- clipboard backend;
- browser text field;
- GTK text field;
- Qt text field;
- VS Code/electron.

### Linux Wayland
- ydotool/current backend;
- clipboard fallback;
- same app categories where available.

### macOS
- native injection backend;
- clipboard fallback;
- TextEdit/browser/editor.

### Windows
- native injection backend;
- clipboard fallback;
- Notepad/browser/editor.

Record:
- exact bytes/text expected vs actual;
- lost characters;
- reordered punctuation;
- line break behavior;
- latency for 10/100/1000 Han characters.

No backend gets a green status from “ASCII worked.”

---

## 14. Mandarin benchmark protocol

### 14.1 Corpus requirements

At least two different evaluation conditions:

- clean/read or clean controlled speech;
- spontaneous/conversational or accented speech.

Prefer an additional noise/far-field set.

Do not mix train/dev material used by a candidate with a supposedly independent evaluation without disclosure.

### 14.2 Corpus manifest

Commit metadata, not restricted audio:

```json
{
  "corpus": "...",
  "version": "...",
  "split": "...",
  "license": "...",
  "sha256_manifest": "...",
  "n_utterances": 500,
  "duration_hours": 1.2,
  "reference_script": "simplified"
}
```

### 14.3 Text normalization

Publish scoring normalization code.

Score at least:
- Unicode normalized consistently;
- punctuation-preserving CER;
- punctuation-stripped CER;
- raw script;
- requested script after OpenCC;
- digits policy explicitly stated.

Never silently convert references in a way that makes errors disappear without reporting raw results too.

### 14.4 Error metrics

Per model:
- substitutions;
- deletions;
- insertions;
- CER;
- sentence exact match;
- hallucination/repetition count;
- empty decode count.

Subsets:
- short (<3s);
- medium;
- long;
- numbers;
- Latin technical terms;
- accent/noise if labels available.

### 14.5 Determinism

Decode each selected stress subset multiple times for models/settings known to vary.

Report:
- distinct hypothesis count;
- CER range;
- repetition incidents.

---

## 15. Performance benchmark

Reference machine record:

- CPU model;
- physical/logical cores;
- RAM;
- OS/kernel;
- power mode;
- Python;
- CTranslate2/faster-whisper version;
- compute type;
- thread count.

Measure:
- cold model load;
- warm model load;
- 2/5/10/30s utterances;
- p50/p95 decode time;
- RTF;
- release-to-text;
- peak RSS;
- CPU-seconds;
- disk model size.

Run enough samples to avoid single-utterance timing claims.

---

## 16. Alternative-model benchmark

Same audio and scoring pipeline for:

- Whisper small baseline;
- large-v3-turbo;
- large-v3;
- SenseVoiceSmall prototype when available;
- Paraformer candidate when available;
- Qwen3-ASR-0.6B when available.

Do not change VAD/segmentation differently per model without recording it as a distinct pipeline arm.

A model’s upstream benchmark is background context only; promotion is based on YazSes harness results.

---

## 17. Native-speaker acceptance protocol

At least:

- one Simplified Chinese reviewer;
- one Traditional Chinese reviewer independently.

Prefer more than one speaker/accent.

Review checklist:

### Dictation
- common prose;
- punctuation;
- numbers;
- names/English technical terms;
- correction experience;
- script consistency.

### Commands
- phrase naturalness;
- alternatives speakers actually say;
- ambiguous commands;
- Traditional wording, not mechanical character conversion only.

### UX
- language switch wording;
- Mandarin vs Chinese terminology;
- zh-TW wording;
- zh-HK/Cantonese explanation;
- diagnostics understandable.

Reviewer result should be documented without publishing private audio.

---

## 18. English regression gate

Run full existing suite.

Additionally:
- default Config values exact;
- default model artifact unchanged;
- startup import regression;
- representative English grammar vectors;
- English language set no-op behavior;
- Chinese profile code absent from hot decode path when unused.

Performance smoke:
- compare baseline English release-to-text before/after implementation on a fixed small sample;
- investigate >5% systematic regression in median wall time attributable to code change.

---

## 19. Packaging validation

For each supported distribution path that can exercise Settings/language setup:

- pip/pipx/uv;
- Snap;
- Flatpak where applicable;
- macOS app/package;
- Windows app/installer;
- distro packages as appropriate.

Questions:
- can OpenCC extra be installed?
- if not, is it bundled or does the profile give exact remediation?
- can model download write to cache?
- can air-gapped provisioning work?
- does writable config transaction work in sandbox?
- does restart work?
- are non-ASCII CLI/UI strings rendered?

A packaging path may support Chinese with a documented fallback, but cannot silently enable an unavailable extra.

---

## 20. Release evidence artifact

Suggested output directory:

```text
design/chinese/results/<release-or-date>/
    README.md
    environment.json
    corpus-manifest.json
    recognition.json
    performance.json
    commands.json
    injection-matrix.md
    native-review.md
```

If repository policy prefers `paper/results` for machine artifacts, put JSON there and link from this directory. Follow the established public/private visibility contract.

---

## 21. Release decision checklist

Chinese may move from experimental/manual to supported only when:

- [ ] profile resolver tests pass;
- [ ] config transaction failure tests pass;
- [ ] English contract parity passes;
- [ ] Chinese command positive/negative vectors pass;
- [ ] STT wiring all surfaces passes;
- [ ] postprocess compatibility audit complete;
- [ ] file transcription real test passes;
- [ ] meeting audit/real test passes or meeting Chinese is explicitly excluded;
- [ ] model benchmark complete;
- [ ] performance gate complete;
- [ ] X11 result recorded;
- [ ] Wayland result recorded;
- [ ] macOS result recorded;
- [ ] Windows result recorded;
- [ ] fallback documented for any red backend;
- [ ] Simplified native review complete;
- [ ] Traditional native review complete;
- [ ] English regression complete;
- [ ] exact model/tool licenses recorded;
- [ ] offline-after-cache test passes;
- [ ] support documentation accurately names remaining limits.

Unchecked items are not “follow-up polish” if they affect the scope being claimed; they either block release or narrow the documented support matrix.
