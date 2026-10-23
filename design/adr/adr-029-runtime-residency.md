# ADR-029 — Runtime residency: RAM and CPU proportional to what is enabled

**Status:** Accepted (2026-10-22). Proposed 2026-10-21. First step implemented: the
dictation engine's opt-in idle unload, `[stt] idle_unload_s` (see *Implementation status*).
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-016-dependency-budget]] (features pay for themselves — in bytes
and imports; this ADR extends it to RAM and CPU), [[adr-018-feature-packs-and-the-plugin-question]]
(§1 show the price first; §3 the isolation boundary that would reopen plug-ins),
[[adr-019-egress-inventory-and-escalation]] (a worker inherits the inventory, adds no
row), [[adr-028-feature-addon-packs]] (download and disk; this is the other half),
[[adr-v2-073-adaptive-latency-governor]] (`latency/pool.py`, the one place today that
holds more than one engine), [[adr-011]] (nothing leaves the machine).
Research input: [`design/research/2026-10-21-pay-for-what-you-enable.md`](../research/2026-10-21-pay-for-what-you-enable.md)
§4 (gaps 1, 2, 8), §5 (the runtime half) and §6 (layer L6, roadmap item 3).
Policy module: `src/yazses/system/residency.py` (pure, stdlib-only, lands with this ADR).

Evidence labels, as in the research note: **[M]** measured in this repository on
`origin/main` `fa058766` · **[F]** a primary source says so · **[O]** engineering
judgement · **[U]** not verified.

---

## Context

The brief behind ADR-028 was *"a user who selects a few features downloads and runs only
those features' libraries and models; a user who selects everything downloads more and uses
more CPU and RAM."* ADR-016 and ADR-028 deliver the first half: a disabled feature costs
zero bytes and zero imports, and the guards hold (`tests/test_base_weight_budget.py`,
`tests/test_dormant_features_stay_unimported.py`, the AST scan for module-scope optional
imports). The second half — *uses more CPU and RAM* — only holds if a feature's memory and
CPU also **leave** when the feature is not in use. Today they do not.

What the code does, measured [M] on `fa058766` (Linux x86_64, CPython 3.12, base-only
install):

| Fact | Figure | Where |
|---|---|---|
| The speech model loads at daemon start and is never unloaded | base.en: **188 MB** resident after load, **216 MB** after the first decode, **343 MB** peak during the load | `core/daemon.py::_build_pipeline` → `stt/factory.build_engine`; `stt/faster_whisper.py` has no unload |
| The latency governor's second model loads once the CPU is busy and then stays | tiny.en: about **75 MB** download, about **116 MB** RAM | `latency/pool.py::EnginePool` memoises and never evicts; `latency` sits in the RECOMMENDED tier that first run switches on |
| Base import weight | `import yazses.cli` 63–73 ms / 18 MB; `import yazses.core.daemon` 250–310 ms / 33 MB | — |
| The import-time ceiling | baseline 1 172 375 µs × 1.5 tolerance ≈ **1.76 s**, about 6× the measured 0.30 s | `scripts/dependency_budget_baseline.json`, `scripts/check_dependency_budget.py` |
| RAM or idle-CPU budget | none | `tests/` |

The features that load the heaviest stacks — diarization (sherpa-onnx), the camera
features (MediaPipe + OpenCV through the shared perception source), TTS (Kokoro ONNX),
the LLM cleaner (llama.cpp, or a loopback server) and the voiceprint stack (torch,
speechbrain) — each load on first use and then keep their model for the life of the
daemon. Nothing bounds how many are resident together. A user who enabled eye control,
read-back and the cleaner pays for all three from the first time each ran, however long
ago.

Two properties of the native stacks shape the decision:

- **Native allocators do not reliably return freed memory to the OS.** ONNX Runtime,
  CTranslate2 and torch keep their arenas mapped after a model is deleted; `del engine`
  frees Python's references and leaves RSS where it was [O, consistent with the research
  note §5 item 4; the exact retention per library is **[U]** until the nightly job
  measures it]. For those stacks a process exit is the only release that is guaranteed.
- **A worker is also a fault boundary and the isolation boundary ADR-018 named.** ADR-018
  §3 declined third-party plug-ins and wrote down the one thing that would reopen the
  question: "a separate process with no network namespace and no injector handle,
  communicating over the existing IPC". A first-party worker is that process, built for
  our own heavy features first.

The precedent, from the research note §2 and §5: Ollama keeps a model loaded five minutes
after its last use (`keep_alive`) and caps loaded models (`OLLAMA_MAX_LOADED_MODELS`)
[F, [Ollama FAQ](https://docs.ollama.com/faq)]; VS Code runs extensions in a separate host
process and activates them lazily [F, [extension host](https://code.visualstudio.com/api/advanced-topics/extension-host)];
Chromium's process model is the fault-isolation half [F, [Chromium](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md)].

## Decision

Residency becomes **policy, in one pure module** (`system/residency.py`), read by the
daemon's loader, by `yazses status`/`doctor`, by the settings window and by the nightly
budget job — rather than a property each feature's factory happens to have. The policy
works on **residency units**, which are coarser than registry slugs: `gaze`,
`facegesture`, `headpointer` and `gesture` share one MediaPipe model through the shared
perception source, so they are one unit and unloading it is one decision
(`residency.UNIT_OF_SLUG`, `unit_for(slug)`).

### 1. Unload after idle, per unit, with a keep-alive — and the core engine stays

Each unit has a keep-alive: how long its model stays loaded after its last use. `None`
means *resident while enabled*. `IdleTracker.due_for_unload(now)` names the loaded units
whose last use is at least that long ago; it fires **at** the boundary (`>=`), never for a
`None` row, and reports longest-idle first.

| Unit | Registry slugs | Default | Loads | Why this number [O] |
|---|---|---|---|---|
| `stt` | the dictation engine | **none** — resident while enabled | at daemon start | **First-word latency is the product.** A user who presses the key waits for the first word; a 2–6 s reload on a cold engine would be the feature failing. |
| `latency` | `latency` | 600 s | first high-load burst | The governor only asks for the light model while the 1-minute load average is above `high_load`; ten idle minutes outlive that average many times over, and `EnginePool` already loads in the background, so a reload costs the user nothing on the hot path. |
| `diarize` | `diarize`, `recimport`, `meeting` | 300 s | first diarized decode | Ollama's default. A meeting is continuous use; a five-minute gap after it is the meeting having ended. |
| `gaze` | `gaze`, `facegesture`, `headpointer`, `gesture` | 120 s | first camera lease | The shared perception source already closes the camera on the last lease (`perception/source.py`); the FaceLandmarker is small and reloads in about a second [U], so a short timer buys RAM cheaply. Camera features are session-shaped: idle gaps are seconds, not minutes. |
| `tts` | `read-back` | 300 s | first read-back | Read-back follows a dictation, and dictations are minutes apart. |
| `llm` | `llm-cleanup` | 300 s | first cleaned dictation | The same class of model Ollama applies its five minutes to; when the cleaner points at a loopback Ollama, Ollama's own `keep_alive` does this and ours is a no-op. |
| `voiceprint` | `cocktail`, `voiceguard`, `multiprofile` | 600 s | first guarded burst | The torch stack is the slowest to bring back — a worker spawn plus `import torch` [U, seconds to tens of seconds] — and it is consulted per burst, so a short timer would thrash. Twice Ollama's default. |

**The core engine's opt-in.** Low-RAM machines get `[stt] idle_unload_s` (proposed key;
default `0` = never, the behaviour today). When set, the engine is unloaded after that
many idle seconds and reloaded on the next hold — with the overlay's existing "loading"
state shown, because the first word will be late and the user must see why. It is opt-in
because the default user has not asked to trade latency for RAM. The six heavy units get
`[residency] keep_alive_s.<unit>` overrides (proposed table key) with the defaults above;
`0` disables the timer for that unit. **No config key is added by this ADR's own change**;
the integration change adds them (see *Integration hand-offs*).

An unload is a **release of our references plus, where the unit runs in a worker, the
worker's exit**. In-process units (`stt`, `latency`, `tts`) cannot promise the OS gets the
pages back (above); the nightly table will say how much each actually returns, and that
figure — not the policy — decides whether `tts` later moves to a worker.

### 2. The heaviest stacks run out of process

`residency.WORKER_UNITS = {gaze, llm, voiceprint, diarize}`; `placement(unit)` answers
`"worker"` or `"in_process"` and raises for an unknown unit, so a misspelling can never
mean "in process by default". The four are the native stacks whose allocators keep freed
memory mapped (MediaPipe + OpenCV; llama.cpp; torch; sherpa-onnx), and the ones whose
crash must not take dictation down.

**What a worker is.** One child process per unit, started on the unit's first use by the
daemon, speaking the **existing JSON-RPC 2.0 IPC** (`ipc/protocol.py`, ADR-010) over a
private socket the daemon creates — the daemon is the client, the worker the server. The
worker gets **derived data only**: audio frames or a frame-shaped tensor in, text, labels,
embeddings or landmark numbers out. It holds **no injector handle, no hotkey, no network
primitive** — `tests/test_egress_inventory.py` scans `src/yazses/`, and the worker
modules live there, so the inventory enforces the last point without a new rule
(ADR-019 §1). A worker exit is the unload. A worker crash is a logged degradation of its
unit (the feature's `NullBackend` path, as `tts/factory.py` already does) and never a
daemon restart.

**What talks over IPC and what does not change.** The worker boundary is drawn where each
feature already has an injected backend Protocol: `recimport/diarizer.py::SherpaDiarizer`
behind `build_diarizer()`, `perception/source.py`'s `FrameProcessor` seam,
`postprocess/llm_cleanup.py::LlmCleaner` behind `build_cleaner()`, and
`voiceprint/base.py::SpeakerEmbedder` behind `build_embedder()`. A worker-side stub
implements the same Protocol by relaying the call. The pure halves — `recimport/align.py`,
`gaze/zones.py`, `headpointer/controller.py`, `facegesture/detector.py`,
`voiceprint/embedding.py` — stay in the daemon, unchanged. The dictation engine, the
latency governor and TTS **stay in process**: the engine because an IPC hop per burst is
first-word latency; TTS because its ONNX session is the same runtime the base already
holds for Whisper, so a worker would buy little.

**Per-feature environments** are permitted *only* for a worker, and only when its stack
conflicts with the base (ADR-028 §1's torch/`libiomp5md.dll` collision is the known case).
An in-process unit never gets its own environment: it would duplicate numpy and ONNX
Runtime and cannot share the process (research note §6, *what not to do*).

### 3. A memory-bounded scheduler: at most N heavy models, LRU eviction

`ResidencyBudget(max_resident, pinned=...)` is Ollama's `OLLAMA_MAX_LOADED_MODELS`:
`admit(unit, now)` records the unit as most recently used and returns the units that must
be unloaded first so the cap holds, least recently used first. The dictation engine is
**pinned** (`ResidencyPolicy.pinned()` is every `None`-keep-alive row): it counts against
the cap — it does use the memory — but is never the one chosen. With a cap of one and the
engine pinned the budget can be over by the engine alone; `over_budget()` reports that
rather than hiding it, and `yazses doctor` should question a cap below two.

Default cap: **3** [O] — the engine plus two heavy features. A laptop running eye control
and read-back together keeps both; a third asks the least recently used one to leave.
Proposed key: `[residency] max_resident`.

`latency/pool.py::EnginePool` is today's one multi-engine holder. It keeps its
memoisation and background loading; the integration gives it the tracker and budget to
consult, so the light model is one more unit rather than a second policy.

### 4. Budgets in CI, so proportionality is a test and not a hope

| Budget | Status | What this ADR decides |
|---|---|---|
| Import time | exists: `check_dependency_budget.py`, baseline 1.17 s × 1.5 | Tighten the tolerance toward the measured 0.30 s once the nightly has three weeks of runs; the ceiling today is 6× the measurement and catches nothing short of a top-level torch import. |
| "Disabled features add zero modules" | half exists: `test_dormant_features_stay_unimported.py` records imports `core/daemon.py` makes at start | Add the `sys.modules` allowlist form: after a default daemon start, the set of `yazses.*` modules loaded is a committed list that may only shrink. |
| Per-unit peak RSS | **missing** | A **nightly** job with real models (Linux x86_64 first, the one platform with measured download sizes), one subprocess per unit — base alone, then base + unit, peak RSS by `resource.getrusage` or pytest-memray `limit_memory` — writing `system/runtime_sizes.json` (RAM twin of `feature_sizes.json`). `residency.check_rss(measured, budget, tolerance=1.2)` is the verdict; `unmeasured()` fails the run for a unit the probe skipped, and an empty measurement is a failure, not zero breaches. **Baseline figures [M] on `fa058766`:** `stt.base.en.loaded` 188, `stt.base.en.after_first_decode` 216, `stt.base.en.load_peak` 343, `latency.tiny.en` 116 (`residency.MEASURED_FA058766_MB`). |
| Idle CPU | **missing** | Same nightly: daemon CPU seconds over 60 s idle with everything off, then with each unit loaded and idle. `RuntimeBudget.idle_cpu_s_per_min` holds the ceiling; a loaded-and-idle model that burns CPU is a polling loop that should not exist. |
| Release that an unload actually unloads | **missing** | The nightly measures RSS after `due_for_unload` fires, per unit — the number that decides §1's "in-process units cannot promise" and whether `tts` moves to a worker. |

The nightly is not a PR gate: it needs real models and a network to fetch them (ADR-019
Class A, the same as `yazses` itself on first use) and takes minutes. A regression is a
report that opens an issue, compared against the **working** baseline — not against the
previous run, which is how a channel that broke and stayed broken hides itself.

### 5. Show RAM and CPU at consent time, next to the download size

ADR-018 §1 shows the marginal *download* before `features enable` fetches anything. The
same row gains the runtime price: *"Eye control: 220 MB download, about 410 MB RAM while
active, unloads 2 min after last use."* The figures come from `runtime_sizes.json`
exactly as disk figures come from `feature_sizes.json`: a committed table with a
generator, rendered offline, instantly, identically for everyone; a stale figure is
acceptable, a hang is not. Until the nightly has produced a row for a unit the catalogue
prints *RAM: not yet measured*, never an estimate presented as a measurement.

### 6. What does not change

- No third-party code. A worker runs this repository's modules; ADR-018 §3 stands. If a
  future ADR ever reopens plug-ins, the worker is the boundary it would build on, and it
  supersedes ADR-018 rather than amending it.
- No new egress row. A worker inherits the inventory because its modules are under
  `src/yazses/` (ADR-019 §1); a worker that gained a socket would fail
  `test_egress_inventory.py` like any module.
- The dictation hot path. The engine stays in process, loaded at start, pinned.
  `idle_unload_s` is opt-in, default never.
- The endpointing and auto-stop paths (`stt/endpoint.py`, `endpoint/autostop.py`,
  `Daemon._build_autostop`) are **not** touched by this ADR or its integration; they
  consume the engine, they do not own its residency.

## Integration hand-offs

This ADR's own change lands the policy module, its tests and this record. The hooks below
belong to other owners and are **not** done here; each is a small, separately testable
diff.

**Quick fix, not this ADR (research note §6 roadmap item 1; another owner):**

- `src/yazses/system/features.py` — move the `latency` row out of `RECOMMENDED` so first
  run stops switching on a second model whose own description says "Off by default"
  (research note §4 gap 2; the row is `_Def("latency", ...)` near line 728,
  `_DEFAULT_ENABLED_TIERS` near line 1849). Its test asserts `latency` is not in the
  default-on set. Done 2026-10-22: the row is OPTIONAL, pinned by
  `tests/test_features_defaults.py`.

**Daemon engine load/unload (the `core/daemon.py` owner):**

- `Daemon._build_pipeline` (line ~1362): after `self._engine = build_engine(cfg.stt)`,
  `tracker.mark_loaded("stt", now)` and `budget.admit("stt", now)` with `"stt"` pinned.
  When `[stt] idle_unload_s > 0`, give `"stt"` that keep-alive instead of `None`.
- Every decode entry that uses `self._engine` or `self._decode_engine()` (the hold-end
  decode near line 2947, `_transcribe_*` near line 4995, the streaming constructor
  `StreamingEngine(self._engine, ...)` near lines 1383 and 6810): `tracker.touch(unit,
  now)` on use. A reload after an idle unload rebuilds `self._engine` **and**
  `self._stream_engine`, since the latter holds a reference to the former.
- A periodic tick calls `tracker.due_for_unload(now)` and, for each unit, the owner's
  `unload()` below, then `tracker.mark_unloaded(unit)` and `budget.release(unit)`. The
  daemon already runs one housekeeping thread of exactly this shape — `_reap`
  (`core/daemon.py` ~line 1252, `while not self._stop_event.wait(tick)`); the residency
  tick is a sibling of it, not a change to it.
- `Daemon._decode_engine` / `latency/pool.py::EnginePool` (lines ~4846–4868, 4857–4904):
  `EnginePool._load` calls `budget.admit("latency", now)` before building and unloads what
  it returns; `get` touches `"latency"` on a hit. `EnginePool.resident()` already exists
  for `yazses status`; add the tracker's `idle_s` beside it.

**Feature-level model owners (one `unload()` each, then the worker stub):**

- `recimport/factory.py::build_diarizer` / `recimport/diarizer.py::SherpaDiarizer` — unit
  `diarize`.
- `perception/source.py::SharedPerceptionSource` — unit `gaze`; the model closes with the
  last lease today, so the keep-alive here delays that close rather than adding one.
- `tts/factory.py::build_tts` — unit `tts`.
- `postprocess/llm_cleanup.py::build_cleaner` / `LlmCleaner` — unit `llm`.
- `voiceprint/factory.py::build_embedder` — unit `voiceprint`.

**Config (the `config.py` owner):** `[stt] idle_unload_s` (int, default 0),
`[residency] max_resident` (int, default 3), `[residency] keep_alive_s` (table, defaults
as §1). Regenerate `docs/configuration.md` with `scripts/gen-docs.py`.

**Consent surface (ADR-018 §1's owner):** `yazses features` and the settings window read
`runtime_sizes.json` when it exists.

Until the daemon hook lands, `system/residency.py` has no importer in `src/` and is
recorded in `tests/test_orphan_modules.py::KNOWN_ORPHANS` with this ADR as the reason;
that entry must be deleted in the same change that wires it. (Done 2026-10-22 with the
`[stt] idle_unload_s` step.)

## Implementation status

**2026-10-22, step 1: `[stt] idle_unload_s`.** The key exists (`SttConfig.idle_unload_s`,
int seconds, default `0` = never, so an existing install is unchanged).
`stt/resident.py::IdleUnloadEngine` wraps the engine only when the value is positive.
This step differs from the hand-off text above in one respect:

- **The daemon does not set `self._engine` to `None` or rebuild `self._stream_engine`.** The
  wrapper stays in place for the daemon's life and only its *inner* engine comes and goes.
  `StreamingEngine`, `EnginePool` (as its base engine) and meeting capture all hold the
  wrapper, so they reload through it and nothing needs rebuilding. Setting the attribute to
  `None` would also have made every `self._engine is None` guard read an idle unload as
  "not started" and drop the burst.

How it meets the rest of §1:

- **The decision** is `system/residency.py`: `with_stt_idle_unload(s)` gives the `stt` row
  a keep-alive of `s` (which also unpins it), `IdleTracker` decides when it is due, and
  `unload_tick_s` sets the tick to a quarter of the keep-alive, clamped to 1–30 s.
- **The tick** is a thread beside the portal reaper (`Daemon._start_stt_idle_unloader`).
  It releases the model only while the daemon state is IDLE or PAUSED, checked under
  `Daemon._lock`. `IdleUnloadEngine.detach_if_idle()` never blocks and refuses while any
  decode is counted in.
- **The reload** starts at the press (`prefetch`), after the recorder is already running,
  so capture never waits and the press's audio is kept. If the model is still loading at
  release, the burst shows the existing LOADING state, and it returns to TRANSCRIBING when
  the load ends.

**2026-10-23, step 1b: status.** The daemon's `status` reply carries `stt_residency`
(`IdleUnloadEngine.residency_snapshot`: `idle_unload_s`, `loaded`, `loading`, `idle_s`),
`null` while the key is `0`. `yazses status` and the tray render it through
`residency.describe_stt_residency`. The read only *tries* the engine lock and uses
`IdleTracker.last_use`, which reads no clock, so a status poll never waits on a decode.
A follow-up the same day added `unloaded_after_s` and `unloaded_for_s`. `detach_if_idle`
stamps the release time and the idle time it measured, so "unloaded after N s idle" is
what happened, not the configured keep-alive, which a late tick overshoots. The
snapshot reads both stamps the same lock-free way, and it reads "how long ago" from the
wrapper's clock directly, never through the tracker's monotonic check.

Not done in this step and still open: `ResidencyBudget` and `[residency] max_resident`;
`[residency] keep_alive_s` and the unload hooks for `latency`, `diarize`, `gaze`, `tts`,
`llm` and `voiceprint`; the worker processes (§2); the nightly RSS, idle-CPU and
release-after-unload jobs (§4); and the consent-time RAM figures (§5). Also open: how much
RSS an `stt` unload actually returns. CTranslate2 may keep its arena, and the nightly
"release" row is what measures that.

## Consequences

**Positive**

- The brief's second half becomes true: RAM and CPU track what is *in use*. A user with
  everything enabled and nothing in use for ten minutes holds the engine and nothing else.
- Faults in the heaviest stacks stop reaching dictation.
- The ADR-018 §3 boundary exists in first-party form, costed and measured, before anyone
  asks for plug-ins again.
- Regressions in RAM become a report with a number, not a user noticing.

**Negative, accepted**

- A reload after idle costs latency on the first use after a gap — seconds for a worker
  that must re-import torch. The defaults are long enough that an active user never
  sees it, and every number is a key.
- A worker is more code: process lifecycle, a socket, a relay stub per Protocol, and a
  crash path. It is paid for by the four stacks that most need it, in the order the
  nightly table ranks them.
- Two numbers in §1 and the retention claim in *Context* are [O]/[U] until the nightly
  measures them; the ADR records that rather than presenting them as facts.

## Alternatives considered

- **Unload everything after idle, the engine included.** Rejected: first-word latency is
  the product, and the default user did not ask to trade it. Offered as `idle_unload_s`.
- **Unload in process and trust `del` + `gc.collect()`.** Rejected as the *only*
  mechanism: the native allocators keep their arenas, so RSS would not move for the
  stacks that matter. Kept for the small in-process units, with the nightly measuring
  how much it returns.
- **One worker for all heavy features.** Rejected: a MediaPipe crash would then take the
  cleaner with it, and the torch stack's conflicting DLLs would poison the shared
  environment. One worker per unit; a unit is already the unloading granularity.
- **Subinterpreters (PEP 734) as the boundary.** Rejected: many native packages do not
  support them, and they share the allocator, so neither the fault nor the release
  property holds (research note §3).
- **Per-feature virtual environments for in-process features.** Rejected (research note
  §6): duplicates numpy and ONNX Runtime and cannot share one process.
- **A PR-gated RSS budget.** Rejected: it needs real models and minutes; a slow PR gate is
  one contributors learn to retry. Nightly, with a report.
- **Fixed slot counts instead of LRU.** Rejected: which two heavy features a user runs
  together is their choice; recency is the one signal that follows it without a setting.

## Test plan

Landed with this ADR, in `tests/test_residency.py` (pure, no mocks): the policy table
equals the seconds above; an unknown unit raises; a keep-alive fires at the boundary and
not before, a touch restarts it, a `None` row is never due, due units come longest-idle
first; LRU order, re-admission refreshes, a pinned unit is never evicted, a cap of one with
a pin reports `over_budget`, cap changes evict on the next admit; the worker table equals
`{gaze, llm, voiceprint, diarize}` and the policy's `worker_required` flags agree with it;
`check_rss` reports each breach with the amount over, honours a tolerance, ignores an
unbudgeted unit, refuses an empty measurement; NaN, infinite and negative inputs and a
clock running backwards raise; the module imports only the standard library.

To land with the integration: the daemon's tick unloads a unit at its keep-alive and the
next use reloads it; `EnginePool` consults the budget; a worker crash degrades its unit
and the daemon survives; the nightly job writes `runtime_sizes.json` and fails on a
breach, an unmeasured unit, or an empty run.
