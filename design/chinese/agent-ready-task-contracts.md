# Chinese support — ADR-023 agent-ready task contracts

**Status:** Planning artifact; do not copy these directly into `campaign/tasks.json` until the governing ADRs are accepted and each task has completed the ADR-023 negative-test/internal-verification step.

The repository now uses ADR-023’s agent-first contribution pipeline. This changes how the Chinese roadmap should be operationalized:

- **GitHub issues are umbrellas for discussion/design**, not one issue per 15-minute task.
- **Bounded contributor work lives in `campaign/tasks.json`** after it reaches A2/A3 readiness.
- L3 architecture/dependency/privacy/default-state work is **not** advertised as an open first task.
- Hardware, model measurements, and native-language judgment are never marked cloud-agent-ready.

## 1. Umbrella issues only

After PR #378’s ADRs are accepted, create at most these umbrella issues:

| Umbrella | Scope | Contains work packages |
|---|---|---|
| Mandarin foundation | language resolver, transaction, CLI, Settings, doctor | CHN-10..15 |
| Mandarin command grammar | grammar registry, numerals, phrase contracts | CHN-20..23 |
| Mandarin compatibility | postprocessors, file/meeting, platform injection | CHN-30..32 |
| Mandarin model evidence | benchmark harness, Whisper baseline, alternative probes | CHN-40..42 |
| Mandarin release validation | native review + ADR-v2-144 gate | CHN-43..50 |

The umbrella holds design discussion and cross-task decisions. Individual contributor units are campaign tasks.

## 2. Readiness mapping

| Work package | ADR-023 readiness target | Risk | Advertise? | Why |
|---|---|---:|---:|---|
| CHN-10 pure profile resolver | A3 after symbols/paths fixed | L2 | yes | pure code, deterministic CI |
| CHN-11 status derivation | A3 | L1/L2 | yes | pure code |
| CHN-12 atomic config transaction | A2 but maintainer/experienced | **L3** if shared config semantics/public interface change | **no open first task** | expensive failure mode |
| CHN-13 CLI | A3 once transaction API accepted | L2 | yes | bounded integration |
| CHN-14 Settings | A3 if Qt tests containerized | L2 | yes | UI/controller |
| CHN-15 doctor checks | A3 | L1/L2 | yes | diagnostics |
| CHN-20 English grammar extraction | A3 | L2 | yes after parity vectors fixed | regression-sensitive |
| CHN-21 Chinese grammar rules | A2 | L2 | yes, with native review | code can be agent-assisted; language judgment cannot |
| CHN-22 Chinese numeral parser | A3 | L1/L2 | yes | pure deterministic parser |
| CHN-23 language vectors | A2 | L0/L1 | yes | requires native-language review -> cloud false |
| CHN-30 postprocess audit | A2 | L1 | yes in one-module slices | evidence requires code inspection |
| CHN-31 file/meeting integration | A2/A3 by slice | L2 | yes | split file and meeting |
| CHN-32 platform injection | A2 | L0 compatibility | yes | hardware/desktop evidence -> cloud false |
| CHN-40 harness | A3 | L2 | yes to experienced contributor | deterministic code |
| CHN-41 benchmark runs | A2 | L0 measurement | yes | hardware/model evidence -> cloud false |
| CHN-42 alternative model probe | A2 | L2/L3 if dependency added | benchmark task yes; production dependency wiring no | separate research from integration |
| CHN-43 native acceptance | A2 | L0 localization/measurement | yes | human judgment, cloud false |
| CHN-50 release gate | A1 maintainer work | L3 | no | support claim/architecture decision |

## 3. Sample campaign task contracts

These are examples of the precision expected. Exact paths/commands must be rechecked against the implementation branch before a task becomes `open`.

### CHN-PROFILE-STATUS-001

```json
{
  "id": "CHN-PROFILE-STATUS-001",
  "family": "feature-wiring",
  "title": "Derive coherent en/zh-CN/zh-TW language status from Config",
  "value": "Lets CLI, Settings and doctor report one shared truth instead of reimplementing compatibility rules.",
  "risk": "L2",
  "minutes": 30,
  "skills": ["python", "pytest"],
  "cloud_agent_ready": true,
  "allowed_paths": [
    "src/yazses/language/status.py",
    "tests/test_language_status.py"
  ],
  "validation": [
    "uv run python -m pytest tests/test_language_status.py -q",
    "uv run ruff check src/yazses/language/status.py tests/test_language_status.py"
  ],
  "state": "draft",
  "source": "design/chinese/implementation-roadmap.md#5-chn-11--derive-language-statuscoherence"
}
```

Negative test before opening: a contributor must not be able to “pass” by comparing only profile strings. Fixtures must include a custom compatible model and an incoherent `base.en + zh` state.

### CHN-NUMERALS-001

```json
{
  "id": "CHN-NUMERALS-001",
  "family": "feature-wiring",
  "title": "Parse bounded Chinese command numerals from 0 to 99",
  "value": "Enables deterministic commands such as go-to-line without introducing a general Chinese text rewriter.",
  "risk": "L1",
  "minutes": 25,
  "skills": ["python", "pytest"],
  "cloud_agent_ready": true,
  "allowed_paths": [
    "src/yazses/commands/grammars/zh.py",
    "tests/test_command_numerals_zh.py"
  ],
  "validation": [
    "uv run python -m pytest tests/test_command_numerals_zh.py -q",
    "uv run ruff check src/yazses/commands/grammars/zh.py tests/test_command_numerals_zh.py"
  ],
  "state": "draft",
  "source": "design/chinese/implementation-roadmap.md#12-chn-22--chinese-command-numeral-parser"
}
```

Negative test: malformed or out-of-scope numerals must not turn into plausible numbers silently.

### CHN-INJECT-WAYLAND-001

```json
{
  "id": "CHN-INJECT-WAYLAND-001",
  "family": "compatibility",
  "title": "Record exact Han-text injection behavior on Linux Wayland",
  "value": "Prevents a correct Mandarin transcript from being advertised on a backend that cannot reliably type Han characters.",
  "risk": "L0",
  "minutes": 20,
  "skills": ["linux", "wayland"],
  "requires": {
    "os": "Linux",
    "desktop_session": "Wayland",
    "apps": ["one browser", "one native text editor"]
  },
  "cloud_agent_ready": false,
  "allowed_paths": [
    "design/chinese/results/injection/**"
  ],
  "validation": [
    "uv run python scripts/check-chinese-injection-report.py <new-report>"
  ],
  "evidence": [
    "Record OS/session/backend and target app.",
    "Paste expected and observed fixed public fixture text.",
    "State whether clipboard fallback was required.",
    "Do not include hostname, username, home path, private clipboard data, or dictated personal text."
  ],
  "state": "draft",
  "source": "design/chinese/surface-support-matrix.md#injection-matrix"
}
```

This task cannot become open until the proposed report validator exists; otherwise fabricated/free-form reports are too cheap to submit.

### CHN-COMMAND-TRADITIONAL-REVIEW-001

```json
{
  "id": "CHN-COMMAND-TRADITIONAL-REVIEW-001",
  "family": "localization",
  "title": "Review the Traditional Mandarin core-command phrase fixture for naturalness",
  "value": "Stops Simplified phrases or mechanical character conversion from being presented as natural Taiwan-oriented command language.",
  "risk": "L0",
  "minutes": 20,
  "skills": ["traditional-chinese", "mandarin"],
  "cloud_agent_ready": false,
  "allowed_paths": [
    "contract/vectors/grammar-zh.json"
  ],
  "validation": [
    "uv run python scripts/check-contract-vectors.py contract/vectors/grammar-zh.json"
  ],
  "evidence": [
    "Reviewer states which phrases were changed and why.",
    "Machine translation alone is not evidence."
  ],
  "state": "draft",
  "source": "design/adr/adr-v2-142-localized-command-grammars.md"
}
```

The exact validator name/path must match repository reality when the vector format is implemented.

### CHN-WHISPER-SMALL-MEASURE-001

```json
{
  "id": "CHN-WHISPER-SMALL-MEASURE-001",
  "family": "measurement",
  "title": "Run the pinned Mandarin benchmark on faster-whisper small",
  "value": "Provides the release baseline for CER, latency and resource cost using the same harness every candidate must beat.",
  "risk": "L0",
  "minutes": 45,
  "skills": ["python", "asr-benchmarking"],
  "requires": {
    "cpu": "record exact model",
    "ram": "record total",
    "network": "only for predeclared model/corpus acquisition if not already cached"
  },
  "cloud_agent_ready": false,
  "allowed_paths": [
    "design/chinese/results/**",
    "paper/results/**"
  ],
  "validation": [
    "uv run python <benchmark-validator> <result-json>"
  ],
  "evidence": [
    "Commit SHA, model identifier/hash, runtime versions and hardware are recorded.",
    "Corpus manifest and scoring normalization are named.",
    "Raw and requested-script CER are both present."
  ],
  "state": "draft",
  "source": "design/chinese/model-strategy.md"
}
```

Do not open this task until the benchmark validator and exact output path are implemented.

## 4. How to split the large roadmap packages

The first roadmap used S/M/L work packages. Those are useful for architecture planning but **too broad for contributor advertising**. Split them as follows:

### CHN-30 postprocessor audit

One campaign task per module/component, for example:

- burst-spacing audit;
- filler-filter audit;
- number-normalizer audit;
- prosody audit;
- meeting-quality audit.

Each task may only edit its report row plus a targeted test if the issue explicitly asks for a fix. Do not give an agent “audit all postprocessing.”

### CHN-32 injection

One task per OS/session, already naturally independent.

### CHN-41 model baseline

Separate:
- harness verification;
- model artifact/cache check;
- recognition run;
- performance run;
- result validation.

A single contributor may do several, but the evidence remains independently checkable.

### CHN-21 command grammar

Split by semantic family:
- safe editing;
- selection;
- navigation;
- file/symbol navigation;
- terminal/refactor (later/higher risk).

This makes the false-positive review local and avoids a giant regex PR.

## 5. Required negative test before advertising any task

Per ADR-023, ask:

> What low-effort, fabricated, overly broad, or technically-valid-but-useless submission could pass this task as currently written?

Then add a check that rejects it.

Examples:

| Task | Bad submission that might pass | Required guard |
|---|---|---|
| language status | hardcode `zh-CN` for any `zh` | custom-model + invalid-model fixtures |
| command vector | literal machine translation | native-review evidence + negative prose fixture |
| injection report | “works on Wayland” prose | fixed fixture expected/actual + environment fields + schema validator |
| benchmark | one favorable clip | pinned manifest + minimum sample count + result schema |
| postprocess audit | “looks safe” | named code symbols + fixture/result |
| alternative model | upstream leaderboard pasted into report | local YazSes harness result + dependency/license record |

## 6. Validation-command honesty

A campaign task must never list a command that does not exist yet.

If task A creates a validator and task B consumes it:

- A may be A3/cloud-ready.
- B remains `draft` until A merges and the exact command is available.

This is especially important for the proposed injection and benchmark report validators.

## 7. Agent prompt

Contributors can use ADR-023’s repository-wide agent prompt unchanged. Chinese tasks add one rule:

> Do not make linguistic judgments, claim native-language naturalness, or fabricate hardware/model measurements. Stop and request the named human evidence when the contract says it is required.

## 8. Transition from design to campaign

After the ADR PR is accepted:

1. Create the small umbrella issues.
2. Choose the first 5–10 lowest-coupling tasks.
3. Complete ADR-023’s internal two-agent ambiguity test.
4. Add only verified tasks to `campaign/tasks.json`.
5. Run `uv run python scripts/campaign.py --generate`.
6. Run `uv run python scripts/campaign.py --check`.
7. Release tasks in a small batch.
8. Measure review cost and retire/rewrite tasks that attract broad or low-evidence diffs.

The design roadmap remains the dependency graph; `campaign/tasks.json` becomes the execution queue.
