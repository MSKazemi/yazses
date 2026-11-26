# Start plans for the November 2026 landscape recommendations

**Date:** 2026-11-19
**Status:** Planning note (not a decision). No default, dependency, pin, config key or engine is changed by this note.
**Repository snapshot:** main at 8ecfd4ae (YazSes 2.51.0)
**Source:** [Offline voice tech landscape, November 2026](2026-11-19-offline-voice-tech-landscape.md) — item numbers N1–N6 and M1–M7 are that note's.
**Governing records:** [ADR-030 breadth freeze](../adr/adr-030-agent-era-direction.md), [ADR-019 egress inventory](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-021 invest in error cost](../adr/adr-021-invest-in-error-cost.md), [ADR-033 reproducible ASR evaluation gate](../adr/adr-033-reproducible-asr-evaluation-gate.md).

## How to read this

Every item gets the same fields: **goal**, **freeze status**, **what exists today**, **steps**,
**tests**, **docs**, **done when**, **size** and **risks**. Each item is one PR (AGENTS.md
"one concern per PR") unless a step says otherwise.

### Freeze status first

ADR-030 §3 freezes breadth until the first substantive issue from a non-contributor. It allows
bug fixes, wiring of already-advertised capabilities, removal, tests/CI/packaging, docs, and
work on Pillars 1–2. Its 2026-11-01 amendment says the freeze applies to "further biosignal
capabilities and new device families". That sorts the thirteen items into three lanes:

| Lane | Meaning | Items |
|---|---|---|
| **Build now** | Allowed under the freeze as written | N1, N2, N3, N4, N5, N6, M4, M5 |
| **Upgrade now, new behaviour waits** | The existing capability may be upgraded; the new behaviour is a *Proposed* ADR | M1 |
| **Proposed ADR or research issue only** | New capability or new device family; stops at a written record | M2, M3, M6, M7 |

Items in the third lane get a plan for the *record* plus a plan for the build, so the build can
start the day the freeze is lifted or an amendment names it.

### Gates that apply to every code item

```sh
uv run python -m pytest tests/ -n auto
uv run ruff check src tests scripts
uv run mypy src                          # must stay at zero issues
uv run python scripts/gen-docs.py        # after any config key or CLI change
```

- New config keys ship dormant (rule 2) and are L3: the owner signs off.
- New heavy dependencies are optional extras, imported lazily (rule 3), with a `>=` floor at the latest stable release (rule 4).
- A new outbound primitive fails `tests/test_egress_inventory.py`; none of the items below should need one. If one does, stop and read ADR-019 first.
- `CHANGELOG.md` gets an `[Unreleased]` entry for every user-visible change.

### Suggested order

1. **Week 1:** N1 (docs), N5 (MCP matrix, test-only), M5 (Silero floor), N6 (protocol text).
2. **Week 2:** N3 (cleanup endpoint), N4 (git hints), M4 (grammar-constrained router).
3. **Week 3:** N2 (pyannote measurement — needs the ADR-033 machine and corpus), M1 upgrade half.
4. **Records, any time:** Proposed ADRs for M1-streaming, M2, M3, M6; research issue for M7.

---

## N1 — Correct the stale public claims

**Goal.** Public comparison pages say only what is true on 2026-11-19 (ADR-030 Pillar 1.4).

**Freeze status.** Build now (documentation).

**What exists today.** The stale rows are listed in the landscape note's "Stale claims" section.
Confirmed in the tree at this snapshot:

- `docs/comparison.md:21` — Handy row; and `:121` "Handy has no voice commands" is still true, but `:108` "Handy and TalkType are dictation tools" undersells Handy v0.10 file transcription.
- `docs/comparison.md:32` — "Windows Voice Typing | No (cloud)": wrong on Copilot+ PCs (fluid dictation, English only).
- `docs/comparison.md:33` — "Apple Dictation | Partial": understates OS 27 on 12 GB+ devices.
- `docs/comparison.md:348` onward — TalkType section; the project is now TuxTalk.
- `docs/compare/yazses-vs-handy.md:31` — "Transcribe existing files | No" for Handy is now wrong.
- The front-matter `description` at `docs/comparison.md:3` names TalkType.

**Steps.**

1. Re-verify each claim against its primary source on the day of the edit (release notes, Microsoft Support, Canonical). The VS Code on-device dictation claim rests on one aggregator — verify it before writing it, or leave it out.
2. Edit the rows. Prefer qualified cells ("Yes, Copilot+ PCs, English only") over a bare Yes/No.
3. Rename TalkType → TuxTalk, keep one sentence noting the old name so search still finds it.
4. Update the Handy, FluidVoice and OpenWhispr sections (file transcription; FluidMeet; OpenWhispr meetings and agent actions).
5. Fix the Whispering link (`epicenter-so/epicenter` → `EpicenterHQ/epicenter`).
6. Add Ubuntu 26.10's Myna wherever the page says Linux has no built-in.
7. Check translated comparison pages: hand-owned locales get the same factual fix; drafts are regenerated from `scripts/translations.py`, never hand-edited.
8. Update the Handy star count in `design/research/2026-08-15-adjacent-projects.md` with a dated figure.

**Tests.** `tests/test_citation_hygiene.py` (landing pages, no `.pdf`), the l10n link tests, and the docs build.

**Docs.** This item *is* docs. `CHANGELOG.md`: one "Docs" line.

**Done when.** Every row in the landscape note's stale-claims table is either fixed or marked "not changed, because …".

**Size.** S (half a day). **Risk.** Low. Competitor pages change monthly — date the page ("as of November 2026").

---

## N2 — Measure pyannote community-1 against 3.1

**Goal.** Decide, with YazSes's own numbers, whether `yazses transcribe --diarize` should move from `pyannote/speaker-diarization-3.1` to `pyannote/speaker-diarization-community-1`.

**Freeze status.** Build now. This is the engine-question-by-measurement of Pillar 1.3, applied to diarization, and it changes no capability.

**What exists today.** `src/yazses/recimport/pyannote_backend.py:70` pins `PIPELINE_ID = "pyannote/speaker-diarization-3.1"`; `:225` `diarize()` returns `DiarTurn`s that `recimport/align.py` assigns to words. The gated-repo and telemetry handling at `:49–:150` already exists and must keep working.

**Steps.**

1. **Measurement first, no code change in `src/`.** Write a script under `scripts/` (or extend the ADR-033 harness) that runs both pipelines on the same synthetic or explicitly consented multi-speaker fixtures and reports DER, JER, speaker-count error and wall time on the reference machine.
2. Record the result with ADR-033's fields: pinned revision and hash, machine, normaliser, corpus.
3. **Only if community-1 wins:** make the pipeline id a module constant change (not a new config key), add the model to the model manifest with its licence (CC-BY-4.0 → attribution in the licence notices), and consume `exclusive_speaker_diarization` so each instant has one speaker. That removes overlap ambiguity in `align.py`.
4. Keep a one-release escape hatch: if loading community-1 fails, the error names the model and how to accept its terms, as the 3.1 path does now (`_gated_model_error`).

**Tests.**

- Unit: a fake pipeline object returning an `exclusive_speaker_diarization` annotation; assert `diarize()` maps it to `DiarTurn`s and that `align.py` never assigns a word to two speakers.
- Regression: the existing pyannote backend tests still pass with the new id.
- Decoder-stack marker so the FreeBSD leg skips, not fails (`tests/decoder_stack.py`).

**Docs.** `docs/models.md` (diarization model and licence), `docs/benchmarks.md` (the measured table), `CHANGELOG.md`.

**Done when.** A measured table is committed, and either the pin changes with tests or the note records "3.1 stays, because …".

**Size.** M (2–3 days, mostly measurement). **Risks.** Hugging Face gating terms for community-1 may differ from 3.1; a fixture corpus too small to separate the two; licence attribution missed.

---

## N3 — Cleanup through any OpenAI-compatible loopback server

**Goal.** Users who already run llama-server, LM Studio, Ollama or vLLM locally can point YazSes's LLM cleanup at it, with any model, without YazSes depending on `llama-cpp-python`.

**Freeze status.** Build now — it extends an existing, advertised capability (`[disfluency] llm_enabled`). The new config keys are L3: owner sign-off.

**What exists today.** `src/yazses/postprocess/llm_cleanup.py`:

- `_complete_ollama()` (`:289`) POSTs to `{endpoint}/api/generate` with the model **hardcoded** as `"qwen2.5:1.5b"`. A user with any other Ollama model gets a 404 and a silent fallback to raw text. That is a bug worth fixing on its own, first.
- `is_loopback_endpoint()` (`:41`) and `endpoint_is_permitted()` (`:97`) already confine the URL to loopback; ADR-019's inventory lists the module (`tests/test_egress_inventory.py:59`). The guard is the whole protection and must not change.
- Safety checks `_length_ratio_ok` and `_tokens_preserved` (`:110–:170`) reject a rewrite that drops numbers or identifiers.

**Steps.**

1. **PR 1 (bug fix):** add `llm_endpoint_model: str = ""` to `DisfluencyConfig` (`src/yazses/config.py` ~`:397`). Empty keeps `qwen2.5:1.5b` so existing installs do not change. Pass it in `_complete_ollama`.
2. **PR 2 (feature):** add `llm_api: str = "ollama"` with values `"ollama"` and `"openai"`. For `"openai"`, POST to `{endpoint}/v1/chat/completions` with `messages=[system, user]`, `temperature=0`, `max_tokens`, and read `choices[0].message.content`. Same `urllib` primitive, same `endpoint_is_permitted()` gate, same timeout and safety checks.
3. Send the system prompt as a *system* message rather than prefixed text; keep `_prompt()` for the Ollama path.
4. Disable "thinking" output: send `"think": false` for Ollama; for OpenAI-style servers, strip a leading `<think>…</think>` block before the safety checks, and count the result as a rejection if nothing remains.
5. Run `scripts/gen-docs.py` (new keys).
6. **Benchmark (separate, no code):** Qwen3.5 0.8B/2B/4B and Gemma 4 E2B/E4B GGUFs, Q4_K_M, thinking off, on the reference CPU. Measure p50/p95 latency for a 30-word and a 120-word burst, the rejection rate of the safety checks, and number/identifier preservation on the existing number-guard fixtures. Recommend one model in `docs/` with its measured numbers.

**Tests.**

- `tests/test_llm_cleanup.py`: a fake loopback HTTP handler (no network) that asserts the OpenAI path's URL, payload shape and model; a response with a `<think>` block; a response that drops a number → rejected.
- The loopback guard tests still pass with `llm_api = "openai"` and a remote URL → refused.
- Egress inventory test unchanged and green (no new primitive, same module).

**Docs.** `docs/configuration.md` (generated), a short how-to "Use your own local model server for cleanup", `CHANGELOG.md`.

**Done when.** Both API styles work against a fake server in tests, the hardcoded model is gone, and the benchmark table names a recommended model.

**Size.** S for PR 1, M for PR 2, M for the benchmark. **Risks.** OpenAI-compatible servers differ in small ways (missing `max_tokens`, streaming defaults) — send `stream: false` explicitly and test against two real servers by hand before release.

---

## N4 — Project name and git branch as local recognition hints

**Goal.** When dictating into a terminal or editor inside a git repository, the project name, branch name and its words ("fix-tray-crash" → "tray", "crash") bias recognition and cleanup, computed on the machine. This is the agent-era user of Pillar 2.

**Freeze status.** Build now, as an extension of the existing `[context]` capability (ADR-v2-004). One new config key, L3.

**What exists today.** `ContextConfig` (`src/yazses/config.py:980`) composes Whisper's `initial_prompt` from window title, selection, clipboard and LSP symbols, off by default, never stored. `src/yazses/gitvoice/plan.py` already knows how branch names are *spoken* (slash, hyphen) — reuse that mapping instead of writing a second one.

**Steps.**

1. Add `use_git: bool = False` to `ContextConfig`. Off even when `[context]` is on, because it is a new signal.
2. **Pure module** `src/yazses/context/git_hint.py` (or beside `commands/context.py`, following its pattern): given a directory, walk up to find `.git`, read `HEAD` **as a file** (no subprocess, no `git` binary), and return `(repo_name, branch)`. Handle detached HEAD, worktrees (`.git` is a file pointing elsewhere) and submodules.
3. Getting the directory: the focused terminal's working directory is platform-specific. Add it behind a Protocol method in `src/yazses/platform/base.py` (e.g. `focused_cwd() -> Path | None`), implemented first on Linux via `/proc/<pid>/cwd` of the focused window's process; macOS and Windows return `None` until implemented. No `sys.platform` branching outside `platform/`.
4. Split the branch into hint terms with the spoken-punctuation table from `gitvoice/plan.py`, cap them under `max_terms`, and feed them into the existing prompt composition.
5. Never log the repo path or branch; follow the existing "read at decode time, never stored" rule.

**Tests.**

- Pure: temp directories with a normal repo, a detached HEAD, a worktree `.git` file, a nested directory, no repo → expected tuples.
- Composition: hints appear in the prompt only when both `enabled` and `use_git` are true.
- Platform: a fake platform returning a cwd; the real Linux reader tested against the test process's own `/proc/self/cwd`.

**Docs.** `docs/configuration.md` (generated), a line in the AI-agent use-case page, `CHANGELOG.md`.

**Done when.** Dictating "push fix tray crash" in a repo on branch `fix-tray-crash` with `use_git` on produces the branch's words in the prompt, in tests.

**Size.** M. **Risks.** Focused-process lookup on Wayland is limited (see the GNOME/KDE/Wayland note); ship Linux X11 first and say so.

---

## N5 — MCP client compatibility matrix against 2026-07-28

**Goal.** Know, rather than guess, which MCP clients still talk to YazSes's server, before planning a protocol migration (ADR-032, Pillar 2).

**Freeze status.** Build now (tests, Pillar 2).

**What exists today.** `src/yazses/mcp/protocol.py:40` `PROTOCOL_VERSION = "2025-06-18"`; `:47` `SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")`; version negotiation at `:294–:302` answers with the client's version if supported, else ours. The 2026-07-28 revision removes the `initialize` handshake and sessions and replaces server-initiated requests with Multi Round-Trip Requests. Roots, Sampling and Logging are deprecated but keep working for at least 12 months.

**Steps.**

1. **Matrix (docs + manual run):** for Claude Code, Claude Desktop, Codex CLI, Cursor, VS Code (Copilot agent) and Gemini CLI at their current versions, record: version they request, whether they still send `initialize`, whether `tools/list` and `tools/call ask_human` succeed. Store as `docs/mcp-compatibility.md` with a date per row.
2. **Test fixtures:** capture each client's first frames (synthetic, no user data) into `tests/fixtures/mcp/` and replay them through `protocol.py` in `tests/test_mcp_protocol.py`.
3. **Decide the migration from the matrix,** not before. If a client sends no `initialize` under 2026-07-28, the server must answer `tools/list` without a prior handshake; write that as a small Proposed ADR under ADR-032 and implement it as a separate PR.
4. Add `"2026-07-28"` to `SUPPORTED_PROTOCOL_VERSIONS` only when the server actually implements its required behaviour.

**Tests.** Replay tests per client fixture; a test that an unknown future version gets our latest version back, not an error.

**Docs.** `docs/mcp-compatibility.md` (new), link from the MCP how-to; `CHANGELOG.md` only when behaviour changes.

**Done when.** The matrix is published with dated rows, and either "no change needed" or a Proposed ADR for the migration exists.

**Size.** S–M. **Risks.** Client behaviour changes with each release — the page must carry dates, and the replay fixtures pin what was observed, not what is current.

---

## N6 — Adopt SAPC2 latency definitions

**Goal.** YazSes's dysfluency and streaming results use the same latency vocabulary as the field, so they can be compared with published dysarthric-ASR work.

**Freeze status.** Build now (protocol text; no data import).

**What exists today.** `design/research/2026-11-03-dysfluency-fidelity-evaluation-protocol.md`, the streaming commit replay protocol under `design/specs/`, and `src/yazses/stt/latency.py`.

**Steps.**

1. Read the SAPC2 latency toolkit's definitions on its landing page (first-token latency, final-token latency, real-time factor; exact names as SAPC2 publishes them).
2. Map each to an existing YazSes measurement point, or add a named point to the replay spec if one is missing. Do not rename existing metrics; add an "SAPC2 equivalent" column.
3. Note the data-use-agreement boundary: YazSes does not import SAPC data, only definitions. That fits the research-consent ADR (ADR-v2-150).

**Tests.** If `stt/latency.py` gains a named measurement, a unit test on synthetic timestamps.

**Docs.** The two protocol documents; nothing user-facing.

**Done when.** Both protocols carry a mapping table with a citation to the SAPC2 landing page.

**Size.** S. **Risk.** The toolkit's definitions may change before the NeurIPS 2026 results; cite the version.

---

## M1 — Moonshine v2 (upgrade now; streaming waits)

**Goal.** Move the existing Moonshine engine to the maintained `moonshine-voice` package and v2 models; later, use its native streaming partials.

**Freeze status.**

- **Upgrade half — build now:** a dependency change inside an advertised capability (`stt-moonshine`).
- **Streaming half — Proposed ADR only:** partials typed into the target app are new behaviour, and the [streaming delivery boundary ADR](2026-11-03-proposed-adr-streaming-delivery-boundary.md) is still *Proposed*.

**What exists today.** `src/yazses/stt/moonshine.py`; the factory branch at `src/yazses/stt/factory.py:98–:118` (loud fallback to faster-whisper if the dependency is missing); `pyproject.toml:309` extra `moonshine = ["useful-moonshine-onnx>=20251121"]`; `src/yazses/stt/streaming.py` and `streaming_replay.py`; `tests/test_r7_stt_moonshine_long_tail.py`.

**Steps — upgrade.**

1. Check `moonshine-voice` on PyPI: latest version, wheels for Linux x86_64/aarch64, macOS arm64, Windows x86_64, Python 3.11–3.14, and whether it still uses ONNX Runtime (the `pyproject.toml:641` note about the shared `onnxruntime` constraint).
2. Measure under ADR-033: v1 vs v2 (tiny/base) WER and latency on the reference machine, English only. Refuse legacy non-English Community-License checkpoints in `refuse_unsupported_language`.
3. Swap the extra's dependency, adapt `moonshine.py` to the new API, keep `moonshine_onnx` imports out and update the `[tool.mypy]` override list.
4. Re-run `make feature-sizes` (the feature's dependencies changed).

**Steps — streaming (record now, build later).** Write an addendum to the streaming Proposed ADR. Moonshine v2's bounded-attention partials are append-only within a chunk, which removes some prefix-retraction cases. Partials go to the overlay only, and key release still commits. Validate it with `streaming_replay.py` before any delivery change.

**Tests.** The existing Moonshine tests with the new package mocked; a factory test that a missing `moonshine_voice` still produces the loud fallback; the decoder-stack skip marker.

**Docs.** `docs/models.md`, `docs/benchmarks.md`, `CHANGELOG.md`, regenerated feature sizes.

**Done when.** `yazses features enable stt-moonshine` installs v2, the measured table is committed, and the streaming addendum exists.

**Size.** M (upgrade), S (addendum). **Risks.** No published x86 CPU latency for v2; a wheel gap on one OS would block the swap — keep the old package as the fallback extra for one release if so.

---

## M2 — transcribe.cpp engine for files and meetings

**Goal.** One MIT runtime, from GGUF files, that gives `yazses transcribe` and meeting mode access to Granite Speech 4.1, Qwen3-ASR and Streaming Sortformer without torch.

**Freeze status.** Proposed ADR and research spike only (new engine = new capability).

**Record to write now.** `design/research/<date>-proposed-adr-transcribe-cpp-file-tier.md`. It should cover:

- scope: files and meetings only, never hold-to-talk;
- licences of each model it would expose;
- how it fits the model manifest;
- the fallback to faster-whisper;
- the single-maintainer risk.

**Spike (no `src/` change).**

1. Does `pip install` of the Python binding give a wheel on Linux, macOS and Windows for Python 3.11–3.14? Record each result. If any is "build from source", the ADR must say who owns that build matrix.
2. On the reference machine, transcribe the ADR-033 file set with Granite 4.1 2B Q4_K_M and Qwen3-ASR 0.6B: WER, real-time factor, peak RAM, and whether word timestamps are present (required by `recimport/align.py`).
3. Check whether the GGUF files carry a stable hash for the manifest.

**Build plan (when allowed).**

- Engine adapter `src/yazses/recimport/` side first, behind the existing `recimport/factory.py`.
- New extra `transcribe-cpp`, lazy import, pinned model revisions.
- Same alignment and diarization contract as today.

**Done when (for now).** The Proposed ADR and the spike's three answers are committed.

**Size.** S (record + spike), L (build). **Risks.** No release tags upstream; API churn.

---

## M3 — BCI HID switch consumer

**Goal.** A brain-computer interface that speaks Apple's BCI HID protocol (usage page 0x60, decoding on the device) becomes a YazSes switch on macOS, Linux and Windows — mapping ToggleDictation, Select, Next, Previous and Escape to existing YazSes actions.

**Freeze status.** Proposed ADR only. The ADR-030 amendment names "new device families" explicitly.

**Record to write now.** A research-record ADR in the style of [ADR-v2-156](../adr/adr-v2-156-maixcam2-text-link.md) ("research record only"), with:

1. The report layout from Apple's developer page: 32 buttons, pointer, item-selection and signal-quality reports. Record what the host sends back (the scanning-focus position, never the focused key).
2. Mapping to existing actions. It should reuse the biosignal switch event types in `src/yazses/biosignal/types.py` so the false-positive governor of ADR-v2-153 applies unchanged.
3. Signal-quality report → refuse to act below a threshold (ADR-021: fire rarely, on a checkable signal).
4. Per-OS reading: hidraw on Linux, IOHIDManager on macOS, Windows HID — behind a Protocol, not `sys.platform` checks.

**Device-free example (allowed as research, like ADR-v2-156).** A pure parser under `design/` or `examples/` that turns synthetic report bytes into events, with its own tests. No `src/` capability and no registry entry.

**Build plan (when allowed).**

- `src/yazses/biosignal/bci_hid.py` (pure parser) and `platform/<os>/` readers.
- An optional extra if a HID library is needed.
- Off by default and absent from a default daemon (`tests/test_biosignal_default_stays_out.py`).

**Done when (for now).** The record and the device-free example with tests exist.

**Size.** S (record + example), M–L (build). **Risks.** No device to test against; whether user-space apps can open the device on each OS is unverified.

---

## M4 — Grammar-constrained command router

**Goal.** The small-model command router can only output a command that already exists, with arguments YazSes re-checks in plain code before `cmdsafety`. This is the structural defence against instructions hidden in audio.

**Freeze status.** Build now — it hardens an existing capability (Tier 2 SLM router) and adds no command.

**What exists today.** `src/yazses/commands/slm_router.py` prompts `llama-cpp-python` with a list of intents and asks for one line of JSON. Nothing constrains the output, so the model can return an unknown intent or arbitrary `args`. Tests: `tests/test_slm_router_is_wired.py`, `tests/test_docs_describe_the_slm_router_honestly.py`.

**Steps.**

1. **Pure module** `commands/slm_schema.py`: build a JSON Schema from the real intent/action table in `commands/grammar.py`. Use enums for `intent` and `action`, typed `args` per action (e.g. `go_to_line` → integer within the bounds the regex grammar already enforces), and `confidence` in 0–1.
2. Pass it to llama.cpp as a grammar (`LlamaGrammar.from_json_schema(...)`, or `response_format={"type": "json_object", "schema": ...}` depending on the installed binding version). Keep a fallback for older bindings: no grammar, but step 3 still applies.
3. **Re-validate in pure code** after decoding: unknown intent → no action; argument out of bounds → no action; then the existing `cmdsafety` path. Never trust the grammar alone — it guarantees shape, not truth.
4. Generate the schema from the grammar table so a new command cannot drift from the router.

**Tests.**

- Pure: schema built from the table contains every action; a hand-written malicious output (`"action": "run_command", "args": {"cmd": "rm -rf ~"}`) is rejected by re-validation unless the existing grammar would allow it.
- A synthetic accuracy benchmark: 200 paraphrased commands and 200 prose sentences (no real user audio), router decision accuracy with and without the grammar.
- Mocked `Llama` asserting the grammar argument is passed.

**Docs.** The honesty test means `docs/` must describe exactly what the router does — update that page; `CHANGELOG.md`.

**Done when.** Unconstrained output can no longer reach `cmdsafety` with an unknown intent, in tests.

**Size.** M. **Risks.** Grammar decoding is slower on some builds; measure, and fall back to re-validation-only if latency doubles.

---

## M5 — Silero VAD v6

**Goal.** Better speech/noise separation in meeting mode, from the dependency YazSes already uses.

**Freeze status.** Build now (dependency bump; rule 4 asks for the latest stable).

**What exists today.** `pyproject.toml:353` extra `silero = ["silero-vad>=5.1.2"]`, used by `src/yazses/meeting/silero_vad.py` (ONNX path, no torch); also listed at `pyproject.toml:445`.

**Steps.**

1. Read the official silero-vad release notes for v6.x: API changes, whether the ONNX model path and `onnxruntime` requirement are unchanged, the published noise figures (the landscape note's figure is secondary).
2. Raise the floor in both places to the latest stable 6.x; run `make feature-sizes`.
3. Re-run the meeting segmenter's replay fixtures; compare segment counts and boundaries against v5 on the same synthetic audio, and record the difference in the PR body.

**Tests.** Existing `meeting/` tests; add one that pins the model output shape the backend expects, so a future API change fails loudly.

**Docs.** `CHANGELOG.md`; `docs/models.md` if it names the VAD version.

**Done when.** The floor is 6.x, tests are green, and the PR body shows the before/after segment comparison.

**Size.** S. **Risk.** Threshold defaults may shift with the new model; keep YazSes's own threshold explicit.

---

## M6 — Learn vocabulary from corrections in any app

**Goal.** When the user fixes a misrecognised word after YazSes types it, YazSes learns the correction — in any accessible app, not only Neovim.

**Freeze status.** Proposed ADR only. It extends an existing capability, but it reads text in arbitrary applications, which is a new privacy surface under ADR-011 and ADR-019's "learning corpus never leaves" category.

**What exists today.** `src/yazses/learning/edit_watch.py` — `EditWatcher` reads the editor region back after injection, without logging keystrokes, and records near-by corrections. Its reader is injected and is wired only to Neovim's `--listen` socket. `corrdict/` mines corrections; `learning/store.py` and `crypto.py` hold them encrypted. Tests: `tests/test_learning_edit_watch.py`.

**Record to write now.** A Proposed ADR covering:

- an AT-SPI2 text reader on Linux (macOS AX API and Windows UI Automation later);
- that it reads only the region YazSes just typed, once, after a delay;
- that password fields and apps on a deny-list are never read;
- what is stored (the word pair only, encrypted, through the existing store);
- how the user reviews and deletes it.

**Build plan (when allowed).**

- A `read_current_text` implementation behind a new platform Protocol method.
- The diff logic stays as it is.
- Off by default behind its own key.
- A visible indicator the first time it learns something.

**Done when (for now).** The Proposed ADR exists.

**Size.** S (record), M (build, Linux). **Risks.** AT-SPI text access varies by toolkit; Electron apps often expose nothing.

---

## M7 — Meta Neural Band gesture adapter

**Goal.** Use the band's calibration-free wrist gestures as a YazSes switch, offline.

**Freeze status.** Research issue only (`evergreen:research`). New device family, and the only access is through unofficial, reverse-engineered BLE tools that a firmware update can break.

**Record to write now.** An issue recording:

- the community projects and their licences (RawMeta MIT; Kinesis unchecked);
- the one-time Meta-account enrolment, which is outside YazSes's offline boundary — even if nothing is sent during use, setup needs a cloud account;
- the firmware-breakage risk;
- the conditions for revisiting: an official desktop SDK, or a real user asking.

**Build plan.** None until those conditions are met. If they are, it reuses the M3 event mapping and the ADR-v2-153 false-positive governor.

**Size.** XS. **Risk.** Building on it now would advertise something that can break silently — exactly what Pillar 1 forbids.

---

## Watch list (no plan, revisit on a trigger)

| Item | Trigger to revisit |
|---|---|
| NVIDIA Nemotron streaming, Parakeet Realtime EOU, Nemotron-3-Diarization | Licence review passes the model-manifest process, and a CPU latency figure exists |
| Microsoft's int4 ONNX Nemotron (arXiv 2604.14493) | Weights published |
| Voxtral Realtime 3 | Open weights confirmed |
| Ubuntu Myna | A stable release, or an interface YazSes could interoperate with |
| UniGaze / GazeTorch | Weight licences confirmed |
| OpenVINO GenAI, Apple Foundation Models SDK | A cleanup backend need that N3 does not meet |
| EN 301 549 V4.1.1 | Cited in the Official Journal |
| Dragon end-of-life (2026-12-31, reseller-reported) | Confirmed by Microsoft — a migration guide for command-grammar users becomes worthwhile |
